"""Pure logic behind the TUI: sorting, filtering, row text and the process tree.

Nothing here imports Textual, so it is tested without a terminal.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Generic, NamedTuple, TypeVar

from rich.console import Group, RenderableType
from rich.text import Text
from rich.tree import Tree

from clawtop import ui
from clawtop.procs import MB, Proc, Snapshot, Stack

# Sort keys, in the order the sort menu lists them.
SORT_KEYS = ("mem", "idle", "age", "pid", "agent", "runtime")
DEFAULT_SORT = "mem"

# Table column key -> sort key (clicking a header sorts by it). Columns not listed are not sortable.
COLUMN_SORT = {"pid": "pid", "runtime": "runtime", "agent": "agent", "idle": "idle", "age": "age", "mem": "mem"}
# What the sort menu calls each key.
SORT_LABELS = {"mem": "Memory", "idle": "Idle", "age": "Age", "pid": "PID", "agent": "Agent", "runtime": "Runtime"}
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
        Text(flag, style="bold magenta" if flag == "ORPHAN" else "bold red"),
        Text(ui.parts_text(stack.parts, 24)),
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


# Series colours of the memory graph and its legend (also used by the legend swatches).
GATEWAY_STYLE, RUNS_STYLE, OTHER_STYLE = "#ffaf3d", "#5ccfe6", "#c792ea"


def pipe_bar(used: float, total: float, width: int) -> Text:
    """A bottom-style gauge, ``[|||||     ]``, coloured by how full it is."""
    inner = max(1, width - 2)
    ratio = min(1.0, used / total) if total else 0.0
    filled = round(ratio * inner)
    t = Text("[", style="dim")
    t.append("|" * filled, style=ui.level_style(ratio))
    t.append(" " * (inner - filled))
    t.append("]", style="dim")
    return t


def _gauge(name: str, used: float, total: float, figures: str, bar_w: int, style: str | None = None) -> Text:
    """One meter line: name, gauge, percentage, figures. ``style`` fixes the bar colour (else by how full)."""
    ratio = min(1.0, used / total) if total else 0.0
    t = Text(f"{name:<8}", style="dim" if name.startswith(" ") else "bold")
    bar = pipe_bar(used, total, bar_w)
    if style:
        bar.stylize(style, 1, len(bar) - 1)
    t.append_text(bar)
    t.append(f" {ratio:4.0%} ", style=style or ui.level_style(ratio))
    t.append(figures)
    return t


def meters(snap: Snapshot, width: int = 46) -> RenderableType:
    """VM, gateway and swap gauges, then where the gateway's memory goes (coloured like the graph)."""
    vm_used = snap.vm_total_mb - snap.vm_avail_mb
    limit_mb = (snap.cg_high or snap.cg_max or 0) / MB
    gateway_fig = f"{ui.gib(snap.cg_mb)}/{ui.gib(limit_mb)} high" if snap.cg_high else ui.gib(snap.cg_mb)
    swap_fig = f"{ui.gib(snap.swap_used_mb)} psi {snap.psi:.1f}%"
    figures = [f"{ui.gib(vm_used)}/{ui.gib(snap.vm_total_mb)}", swap_fig]
    if snap.main_pid:
        figures.append(gateway_fig)
    bar_w = max(6, width - 8 - 6 - max(len(f) for f in figures) - 1)
    rows: list[Text] = [_gauge("VM", vm_used, snap.vm_total_mb, figures[0], bar_w)]
    if snap.main_pid:
        rows.append(_gauge("Gateway", snap.cg_mb, limit_mb or snap.vm_total_mb, gateway_fig, bar_w))
    else:
        rows.append(Text("Gateway  NOT RUNNING", style="bold red"))
    rows.append(_gauge("Swap", snap.swap_used_mb, max(snap.swap_used_mb, 4096), swap_fig, bar_w))
    if snap.main_pid:
        rows.append(Text())
        scale = limit_mb or snap.vm_total_mb
        for name, mb, style in (
            ("  main", snap.main_mb, GATEWAY_STYLE),
            ("  runs", snap.stacks_mb, RUNS_STYLE),
            ("  other", snap.infra_mb, OTHER_STYLE),
            ("  cache", snap.cg_cache_mb, "#6b7a90"),
        ):
            rows.append(_gauge(name, mb, scale, ui.gib(mb), bar_w, style))
    return Group(*rows)


class Point(NamedTuple):
    """One graph sample, in MB: the whole gateway cgroup, the agent runs inside it, and OpenClaw's other children."""

    gateway: float
    runs: float
    other: float


T = TypeVar("T")


class Ring(Generic[T]):
    """A fixed-size rolling window of samples (for the live memory graph)."""

    def __init__(self, size: int = 120) -> None:
        self._d: deque[T] = deque(maxlen=size)

    def add(self, value: T) -> None:
        self._d.append(value)

    def extend_front(self, values: Sequence[T]) -> None:
        """Seed with older samples (e.g. from the sampler log) without displacing newer ones."""
        room = (self._d.maxlen or 0) - len(self._d)
        if room > 0 and values:
            self._d.extendleft(reversed(list(values)[-room:]))

    def values(self) -> list[T]:
        return list(self._d)


# Braille cell: 2 dot columns x 4 dot rows. _DOT[row][col] is the bit for that dot.
_DOT = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


class Line(NamedTuple):
    values: Sequence[float]
    style: str


def _columns(values: Sequence[float], n: int) -> list[float | None]:
    """Fit ``values`` onto ``n`` dot columns, newest on the right. Squeezing keeps spikes (max per column)."""
    if len(values) <= n:
        return [None] * (n - len(values)) + list(values)
    step = len(values) / n
    return [max(values[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)]) for i in range(n)]


def plot(lines: Sequence[Line], width: int, height: int, ymax: float, hline: float | None = None) -> list[Text]:
    """Braille line plot: ``height`` rows of ``width`` cells, values scaled from 0 to ``ymax``.

    Later lines are drawn over earlier ones. ``hline`` adds a dotted horizontal marker (the memory limit).
    """
    width, height, ymax = max(1, width), max(1, height), max(ymax, 1e-9)
    dw, dh = width * 2, height * 4
    cells: dict[tuple[int, int], tuple[int, str]] = {}

    def dot(x: int, y: int, style: str) -> None:
        key = (x // 2, y // 4)
        cells[key] = (cells.get(key, (0, ""))[0] | _DOT[y % 4][x % 2], style)

    def row_of(v: float) -> int:
        return min(dh - 1, max(0, round((1 - min(v, ymax) / ymax) * (dh - 1))))

    if hline is not None and 0 < hline <= ymax:
        for x in range(0, dw, 3):
            dot(x, row_of(hline), "dim")
    for line in lines:
        prev: int | None = None
        for x, v in enumerate(_columns(line.values, dw)):
            if v is None:
                prev = None
                continue
            y = row_of(v)
            for yy in range(min(prev, y), max(prev, y) + 1) if prev is not None else (y,):
                dot(x, yy, line.style)  # join neighbouring samples so a line stays a line
            prev = y
    rows: list[Text] = []
    for cy in range(height):
        row = Text()
        for cx in range(width):
            mask, style = cells.get((cx, cy), (0, ""))
            row.append(chr(0x2800 + mask) if mask else " ", style=style)
        rows.append(row)
    return rows


def graph(points: Sequence[Point], width: int, height: int, limit_mb: float | None, span_s: float) -> Text:
    """The memory graph as bottom draws one: y labels, a braille plot of three series, and a time axis.

    Scaled from 0 (a flat line looks flat) up to the limit, or a little above the peak if it went past it.
    ``span_s`` is how much time the samples cover; it labels the left end of the x axis.
    """
    if not points:
        return Text("waiting for data ...", style="dim")
    height = max(2, height - 1)  # the last row is the x axis
    ymax = max(limit_mb or 0.0, max(p.gateway for p in points) * 1.05, 1.0)
    labels = [ui.gib(ymax), ui.gib(ymax / 2), "0"]
    lw = max(len(s) for s in labels)
    y_text = [""] * height
    y_text[0], y_text[-1] = labels[0], labels[2]
    if height >= 5:
        y_text[height // 2] = labels[1]
    plot_w = max(4, width - lw - 2)
    rows = plot(
        [
            Line([p.other for p in points], OTHER_STYLE),
            Line([p.runs for p in points], RUNS_STYLE),
            Line([p.gateway for p in points], GATEWAY_STYLE),
        ],
        plot_w,
        height,
        ymax,
        limit_mb,
    )
    out = Text()
    for label, row in zip(y_text, rows, strict=True):
        out.append(label.rjust(lw), style="dim")
        out.append(" \u2502", style="dim")
        out.append_text(row)
        out.append("\n")
    left, right = ui.dur(span_s), "0s"
    out.append(" " * (lw + 2), style="dim")
    out.append(left + " " * max(1, plot_w - len(left) - len(right)) + right, style="dim")
    return out


def legend(snap: Snapshot | None, limit_mb: float | None) -> Text:
    """The graph's key: one swatch per series with its current value, the limit, and the page cache."""
    t = Text()
    if snap is None:
        return t
    for name, style, mb in (
        ("Gateway", GATEWAY_STYLE, snap.cg_mb),
        ("Runs", RUNS_STYLE, snap.stacks_mb),
        ("Other", OTHER_STYLE, snap.infra_mb),
    ):
        t.append("\u2501\u2501 ", style=style)
        t.append(f"{name:<8}")
        t.append(f"{ui.gib(mb):>6}\n", style=style)
    if limit_mb:
        t.append("\u2504\u2504 ", style="dim")
        t.append(f"{'limit':<8}{ui.gib(limit_mb):>6}\n", style="dim")
    t.append(f"\n   {'cache':<8}{ui.gib(snap.cg_cache_mb):>6}", style="dim")
    return t
