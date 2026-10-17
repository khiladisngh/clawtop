"""Rich renderers. Pure functions of data -> renderables, so they are trivial to test."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from clawtop.history import Sample, sparkline
from clawtop.procs import MB, Snapshot, Stack
from clawtop.sessions import Node, Session

STALE_IDLE_MIN = 30


def dur(s: float) -> str:
    s = int(s)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s // 3600}h{s % 3600 // 60:02d}m"
    return f"{s // 86400}d"


def gib(mb: float) -> str:
    return f"{mb / 1024:.1f}G" if mb >= 1024 else f"{mb:.0f}M"


def level_style(ratio: float) -> str:
    return "green" if ratio < 0.6 else "yellow" if ratio < 0.85 else "bold red"


def bar(used: float, total: float, width: int = 24) -> Text:
    ratio = min(1.0, used / total) if total else 0.0
    filled = round(ratio * width)
    t = Text()
    t.append("█" * filled, style=level_style(ratio))
    t.append("░" * (width - filled), style="dim")
    t.append(f" {ratio:4.0%}", style=level_style(ratio))
    return t


def _table(*cols: str, right: frozenset[str] = frozenset(), numbered: bool = False) -> Table:
    t = Table(box=None, pad_edge=False, header_style="bold dim", show_edge=False)
    if numbered:
        t.add_column("#", justify="right", style="bold cyan")
    for c in cols:
        t.add_column(c, justify="right" if c in right else "left")
    return t


def parts_text(parts: Sequence[str], each: int = 11) -> str:
    short = [p if len(p) <= each else p[: each - 1] + "\u2026" for p in parts]
    return ",".join(short) or "-"


def no_stacks_note(snap: Snapshot) -> str:
    if not snap.workspaces_known:
        return "  none found: no agent workspaces in the OpenClaw config (set CLAWTOP_WORKSPACES)"
    return "  none. Runtimes that run inside the gateway (openclaw, codex, ...) have no process of their own."


def stacks_table(stacks: Sequence[Stack], stale_min: float = STALE_IDLE_MIN, numbered: bool = False) -> Table:
    t = _table(
        "PID", "RUNTIME", "AGENT", "IDLE", "AGE", "CTX", "MEM", "PARTS", "",
        right=frozenset({"PID", "IDLE", "AGE", "CTX", "MEM"}),
        numbered=numbered,
    )  # fmt: skip
    for i, s in enumerate(stacks, 1):
        stale = s.is_idle_over(stale_min)
        flag = (
            Text("ORPHAN", style="bold magenta")
            if s.kind == "orphan"
            else Text("STALE", style="bold red")
            if stale
            else Text()
        )
        mem_style = "bold red" if s.mb > 700 else "yellow" if s.mb > 400 else "green"
        cells: list[RenderableType] = [
            str(s.pid),
            s.runtime,
            s.agent,
            Text(dur(s.idle_s) if s.idle_s is not None else "-", style="red" if stale else ""),
            dur(s.age_s),
            f"{s.transcript.size_mb:.1f}M" if s.transcript else "-",
            Text(gib(s.mb), style=mem_style),
            parts_text(s.parts),
            flag,
        ]
        t.add_row(*([str(i)] if numbered else []), *cells)
    return t


def status(snap: Snapshot, stale_min: float = STALE_IDLE_MIN) -> RenderableType:
    head = Text()
    if snap.main_pid:
        head.append(f"gateway pid {snap.main_pid}", style="bold")
        head.append(f"  up {dur(snap.main_age_s)}", style="dim")
    else:
        head.append("gateway NOT RUNNING", style="bold red")

    vm_used = snap.vm_total_mb - snap.vm_avail_mb
    g = Table.grid(padding=(0, 2))
    g.add_row("VM", bar(vm_used, snap.vm_total_mb), f"{gib(vm_used)} / {gib(snap.vm_total_mb)}")
    notes = [f"vm: swap {gib(snap.swap_used_mb)} · memory pressure {snap.psi:.1f}%"]
    if snap.main_pid:
        limit_mb = (snap.cg_high or snap.cg_max or 0) / MB
        if snap.cg_high and snap.cg_max:
            detail = f"{gib(snap.cg_mb)} / {gib(snap.cg_high / MB)} high"
            cap = f" · hard max {gib(snap.cg_max / MB)}"
        else:
            detail, cap = f"{gib(snap.cg_mb)} (no limit)", ""
        g.add_row("Gateway", bar(snap.cg_mb, limit_mb or snap.vm_total_mb), detail)
        notes.append(
            f"gateway: main {gib(snap.main_mb)} · run stacks {gib(snap.stacks_mb)} · other {gib(snap.infra_mb)}"
        )
        notes.append(f"gateway: page cache {gib(snap.cg_cache_mb)} (reclaimable){cap}")

    stale = sum(1 for s in snap.stacks if s.is_idle_over(stale_min))
    hint = "clawtop kill" + (f"   [{stale} stale: clawtop kill --idle {stale_min:g}]" if stale else "")
    body: list[RenderableType] = [
        g,
        *(Text(n, style="dim") for n in notes),
        Text(),
        Text(f"Agent run stacks ({len(snap.stacks)})", style="bold"),
        stacks_table(snap.stacks, stale_min) if snap.stacks else Text(no_stacks_note(snap), style="dim"),
        Text(),
        Text(hint, style="dim"),
    ]
    return Panel(Group(*body), title=head, title_align="left", border_style="cyan", padding=(1, 2))


def sessions_table(sessions: Sequence[Session], numbered: bool = False, titles: bool = False) -> Table:
    t = _table(
        "AGENT",
        "KIND",
        "RUNTIME",
        "STATUS",
        "IDLE",
        "TOKENS",
        *(["TITLE"] if titles else []),
        "KEY",
        right=frozenset({"IDLE", "TOKENS"}),
        numbered=numbered,
    )
    for i, s in enumerate(sessions, 1):
        cells: list[RenderableType] = [
            s.agent,
            s.kind,
            Text(s.runtime or "-", style="" if s.runtime else "dim"),
            Text(s.status, style="green" if s.is_open else "dim"),
            dur(s.idle_s),
            f"{s.tokens:,}" if s.tokens else "-",
            *([Text(s.label or "-", style="" if s.label else "dim")] if titles else []),
            Text(s.key, style="dim"),
        ]
        t.add_row(*([str(i)] if numbered else []), *cells)
    return t


def node_text(n: Node) -> Text:
    s = n.session
    t = Text()
    t.append(f"{s.kind} ", style="bold cyan" if s.kind == "subagent" else "bold")
    tail = s.key.split(":", 2)[2]
    if s.label or tail != s.kind:  # "main main" adds nothing
        t.append(s.label or tail, style="" if n.selected else "dim")
    t.append(f"  {dur(s.idle_s)} idle", style="dim")
    if s.tokens:
        t.append(f"  {s.tokens:,} tok", style="dim")
    if not s.is_open:
        t.append(f"  [{s.status}]", style="dim")
    if not n.selected:
        t.append("  (parent)", style="dim italic")
    return t


def sessions_tree(roots: Sequence[Node]) -> RenderableType:
    """One tree per agent: parent sessions with the subagents they spawned nested underneath."""
    if not roots:
        return Text("No sessions.", style="dim")
    trees: list[RenderableType] = []
    for agent in dict.fromkeys(r.session.agent for r in roots):
        mine = [r for r in roots if r.session.agent == agent]
        tree = Tree(Text(agent, style="bold cyan"), guide_style="dim")

        def add(parent: Tree, n: Node) -> None:
            branch = parent.add(node_text(n))
            for c in n.children:
                add(branch, c)

        for r in mine:
            add(tree, r)
        trees.append(tree)
    return Group(*trees)


def history(rows: Sequence[Sample], width: int = 64) -> RenderableType:
    if not rows:
        return Text("No samples in that window. Run `clawtop sampler install`.", style="yellow")
    cg = [r["cg_mb"] for r in rows]
    swap = [r["swap_used"] for r in rows]
    peak_i = max(range(len(rows)), key=lambda i: cg[i])
    peak = rows[peak_i]
    t0, t1 = datetime.fromtimestamp(rows[0]["ts"]), datetime.fromtimestamp(rows[-1]["ts"])

    g = Table.grid(padding=(0, 2))
    g.add_row("window", f"{t0:%a %H:%M} -> {t1:%a %H:%M}   {len(rows)} samples")
    g.add_row("gateway", Text(sparkline(cg, width), style="cyan"))
    g.add_row(
        "",
        f"[dim]min {gib(min(cg))}   now {gib(cg[-1])}   [/][bold]peak {gib(cg[peak_i])}[/] "
        f"[dim]at {datetime.fromtimestamp(peak['ts']):%H:%M}[/]",
    )
    if max(swap) > 50:
        g.add_row("swap", Text(sparkline(swap, width), style="yellow"))
        g.add_row("", f"[dim]peak {gib(max(swap))}[/]")

    parts: list[RenderableType] = [g]
    if peak["stacks"]:
        tb = _table("PID", "AGENT", "MEM", "AGE", right=frozenset({"PID", "MEM", "AGE"}))
        for pid, agent, mb, age_min in peak["stacks"]:
            tb.add_row(str(pid), str(agent), gib(float(mb)), dur(float(age_min) * 60))
        parts += [Text(), Text(f"stacks at peak ({len(peak['stacks'])})", style="bold"), tb]
    return Panel(Group(*parts), title="memory history", title_align="left", border_style="cyan", padding=(1, 2))
