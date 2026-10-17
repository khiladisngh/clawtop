"""clawtop command line (Typer)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from clawtop import history as hist
from clawtop import sampler as sampler_mod
from clawtop import sessions as sess
from clawtop import ui
from clawtop.procs import Snapshot, Stack, kill_stack, take_snapshot

out = Console()
err = Console(stderr=True)

app = typer.Typer(
    help="[bold]clawtop[/]: htop for OpenClaw. See gateway memory per agent run, kill runaway "
    "runs, and manage open sessions.\n\nRun with no command for a live-at-a-glance status.",
    rich_markup_mode="rich",
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
sessions_app = typer.Typer(
    help="List, archive and prune OpenClaw sessions.", rich_markup_mode="rich", no_args_is_help=True
)
sampler_app = typer.Typer(help="Background memory sampling (systemd user timer).", no_args_is_help=True)
app.add_typer(sessions_app, name="sessions")
app.add_typer(sampler_app, name="sampler")

StaleOpt = Annotated[int, typer.Option("--stale-min", help="Minutes without activity before a run is flagged STALE.")]


def _version(show: bool) -> None:
    if show:
        typer.echo(f"clawtop {pkg_version('clawtop')}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    _version_flag: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        out.print(ui.status(take_snapshot()))


@contextmanager
def _openclaw_errors() -> Generator[None]:
    try:
        yield
    except (sess.OpenClawError, ValueError) as e:
        err.print(f"[red]error:[/] {e}")
        raise typer.Exit(1) from e


# --------------------------------------------------------------------------- status / watch


@app.command()
def status(
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    stale_min: StaleOpt = ui.STALE_IDLE_MIN,
) -> None:
    """Show VM and gateway memory and every agent run stack."""
    snap = take_snapshot()
    if json_out:
        import json

        typer.echo(json.dumps(snap.to_dict(), indent=2))
    else:
        out.print(ui.status(snap, stale_min))


@app.command()
def watch(
    interval: Annotated[float, typer.Option("--interval", "-i", min=0.5, help="Seconds between refreshes.")] = 3.0,
    stale_min: StaleOpt = ui.STALE_IDLE_MIN,
) -> None:
    """Live view, refreshed every few seconds. Ctrl-C to quit."""
    from rich.live import Live

    try:
        with Live(ui.status(take_snapshot(), stale_min), console=out, screen=True, auto_refresh=False) as live:
            while True:
                time.sleep(interval)
                live.update(ui.status(take_snapshot(), stale_min), refresh=True)
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------- kill


def _targets(
    snap: Snapshot, pids: list[int], idle: float | None, older_than: float | None, orphans: bool
) -> list[Stack]:
    by_pid = {s.pid: s for s in snap.stacks}
    picked: dict[int, Stack] = {}
    for pid in pids:
        if pid not in by_pid:
            raise ValueError(f"{pid} is not an agent run-stack leader (see `clawtop status`)")
        picked[pid] = by_pid[pid]
    unknown = 0
    for s in snap.stacks:
        if idle is not None and s.idle_s is None:
            unknown += 1
        if (
            (idle is not None and s.is_idle_over(idle))
            or (older_than is not None and s.age_s > older_than * 60)
            or (orphans and s.kind == "orphan")
        ):
            picked[s.pid] = s
    if unknown:
        err.print(
            f"[dim]{unknown} run(s) skipped by --idle: this runtime has no activity source, so idle time is "
            "unknown. Use --older-than or name the PID.[/]"
        )
    return sorted(picked.values(), key=lambda s: -s.mb)


def _choose(items: list[Stack], stale_min: int) -> list[Stack]:
    """Interactive picker: numbers, 'stale' or 'all'."""
    out.print(ui.stacks_table(items, stale_min, numbered=True))
    ans = (
        typer.prompt(
            "\nKill which? numbers (1 3), 'stale', 'all'; Enter cancels",
            default="",
            show_default=False,
        )
        .strip()
        .lower()
    )
    if ans == "all":
        return items
    if ans == "stale":
        return [s for s in items if s.kind == "orphan" or s.is_idle_over(stale_min)]
    idx = [int(x) for x in re.split(r"[\s,]+", ans) if x]
    if any(not 1 <= i <= len(items) for i in idx):
        raise ValueError(f"pick numbers between 1 and {len(items)}")
    return [items[i - 1] for i in idx]


@app.command()
def kill(
    pids: Annotated[list[int] | None, typer.Argument(help="Run-stack leader PID(s) from `clawtop status`.")] = None,
    idle: Annotated[
        float | None,
        typer.Option("--idle", help="Kill runs with no activity for this many minutes."),
    ] = None,
    older_than: Annotated[
        float | None, typer.Option("--older-than", help="Kill runs older than this many minutes.")
    ] = None,
    orphans: Annotated[
        bool, typer.Option("--orphans", help="Kill gateway-signed stacks whose parent is gone.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be killed.")] = False,
    grace: Annotated[float, typer.Option(help="Seconds between SIGTERM and SIGKILL.")] = 5.0,
    stale_min: StaleOpt = ui.STALE_IDLE_MIN,
) -> None:
    """Kill whole run stacks: an agent run process and everything it started (MCP servers, helpers).

    Only processes the gateway spawned can be selected; processes you started yourself are never touched.
    With no selector this opens an interactive picker.
    """
    snap = take_snapshot()
    with _openclaw_errors():
        selectors = bool(pids) or idle is not None or older_than is not None or orphans
        if selectors:
            chosen = _targets(snap, pids or [], idle, older_than, orphans)
        elif not snap.stacks:
            out.print("[dim]No agent run stacks.[/]")
            return
        elif not sys.stdin.isatty():
            raise ValueError("no selector given and not a terminal; pass PIDs, --idle, --older-than or --orphans")
        else:
            chosen = _choose(snap.stacks, stale_min)
    if not chosen:
        out.print("[dim]Nothing to kill.[/]")
        return
    out.print(ui.stacks_table(chosen, stale_min))
    out.print(f"\n{len(chosen)} stack(s), {ui.gib(sum(s.mb for s in chosen))} to free.")
    if dry_run:
        return
    if not yes and not typer.confirm("Kill?", default=False):
        raise typer.Exit(1)
    alive: list[int] = []
    for s in chosen:
        left = kill_stack(s, grace_s=grace)
        alive += left
        out.print(f"  {s.pid} {s.agent}: " + (f"[red]survivors {left}[/]" if left else "[green]killed[/]"))
    if alive:
        raise typer.Exit(1)


# --------------------------------------------------------------------------- history / sample


def _span(text: str) -> float:
    m = re.fullmatch(r"(\d+)([mhd])", text.strip().lower())
    if not m:
        raise typer.BadParameter("use a number plus m, h or d (e.g. 90m, 6h, 2d)")
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]


@app.command()
def history(
    last: Annotated[str, typer.Option("--last", "-l", help="Window: 90m, 6h, 2d.")] = "6h",
    log: Annotated[
        str | None,
        typer.Option(help="Samples file (default $CLAWTOP_LOG or <OpenClaw state dir>/logs/mem-samples.jsonl)."),
    ] = None,
) -> None:
    """Memory timeline from the sampler: sparkline, peak, and the stacks alive at the peak."""
    path = Path(log).expanduser() if log else hist.default_log()
    out.print(ui.history(hist.load(path, _span(last))))


@app.command(hidden=True)
def sample() -> None:
    """Append one sample to the history log (run by the systemd timer)."""
    hist.append_sample(take_snapshot(), hist.default_log())


@sampler_app.command("install")
def sampler_install() -> None:
    """Install and start a systemd user timer that samples every minute."""
    try:
        d = sampler_mod.install()
    except (RuntimeError, subprocess.CalledProcessError) as e:
        err.print(f"[red]error:[/] {getattr(e, 'stderr', None) or e}")
        raise typer.Exit(1) from e
    out.print(f"[green]installed[/] {d / sampler_mod.TIMER}; samples go to {hist.default_log()}")


@sampler_app.command("uninstall")
def sampler_uninstall() -> None:
    """Stop and remove the sampler timer."""
    sampler_mod.uninstall()
    out.print("[green]removed[/]")


# --------------------------------------------------------------------------- sessions


def _pick(
    rows: list[sess.Session], all_: bool, agent: list[str] | None, kind: list[str] | None, idle_min: float
) -> list[sess.Session]:
    if not all_:
        return sess.select(rows, idle_s=idle_min * 60, kinds=kind, agents=agent)
    return sorted(
        (
            s
            for s in rows
            if (not agent or s.agent in agent) and (not kind or s.kind in kind) and s.idle_s >= idle_min * 60
        ),
        key=lambda s: -s.idle_s,
    )


AllOpt = Annotated[bool, typer.Option("--all", "-a", help="Include finished sessions.")]
AgentOpt = Annotated[list[str] | None, typer.Option("--agent", help="Only these agents.")]
KindOpt = Annotated[
    list[str] | None, typer.Option("--kind", help="Only these kinds (subagent, cron, discord, main, node).")
]
IdleMinOpt = Annotated[float, typer.Option("--idle-min", help="Only sessions idle at least this long.")]


@sessions_app.command("list")
def sessions_list(
    all_: AllOpt = False,
    agent: AgentOpt = None,
    kind: KindOpt = None,
    idle_min: IdleMinOpt = 0,
    titles: Annotated[bool, typer.Option("--titles", "-t", help="Add the session title (label) column.")] = False,
) -> None:
    """List sessions (open ones by default), longest idle first."""
    with _openclaw_errors():
        rows = _pick(sess.list_sessions(), all_, agent, kind, idle_min)
    out.print(ui.sessions_table(rows, titles=titles))
    out.print(
        f"\n[dim]{len(rows)} session(s). Close with `clawtop sessions archive KEY` or `clawtop sessions prune`.[/]"
    )


@sessions_app.command("tree")
def sessions_tree(
    all_: AllOpt = False,
    agent: AgentOpt = None,
    kind: KindOpt = None,
    idle_min: IdleMinOpt = 0,
    within: Annotated[
        float, typer.Option("--within", help="Also show finished sessions active in the last N hours (0 = open only).")
    ] = 6,
) -> None:
    """Sessions grouped by agent, with subagents nested under the session that spawned them (titles shown).

    Subagents finish within minutes, so finished ones from the last few hours are included by default.
    """
    with _openclaw_errors():
        everything = sess.list_sessions()
    if all_:
        picked = _pick(everything, True, agent, kind, idle_min)
    else:
        picked = sess.select(everything, idle_s=idle_min * 60, kinds=kind, agents=agent, recent_s=within * 3600)
    out.print(ui.sessions_tree(sess.build_tree(picked, everything)))
    out.print(f"\n[dim]{len(picked)} session(s); dim rows are parents shown for context.[/]")


def _archive(items: list[sess.Session], yes: bool, dry_run: bool) -> None:
    if not items:
        out.print("[dim]Nothing to archive.[/]")
        return
    out.print(ui.sessions_table(items, titles=True))
    if not dry_run and not yes and not typer.confirm(f"\nArchive {len(items)} session(s)?", default=False):
        raise typer.Exit(1)
    with _openclaw_errors():
        results = sess.archive(items, dry_run=dry_run)
    bad = [r for r in results if not r.get("ok")]
    verb = "would archive" if dry_run else "archived"
    out.print(f"\n[green]{len(results) - len(bad)} {verb}[/]" + (f", [red]{len(bad)} failed[/]: {bad}" if bad else ""))
    if bad:
        raise typer.Exit(1)


@sessions_app.command("archive")
def sessions_archive(
    keys: Annotated[list[str], typer.Argument(help="Session keys, e.g. agent:<id>:subagent:<uuid>.")],
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Archive specific sessions by key."""
    with _openclaw_errors():
        items = [sess.from_key(k) for k in keys]
    _archive(items, yes, dry_run)


@sessions_app.command("prune")
def sessions_prune(
    idle_hours: Annotated[
        float, typer.Option("--idle-hours", help="Archive open sessions idle at least this long.")
    ] = 6,
    kind: Annotated[
        list[str] | None,
        typer.Option("--kind", help="Kinds to prune (repeatable). Default: subagent."),
    ] = None,
    agent: Annotated[list[str] | None, typer.Option("--agent", help="Limit to these agents.")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Archive open sessions that have gone idle (subagents by default; channels are kept)."""
    with _openclaw_errors():
        items = sess.select(
            sess.list_sessions(),
            idle_s=idle_hours * 3600,
            kinds=kind or sess.DEFAULT_PRUNE_KINDS,
            agents=agent,
        )
    _archive(items, yes, dry_run)


# --------------------------------------------------------------------------- entry


def _forward_to_wsl(argv: list[str]) -> int:
    """On Windows the gateway lives in WSL: run the same command there, inheriting the console.

    Uses your default WSL distro and user unless CLAWTOP_WSL_DISTRO / CLAWTOP_WSL_USER are set.
    """
    distro = os.environ.get("CLAWTOP_WSL_DISTRO")
    user = os.environ.get("CLAWTOP_WSL_USER")
    cmd = [
        "wsl.exe",
        *(["-d", distro] if distro else []),
        *(["-u", user] if user else []),
        "-e",
        "bash",
        "-lc",
        'exec clawtop "$@"',
        "clawtop",
        *argv,
    ]
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        err.print("[red]error:[/] wsl.exe not found")
        return 1


def main() -> None:
    if sys.platform == "win32":
        raise SystemExit(_forward_to_wsl(sys.argv[1:]))
    app()
