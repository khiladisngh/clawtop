"""Pure logic behind the TUI: sorting, filtering, row text and the process tree.

Nothing here imports Textual, so it is tested without a terminal.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from rich.console import Group, RenderableType
from rich.text import Text
from rich.tree import Tree

from clawtop import ui
from clawtop.procs import MB, Proc, Snapshot, Stack

# Sort keys, in the order `s` cycles through them.
SORT_KEYS = ("mem", "idle", "age", "pid", "agent", "runtime")
DEFAULT_SORT = "mem"

# Table column key -> sort key (clicking a header sorts by it). Columns not listed are not sortable.
COLUMN_SORT = {"pid": "pid", "runtime": "runtime", "agent": "agent", "idle": "idle", "age": "age", "mem": "mem"}
# Natural direction when a key is first chosen: biggest/oldest first, names A-Z.
NATURAL_DESC = {"mem": True, "idle": True, "age": True, "pid": False, "agent": False, "runtime": False}

SPANS = (("1h", 3600), ("6h", 6 * 3600), ("24h", 24 * 3600), ("7d", 7 * 86400))
WINDOWS = (0, 6, 24)  # sessions tree: hours of finished sessions to include


def next_in(options: Sequence[str], current: str) -> str:
    """The option after ``current`` (wrapping); the first one if ``current`` is unknown."""
    if current not in options:
        return options[0]
    return options[(options.index(current) + 1) % len(options)]


def sort_stacks(stacks: Sequence[Stack], key: str, descending: bool) -> list[Stack]:
    """Sort stacks by ``key``. Runs whose idle time is unknown always go last for ``idle``."""
    if key == "idle":
        known = [s for s in stacks if s.idle_s is not None]
        unknown = [s for s in stacks if s.idle_s is None]
        known.sort(key=lambda s: s.idle_s or 0.0, reverse=descending)
        return known + sorted(unknown, key=lambda s: -s.mb)
    return sorted(stacks, key=lambda s: _sort_value(s, key), reverse=descending)


def _sort_value(s: Stack, key: str) -> tuple[float | str, int]:
    """Comparable value for a sort key; the PID breaks ties so the order is stable."""
    if key == "age":
        return (s.age_s, s.pid)
    if key == "pid":
        return (s.pid, s.pid)
    if key == "agent":
        return (s.agent.lower(), s.pid)
    if key == "runtime":
        return (s.runtime.lower(), s.pid)
    return (s.mb, s.pid)


def filter_stacks(stacks: Sequence[Stack], text: str) -> list[Stack]:
    """Stacks matching every whitespace-separated term, case-insensitively, in any field."""
    terms = text.lower().split()
    if not terms:
        return list(stacks)

    def haystack(s: Stack) -> str:
        return " ".join([str(s.pid), s.runtime, s.agent, s.session_id, s.kind, *s.parts]).lower()

    return [s for s in stacks if all(t in haystack(s) for t in terms)]


def flag_of(stack: Stack, stale_min: float) -> str:
    if stack.kind == "orphan":
        return "ORPHAN"
    return "STALE" if stack.is_idle_over(stale_min) else ""


def stack_cells(stack: Stack, stale_min: float, marked: bool) -> list[Text]:
    """One table row as styled text. Numbers are right-aligned."""

    def right(s: str, style: str = "") -> Text:
        return Text(s, style=style, justify="right")

    flag = flag_of(stack, stale_min)
    mem_style = "bold red" if stack.mb > 700 else "yellow" if stack.mb > 400 else "green"
    return [
        Text("\u2714" if marked else " ", style="bold cyan"),
        right(str(stack.pid)),
        Text(stack.runtime),
        Text(stack.agent),
        right(ui.dur(stack.idle_s) if stack.idle_s is not None else "-", "red" if flag == "STALE" else ""),
        right(ui.dur(stack.age_s)),
        right(f"{stack.transcript.size_mb:.1f}M" if stack.transcript else "-"),
        right(ui.gib(stack.mb), mem_style),
        Text(ui.parts_text(stack.parts, 14)),
        Text(flag, style="bold magenta" if flag == "ORPHAN" else "bold red"),
    ]


def stack_tree(stack: Stack) -> Tree:
    """The stack's processes as a tree (leader at the top), each with its memory."""
    by_parent: dict[int, list[Proc]] = {}
    pids = {p.pid for p in stack.procs}
    for p in stack.procs:
        if p.pid != stack.leader.pid and p.ppid in pids:
            by_parent.setdefault(p.ppid, []).append(p)

    def label(p: Proc) -> Text:
        t = Text(p.label, style="bold" if p.pid == stack.leader.pid else "")
        t.append(f"  {p.pid}", style="dim")
        t.append(f"  {ui.gib(p.mb)}", style="cyan")
        return t

    root = Tree(label(stack.leader), guide_style="dim")

    def add(node: Tree, parent: Proc) -> None:
        for child in sorted(by_parent.get(parent.pid, []), key=lambda c: -c.mb):
            add(node.add(label(child)), child)

    add(root, stack.leader)
    return root


def meters(snap: Snapshot, width: int = 28) -> RenderableType:
    """VM and gateway memory bars plus the figures that explain them."""
    vm_used = snap.vm_total_mb - snap.vm_avail_mb
    rows: list[Text] = []

    def row(name: str, bar: Text, detail: str) -> Text:
        t = Text(f"{name:<8}", style="bold")
        t.append_text(bar)
        t.append(f"  {detail}")
        return t

    rows.append(row("VM", ui.bar(vm_used, snap.vm_total_mb, width), f"{ui.gib(vm_used)} / {ui.gib(snap.vm_total_mb)}"))
    if snap.main_pid:
        limit_mb = (snap.cg_high or snap.cg_max or 0) / MB
        detail = f"{ui.gib(snap.cg_mb)} / {ui.gib(limit_mb)} high" if snap.cg_high else f"{ui.gib(snap.cg_mb)}"
        rows.append(row("Gateway", ui.bar(snap.cg_mb, limit_mb or snap.vm_total_mb, width), detail))
    else:
        rows.append(Text("Gateway  NOT RUNNING", style="bold red"))
    swap = Text(f"{'Swap':<8}", style="bold")
    swap.append_text(ui.bar(snap.swap_used_mb, max(snap.swap_used_mb, 4096), width))
    swap.append(f"  {ui.gib(snap.swap_used_mb)}   pressure {snap.psi:.1f}%")
    rows.append(swap)
    notes = Text(
        f"main {ui.gib(snap.main_mb)} \u00b7 stacks {ui.gib(snap.stacks_mb)} \u00b7 other {ui.gib(snap.infra_mb)}"
        f" \u00b7 cache {ui.gib(snap.cg_cache_mb)}",
        style="dim",
    )
    return Group(*rows, notes)


class Ring:
    """A fixed-size rolling window of samples (for the live memory graph)."""

    def __init__(self, size: int = 120) -> None:
        self._d: deque[float] = deque(maxlen=size)

    def add(self, value: float) -> None:
        self._d.append(value)

    def extend_front(self, values: Sequence[float]) -> None:
        """Seed with older samples (e.g. from the sampler log) without displacing newer ones."""
        room = (self._d.maxlen or 0) - len(self._d)
        if room > 0 and values:
            self._d.extendleft(reversed(list(values)[-room:]))

    def values(self) -> list[float]:
        return list(self._d)


_EIGHTHS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def graph(values: Sequence[float], width: int, height: int, limit_mb: float | None = None) -> Text:
    """A bottom-style block graph, newest sample on the right, scaled from 0 up to the memory limit.

    Scaling from zero (not from the window's minimum) keeps a flat line looking flat. The ceiling is the
    limit, or a little above the peak if the peak went past it. Bars are coloured by how close to the
    limit they are, and a dotted line marks the limit when it is on screen.
    """
    width, height = max(1, width), max(1, height)
    if not values:
        return Text("waiting for data ...", style="dim")
    step = len(values) / width if len(values) > width else 1.0
    cols: list[float | None] = []
    if len(values) > width:  # keep spikes: each column shows the max of the samples it covers
        for i in range(width):
            chunk = values[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)]
            cols.append(max(chunk))
    else:
        cols = [None] * (width - len(values)) + list(values)
    peak = max(values)
    ceiling = max(limit_mb or 0.0, peak * 1.05, 1.0)
    full = height * 8
    lines: list[Text] = []
    for row in range(height):  # row 0 is the top
        floor_eighths = (height - 1 - row) * 8
        line = Text()
        for v in cols:
            if v is None:
                line.append(" ")
                continue
            level = max(0, min(8, round(v / ceiling * full) - floor_eighths))
            ratio = v / (limit_mb or ceiling)
            if level:
                line.append(_EIGHTHS[level], style=ui.level_style(ratio))
            else:
                line.append(" ")
        lines.append(line)
    if limit_mb and limit_mb <= ceiling:
        row = min(height - 1, max(0, int((1 - limit_mb / ceiling) * height)))
        for i, ch in enumerate(lines[row].plain):
            if ch == " ":
                lines[row].stylize("dim", i, i + 1)
                lines[row] = Text(lines[row].plain[:i] + "\u2504" + lines[row].plain[i + 1 :], spans=lines[row].spans)
    out = Text()
    for i, line in enumerate(lines):
        out.append_text(line)
        if i < len(lines) - 1:
            out.append("\n")
    return out
