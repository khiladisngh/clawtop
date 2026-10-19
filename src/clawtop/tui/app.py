"""The interactive TUI (``clawtop``): a bottom-style dashboard of the gateway, its runs and its sessions.

Six bordered panels share the screen: the memory graph, the meters, the runs table, the process tree of the
highlighted run, the session tree and the memory history. The panel that holds the focus gets a bright border;
``e`` expands it to the whole screen and ``Esc`` brings the dashboard back.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar, TypeVar, cast, overload

from rich.console import RenderableType
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.dom import DOMNode
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import DataTable, Input, OptionList, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from clawtop import history as hist
from clawtop import sessions as sess
from clawtop import ui
from clawtop.procs import MB, Snapshot, Stack, kill_stack, take_snapshot
from clawtop.tui import model

_W = TypeVar("_W", bound=Widget)
SnapshotFn = Callable[[], Snapshot]
SessionsFn = Callable[[], list[sess.Session]]
ArchiveFn = Callable[[Sequence[sess.Session]], list[dict[str, object]]]
KillFn = Callable[[Stack], list[int]]
LoadHistoryFn = Callable[[float], list[hist.Sample]]

# Navy background, sky-blue accents (bottom's default look); orange is the gateway series in the graph.
THEME = Theme(
    name="clawtop",
    primary="#6cc4ff",
    secondary="#8fd3ff",
    accent="#ffaf3d",
    warning="#ffcc66",
    error="#ff6b81",
    success="#7fd962",
    foreground="#cbd5e1",
    background="#141b26",
    surface="#1a2331",
    panel="#1f2a3a",
    dark=True,
)

COLUMNS: tuple[tuple[str, str, int | None], ...] = (
    ("mark", " ", 1),
    ("pid", "PID", 6),
    ("runtime", "RUNTIME", 8),
    ("agent", "AGENT", 10),
    ("idle", "IDLE", 5),
    ("age", "AGE", 5),
    ("ctx", "CTX", 5),
    ("mem", "MEM", 5),
    ("flag", "STATE", 6),
    ("parts", "PARTS", 20),
)

# What each panel offers, shown on its bottom border.
HINTS = {
    "p-graph": "e expand \u00b7 + / - speed \u00b7 f freeze",
    "p-meters": "? help \u00b7 q quit",
    "p-runs": "x kill \u00b7 space mark \u00b7 A stale \u00b7 s sort \u00b7 / filter \u00b7 e expand",
    "p-detail": "",
    "p-sessions": "a archive \u00b7 w window \u00b7 e expand",
    "p-history": "h span \u00b7 e expand",
}
# Which panel owns each action; the others ignore the key.
_SCOPE: dict[str, str] = {
    "kill": "p-runs", "mark": "p-runs", "mark_stale": "p-runs", "sort": "p-runs", "invert": "p-runs",
    "filter": "p-runs", "archive": "p-sessions", "window": "p-sessions", "span": "p-history",
}  # fmt: skip
# Number keys jump to a panel: the widget that takes the focus there.
_JUMP = {"runs": "#runs-table", "sessions": "#sessions-tree", "history": "#history-scroll", "graph": "#graph"}

HELP = """\
[b]Move around[/b]
  tab / shift+tab   next / previous panel      1 runs  2 sessions  3 history  4 graph
  e                 expand the panel (Esc goes back)

[b]Runs[/b]
  up/down, j/k   move            space   mark / unmark the row
  x, F9          kill marked (or the highlighted) run
  A              mark every STALE / ORPHAN run
  s              sort menu       i   reverse   (or click a column header)
  /              filter          Esc  clear the filter

[b]Sessions[/b]
  a              archive the highlighted session
  w              window of finished sessions to show: open only, 6h, 24h

[b]History[/b]
  h              change the time span

[b]Anywhere[/b]
  f, p           freeze / resume      r   refresh now
  + / -          refresh interval     ?   this help       q   quit
"""


class Panel(Vertical):
    """A bordered box with its title in the border and a hint under it; bright while it holds the focus."""


class View(Static):
    """Text you can focus (so Tab reaches it and ``e`` can expand it)."""

    can_focus = True


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question over the current screen."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y,enter", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, title: str, body: RenderableType) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._body, id="dialog-body")

    def on_mount(self) -> None:
        dialog = self.query_one("#dialog")
        dialog.border_title = self._title
        dialog.border_subtitle = "y confirm \u00b7 n cancel"

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,q,question_mark,enter", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(HELP, id="dialog-body")

    def on_mount(self) -> None:
        dialog = self.query_one("#dialog")
        dialog.border_title = "clawtop keys"
        dialog.border_subtitle = "Esc to close"

    def action_close(self) -> None:
        self.dismiss(None)


class SortScreen(ModalScreen[str | None]):
    """bottom's sort menu: pick a column; picking the current one reverses the order."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,s", "close", "Close")]

    def __init__(self, current: str, descending: bool) -> None:
        super().__init__()
        self._current = current
        self._arrow = "\u25bc" if descending else "\u25b2"

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield OptionList(
                *(
                    Option(f"{label} {self._arrow}" if key == self._current else label, id=key)
                    for key, label in model.SORT_LABELS.items()
                ),
                id="sort-list",
            )

    def on_mount(self) -> None:
        dialog = self.query_one("#dialog")
        dialog.border_title = "Sort by"
        dialog.border_subtitle = "Enter select \u00b7 Esc close"
        menu = self.query_one("#sort-list", OptionList)
        menu.highlighted = list(model.SORT_LABELS).index(self._current) if self._current in model.SORT_LABELS else 0
        menu.focus()

    @on(OptionList.OptionSelected)
    def _picked(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_close(self) -> None:
        self.dismiss(None)


class ClawtopApp(App[None]):
    """Live gateway memory, run stacks, sessions and history in one screen."""

    TITLE = "clawtop"
    CSS = """
    Screen { background: $background; }
    .row { height: 1fr; }
    #row-top { height: 30%; min-height: 9; }
    #row-low { height: 30%; min-height: 9; }

    Panel { border: round #6b7a90; border-title-color: $foreground; border-title-style: bold;
            border-subtitle-color: #6b7a90; border-title-align: left; border-subtitle-align: right;
            padding: 0 1; background: $background; }
    Panel:focus-within { border: round $primary; border-title-color: $primary; border-subtitle-color: $primary; }
    #p-graph { width: 3fr; } #p-meters { width: 2fr; }
    #p-runs { width: 5fr; } #p-detail { width: 2fr; }
    #p-sessions { width: 1fr; } #p-history { width: 1fr; }
    #p-graph > Horizontal { height: 1fr; }
    #graph { width: 1fr; height: 1fr; }
    #legend { width: 24; height: 1fr; padding: 0 0 0 2; }
    #meters, #detail { height: 1fr; }

    Screen.-expanded .row { display: none; }
    Screen.-expanded .row.-has-target { display: block; height: 1fr !important; }
    Screen.-expanded Panel { display: none; }
    Screen.-expanded Panel.-target { display: block; width: 1fr; }

    DataTable { height: 1fr; background: transparent; overflow-x: hidden; }
    DataTable > .datatable--header { background: transparent; color: $primary; text-style: bold; }
    DataTable > .datatable--cursor { background: #274b6d; color: $foreground; text-style: bold; }
    DataTable > .datatable--hover { background: #1f3550; }
    Tree { background: transparent; height: 1fr; overflow-x: hidden; }
    * { scrollbar-size-vertical: 1; scrollbar-background: transparent; scrollbar-background-hover: transparent;
        scrollbar-background-active: transparent; scrollbar-color: #33435a; scrollbar-color-hover: #4d6080;
        scrollbar-color-active: #6cc4ff; }
    Tree > .tree--cursor { background: #274b6d; color: $foreground; text-style: bold; }
    Tree:focus > .tree--cursor { background: #274b6d; }
    #history-scroll { height: 1fr; }

    #filter { display: none; height: 3; border: round $primary; background: transparent; }
    #filter.-open { display: block; }
    #sessions-info { height: 1; color: $text-muted; }

    ConfirmScreen, HelpScreen, SortScreen { align: center middle; background: $background 60%; }
    ConfirmScreen #dialog { width: 80%; max-width: 110; }
    #dialog { width: auto; min-width: 36; max-width: 92%; height: auto; max-height: 85%; padding: 1 2;
              border: round $primary; border-title-color: $primary; border-title-style: bold;
              border-subtitle-color: $primary; background: $background; }
    #sort-list { width: 22; height: auto; background: transparent; border: none; padding: 0; }
    #sort-list > .option-list--option-highlighted { background: #274b6d; color: $foreground; text-style: bold; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("j", "cursor(1)", "Down", show=False),
        Binding("k", "cursor(-1)", "Up", show=False),
        Binding("e", "expand", "Expand"),
        Binding("x,f9", "kill", "Kill"),
        Binding("space", "mark", "Mark"),
        Binding("A", "mark_stale", "Mark stale"),
        Binding("s", "sort", "Sort"),
        Binding("i", "invert", "Reverse"),
        Binding("slash", "filter", "Filter"),
        Binding("a", "archive", "Archive"),
        Binding("w", "window", "Window"),
        Binding("h", "span", "Span"),
        Binding("p,f", "pause", "Freeze"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("plus,equals_sign", "faster", "+", show=False),
        Binding("minus", "slower", "-", show=False),
        Binding("1", "focus_panel('runs')", "Runs", show=False),
        Binding("2", "focus_panel('sessions')", "Sessions", show=False),
        Binding("3", "focus_panel('history')", "History", show=False),
        Binding("4", "focus_panel('graph')", "Graph", show=False),
    ]

    def __init__(
        self,
        *,
        interval: float = 2.0,
        stale_min: float = ui.STALE_IDLE_MIN,
        snapshot_fn: SnapshotFn = take_snapshot,
        sessions_fn: SessionsFn = sess.list_sessions,
        archive_fn: ArchiveFn = sess.archive,
        kill_fn: KillFn = kill_stack,
        load_history_fn: LoadHistoryFn | None = None,
        log_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.interval = interval
        self.stale_min = stale_min
        self._snapshot_fn = snapshot_fn
        self._sessions_fn = sessions_fn
        self._archive_fn = archive_fn
        self._kill_fn = kill_fn
        self._log_path = log_path or hist.default_log()
        self._load_history_fn: LoadHistoryFn = load_history_fn or self._read_log
        self.snap: Snapshot | None = None
        self.paused = False
        self.sort_key = model.DEFAULT_SORT
        self.descending: bool = True
        self.filter_text = ""
        self.marked: set[int] = set()
        self.shown: list[Stack] = []
        self.ring: model.Ring[model.Point] = model.Ring(max(30, int(GRAPH_SECONDS / interval)))
        self.span_label = "6h"
        self.window_hours = 6
        self.sessions_loaded_at = 0.0
        self.expanded: str | None = None
        self._sessions_cache: list[sess.Session] | None = None
        self._timer = None
        self._snapshot_busy = False
        self._killing = False

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        with Horizontal(id="row-top", classes="row"):
            with Panel(id="p-graph"), Horizontal():
                yield View(id="graph")
                yield Static(id="legend")
            with Panel(id="p-meters"):
                yield Static(id="meters")
        with Horizontal(id="row-mid", classes="row"):
            with Panel(id="p-runs"):
                yield DataTable(id="runs-table", cursor_type="row")
                yield Input(placeholder="runtime, agent, pid, helper ...  (Enter keeps, Esc clears)", id="filter")
            with Panel(id="p-detail"):
                yield Static(id="detail")
        with Horizontal(id="row-low", classes="row"):
            with Panel(id="p-sessions"):
                yield Static(id="sessions-info")
                yield Tree[sess.Session | None]("sessions", id="sessions-tree")
            with Panel(id="p-history"), VerticalScroll(id="history-scroll"):
                yield Static(id="history-body")

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = THEME.name
        titles = {
            "p-graph": "Gateway memory",
            "p-meters": "Memory",
            "p-runs": "Runs",
            "p-detail": "Process tree",
            "p-sessions": "Sessions",
            "p-history": "History",
        }
        for pid, title in titles.items():
            panel = self._find(f"#{pid}")
            panel.border_title = title
            panel.border_subtitle = HINTS[pid]
        self._find("#filter").border_title = "Filter"
        self._tree().show_root = False
        self._build_columns()
        self._seed_ring()
        self.refresh_snapshot()
        self.load_sessions()
        self.load_history()
        self._timer = self.set_interval(self.interval, self._tick)
        self.set_interval(60, self._slow_tick)  # sessions and history change slowly; the sampler logs once a minute
        self._table().focus()

    def _read_log(self, span: float) -> list[hist.Sample]:
        return hist.load(self._log_path, span)

    def _seed_ring(self) -> None:
        """Start the live graph from the last few minutes of the sampler log, if there is one."""
        try:
            rows = self._load_history_fn(10 * 60)
        except Exception:
            return
        repeat = max(1, round(60 / self.interval))  # one log sample per minute -> keep the time axis even
        points = [
            model.Point(float(r["cg_mb"]), sum(float(s[2]) for s in r["stacks"]), float(r["infra_mb"])) for r in rows
        ]
        self.ring.extend_front([p for p in points for _ in range(repeat)])

    @overload
    def _find(self, selector: type[_W]) -> _W: ...
    @overload
    def _find(self, selector: str) -> Widget: ...
    @overload
    def _find(self, selector: str, expect_type: type[_W]) -> _W: ...
    def _find(self, selector: str | type[Widget], expect_type: type[Widget] | None = None) -> Widget:
        """Look a widget up on the *main* screen.

        ``App.query_one`` searches whichever screen is on top, so while the help or kill confirmation is
        open a refresh would not find ``#meters`` and the screen behind the dialog would go stale.
        """
        stack = self.screen_stack
        if not stack:  # the app is shutting down
            raise NoMatches(str(selector))
        main = stack[0]
        return main.query_one(selector, expect_type) if expect_type else main.query_one(selector)  # type: ignore[arg-type]

    def _table(self) -> DataTable[Text]:
        return cast("DataTable[Text]", self._find("#runs-table", DataTable))

    def _tree(self) -> Tree[sess.Session | None]:
        return cast("Tree[sess.Session | None]", self._find("#sessions-tree", Tree))

    # ------------------------------------------------------------------ data refresh

    @staticmethod
    def _if_screen_gone() -> contextlib.AbstractContextManager[None]:
        """A worker that finishes while the app is quitting finds its widgets already removed."""
        return contextlib.suppress(NoMatches)

    def _tick(self) -> None:
        if not self.paused:
            self.refresh_snapshot()

    def _slow_tick(self) -> None:
        if not self.paused:
            self.load_sessions()
            self.load_history()

    @work(group="snapshot")
    async def refresh_snapshot(self) -> None:
        # Not exclusive: a new tick must never cancel a snapshot that is still running, or a machine
        # slow enough to take longer than the interval (exactly when you open the screen) would never update.
        if self._snapshot_busy:
            return
        self._snapshot_busy = True
        try:
            snap = await asyncio.to_thread(self._snapshot_fn)
        except Exception as e:
            self.notify(f"snapshot failed: {e}", severity="error", timeout=4)
            return
        finally:
            self._snapshot_busy = False
        with self._if_screen_gone():
            self.apply_snapshot(snap)

    def apply_snapshot(self, snap: Snapshot) -> None:
        self.snap = snap
        self.ring.add(model.Point(snap.cg_mb, snap.stacks_mb, snap.infra_mb))
        self.marked &= {s.pid for s in snap.stacks}
        self._redraw()
        self._rebuild_table()
        self._update_titles()

    def _redraw(self) -> None:
        """Repaint the meters and the graph (they depend on the panel sizes as well as the data)."""
        snap = self.snap
        if snap is None:
            return
        with self._if_screen_gone():
            meters = self._find("#meters", Static)
            meters.update(model.meters(snap, width=meters.size.width or 44))
            raw_limit = (snap.cg_high or snap.cg_max) if snap.main_pid else None
            limit: float | None = raw_limit / MB if raw_limit else None
            graph = self._find("#graph", Static)
            span = min(float(GRAPH_SECONDS), len(self.ring.values()) * self.interval)
            graph.update(model.graph(self.ring.values(), graph.size.width or 60, graph.size.height or 8, limit, span))
            self._find("#legend", Static).update(model.legend(snap, limit))

    def on_resize(self) -> None:
        self.call_after_refresh(self._redraw)

    def _update_titles(self) -> None:
        snap = self.snap
        graph = Text("Gateway memory")
        if snap is not None:
            if snap.main_pid:
                graph.append(f"  pid {snap.main_pid} up {ui.dur(snap.main_age_s)}", style="dim")
            else:
                graph.append("  NOT RUNNING", style="bold red")
        if self.paused:
            graph.append("  FROZEN", style="bold yellow")
        self._find("#p-graph").border_title = graph
        total = len(snap.stacks) if snap else 0
        runs = Text(f"Runs ({len(self.shown)}" + (f"/{total}" if len(self.shown) != total else "") + ")")
        if self.filter_text:
            runs.append(f"  filter '{self.filter_text}'", style="bold cyan")
        if self.marked:
            runs.append(f"  {len(self.marked)} marked", style="bold cyan")
        self._find("#p-runs").border_title = runs
        self._find("#p-meters").border_title = Text.assemble("Memory", (f"  every {self.interval:g}s", "dim"))

    # ------------------------------------------------------------------ runs table

    def _build_columns(self) -> None:
        table = self._table()
        table.clear(columns=True)
        for key, label, width in COLUMNS:
            sort_key = model.COLUMN_SORT.get(key)
            arrow = ""
            if sort_key == self.sort_key:
                arrow = "\u25bc" if self.descending else "\u25b2"
            table.add_column(Text(label + arrow, justify="right" if key in _RIGHT else "left"), key=key, width=width)

    def _rebuild_table(self) -> None:
        table = self._table()
        snap = self.snap
        keep: int | None = None
        if table.row_count:
            keep = int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value or 0)
        stacks = model.filter_stacks(snap.stacks if snap else [], self.filter_text)
        self.shown = model.sort_stacks(stacks, self.sort_key, self.descending)
        table.clear()
        for s in self.shown:
            table.add_row(*model.stack_cells(s, self.stale_min, s.pid in self.marked), key=str(s.pid))
        if self.shown:
            idx = next((i for i, s in enumerate(self.shown) if s.pid == keep), 0)
            table.move_cursor(row=idx, animate=False)
        self._update_detail()

    def _highlighted(self) -> Stack | None:
        table = self._table()
        if not self.shown or not table.row_count:
            return None
        row = table.cursor_row
        return self.shown[row] if 0 <= row < len(self.shown) else None

    def _update_detail(self) -> None:
        detail = self._find("#detail", Static)
        panel = self._find("#p-detail")
        s = self._highlighted()
        if s is None:
            note = ui.no_stacks_note(self.snap) if self.snap and not self.snap.stacks else "no runs match the filter"
            panel.border_title = "Process tree"
            detail.update(Text(note, style="dim"))
            return
        panel.border_title = f"Process tree \u2014 {s.runtime} {s.pid} ({s.agent})"
        detail.update(model.stack_tree(s))

    @on(DataTable.RowHighlighted, "#runs-table")
    def _row_moved(self) -> None:
        self._update_detail()

    @on(DataTable.HeaderSelected, "#runs-table")
    def _header_clicked(self, event: DataTable.HeaderSelected) -> None:
        key = model.COLUMN_SORT.get(str(event.column_key.value))
        if key:
            self._set_sort(key, descending=None)

    def _set_sort(self, key: str, descending: bool | None) -> None:
        if descending is None:
            descending = (not self.descending) if key == self.sort_key else model.NATURAL_DESC[key]
        self.sort_key, self.descending = key, descending
        self._build_columns()
        self._rebuild_table()
        self._update_titles()

    # ------------------------------------------------------------------ focus, expand, help

    def _focus_panel(self) -> str | None:
        """The id of the panel that holds the focus, or None (a dialog is open, or nothing is focused)."""
        node: DOMNode | None = self.focused
        while node is not None:
            if isinstance(node, Panel):
                return node.id
            node = node.parent
        return None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        scope = _SCOPE.get(action)
        return True if scope is None else self._focus_panel() == scope

    def action_cursor(self, delta: int) -> None:
        """vim-style j/k: move the cursor of whatever list has focus."""
        move = getattr(self.focused, "action_cursor_down" if delta > 0 else "action_cursor_up", None)
        if move is not None:
            move()

    def action_focus_panel(self, name: str) -> None:
        widget = self._find(_JUMP[name])
        if self.expanded is None:
            widget.focus()
            return
        # Full-screen view: a hidden widget cannot take the focus, so show its panel first, then focus.
        panel = next((n for n in widget.ancestors if isinstance(n, Panel)), None)
        self._expand(panel.id if panel else None)
        self.call_after_refresh(widget.focus)

    def action_expand(self) -> None:
        self._expand(None if self.expanded else self._focus_panel())

    def _expand(self, panel_id: str | None) -> None:
        """Show only ``panel_id`` (full screen), or the whole dashboard again when it is None."""
        self.expanded = panel_id
        main = self.screen_stack[0]
        main.set_class(panel_id is not None, "-expanded")
        for panel in main.query(Panel):
            target = panel.id == panel_id
            panel.set_class(target, "-target")
            panel.border_subtitle = "Esc to go back" if target else HINTS.get(panel.id or "", "")
        for row in main.query(".row"):
            row.set_class(panel_id is not None and bool(row.query("Panel.-target")), "-has-target")
        self.call_after_refresh(self._redraw)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_pause(self) -> None:
        self.paused = not self.paused
        self._update_titles()
        self.notify("frozen" if self.paused else "resumed", timeout=1.5)

    def action_refresh_now(self) -> None:
        self.load_sessions()
        self.load_history()
        self.refresh_snapshot()

    def _set_interval(self, value: float) -> None:
        self.interval = min(30.0, max(0.5, value))
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self.interval, self._tick)
        self._update_titles()

    def action_faster(self) -> None:
        self._set_interval(self.interval / 2 if self.interval > 1 else self.interval - 0.25)

    def action_slower(self) -> None:
        self._set_interval(self.interval * 2 if self.interval >= 1 else self.interval + 0.25)

    def action_sort(self) -> None:
        def picked(key: str | None) -> None:
            if key:
                self._set_sort(key, descending=None)

        self.push_screen(SortScreen(self.sort_key, self.descending), picked)

    def action_invert(self) -> None:
        self._set_sort(self.sort_key, descending=not self.descending)

    def action_mark(self) -> None:
        s = self._highlighted()
        if s is None:
            return
        self.marked ^= {s.pid}
        self._rebuild_table()
        self._update_titles()
        table = self._table()
        if table.cursor_row < len(self.shown) - 1:
            table.move_cursor(row=table.cursor_row + 1, animate=False)

    def action_mark_stale(self) -> None:
        stale = {s.pid for s in self.shown if s.kind == "orphan" or s.is_idle_over(self.stale_min)}
        self.marked = stale if stale != self.marked else set()
        self._rebuild_table()
        self._update_titles()
        if not stale:
            self.notify("no stale or orphaned runs", timeout=2)

    def action_filter(self) -> None:
        box = self._find("#filter", Input)
        box.add_class("-open")
        box.value = self.filter_text
        box.focus()

    @on(Input.Changed, "#filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self._rebuild_table()
        self._update_titles()

    def _close_filter(self, clear: bool) -> None:
        box = self._find("#filter", Input)
        if clear:
            box.value = ""
            self.filter_text = ""
            self._rebuild_table()
            self._update_titles()
        if not self.filter_text:
            box.remove_class("-open")
        self._table().focus()

    @on(Input.Submitted, "#filter")
    def _filter_submitted(self) -> None:
        self._close_filter(clear=False)

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        if key != "escape":
            return
        if self._find("#filter", Input).has_focus:
            self._close_filter(clear=True)
        elif self.expanded is not None:
            self._expand(None)
        else:
            return
        getattr(event, "stop", lambda: None)()

    # ------------------------------------------------------------------ kill

    def action_kill(self) -> None:
        if self._killing:
            self.notify("a kill is already running", severity="warning", timeout=2)
            return
        targets = [s for s in self.shown if s.pid in self.marked] or ([h] if (h := self._highlighted()) else [])
        if not targets:
            self.notify("nothing to kill", severity="warning", timeout=2)
            return
        body = ui.stacks_table(targets, self.stale_min)
        title = f"Kill {len(targets)} run(s), freeing {ui.gib(sum(s.mb for s in targets))}?"

        def after(yes: bool | None) -> None:
            if yes:
                self._do_kill(targets)
            else:
                self.notify("cancelled", timeout=1.5)

        self.push_screen(ConfirmScreen(title, body), after)

    @work(group="kill")
    async def _do_kill(self, targets: list[Stack]) -> None:
        self._killing = True
        results: list[tuple[Stack, list[int]]] = []
        try:
            for s in targets:
                left = await asyncio.to_thread(self._kill_fn, s)
                results.append((s, left))
        finally:
            self._killing = False
        failed = [s for s, left in results if left]
        for s, _left in results:
            self.marked.discard(s.pid)
        if failed:
            self.notify(f"{len(failed)} run(s) survived: {', '.join(str(s.pid) for s in failed)}", severity="error")
        else:
            self.notify(f"killed {len(results)} run(s), {ui.gib(sum(s.mb for s, _ in results))} freed")
        self.refresh_snapshot()

    # ------------------------------------------------------------------ sessions

    @work(exclusive=True, group="sessions")
    async def load_sessions(self) -> None:
        info = self._find("#sessions-info", Static)
        if self._sessions_cache is None:
            info.update("loading sessions from openclaw ...")
        try:
            rows = await asyncio.to_thread(self._sessions_fn)
        except Exception as e:
            with self._if_screen_gone():
                info.update(Text(f"could not load sessions: {e}", style="red"))
            return
        self._sessions_cache = rows
        self.sessions_loaded_at = time.time()
        with self._if_screen_gone():
            self._fill_sessions()

    def _fill_sessions(self) -> None:
        rows = self._sessions_cache or []
        picked = sess.select(rows, recent_s=self.window_hours * 3600)
        roots = sess.build_tree(picked, rows)
        tree = self._tree()
        tree.clear()
        for agent in dict.fromkeys(r.session.agent for r in roots):
            group = tree.root.add(Text(agent, style="bold cyan"), expand=True)
            for r in (r for r in roots if r.session.agent == agent):
                self._add_node(group, r)
        window = f"open + done in {self.window_hours}h" if self.window_hours else "open only"
        self._find("#sessions-info", Static).update(f"{len(picked)} sessions \u00b7 {window}")
        self._find("#p-sessions").border_title = Text.assemble(
            "Sessions", (f"  loaded {time.strftime('%H:%M:%S')}", "dim")
        )

    def _add_node(self, parent: TreeNode[sess.Session | None], n: sess.Node) -> None:
        label = ui.node_text(n)
        node = parent.add(label, data=n.session, expand=True) if n.children else parent.add_leaf(label, data=n.session)
        for c in n.children:
            self._add_node(node, c)

    def action_window(self) -> None:
        i = model.WINDOWS.index(self.window_hours) if self.window_hours in model.WINDOWS else -1
        self.window_hours = model.WINDOWS[(i + 1) % len(model.WINDOWS)]
        if self._sessions_cache is not None:
            self._fill_sessions()

    def action_archive(self) -> None:
        node = self._tree().cursor_node
        session = node.data if node is not None else None
        if not isinstance(session, sess.Session):
            self.notify("highlight a session first", severity="warning", timeout=2)
            return
        if not session.is_open:
            self.notify(f"already {session.status}", timeout=2)
            return
        body = ui.sessions_table([session], titles=True)

        def after(yes: bool | None) -> None:
            if yes:
                self._do_archive(session)
            else:
                self.notify("cancelled", timeout=1.5)

        self.push_screen(ConfirmScreen(f"Archive this {session.kind} session?", body), after)

    @work(group="archive")
    async def _do_archive(self, session: sess.Session) -> None:
        try:
            results = await asyncio.to_thread(self._archive_fn, [session])
        except Exception as e:
            self.notify(f"archive failed: {e}", severity="error")
            return
        ok = all(r.get("ok") for r in results)
        self.notify("archived" if ok else f"archive failed: {results}", severity="information" if ok else "error")
        self.load_sessions()

    # ------------------------------------------------------------------ history

    @work(exclusive=True, group="history")
    async def load_history(self) -> None:
        span = dict(model.SPANS)[self.span_label]
        body = self._find("#history-body", Static)
        try:
            rows = await asyncio.to_thread(self._load_history_fn, span)
        except Exception as e:
            with self._if_screen_gone():
                body.update(Text(f"could not read history: {e}", style="red"))
            return
        with self._if_screen_gone():
            panel = self._find("#p-history")
            panel.border_title = Text.assemble("History", (f"  last {self.span_label}", "dim"))
            body.update(ui.history_body(rows, width=max(20, panel.size.width - 14)))

    def action_span(self) -> None:
        self.span_label = model.next_in([label for label, _ in model.SPANS], self.span_label)
        self.notify(f"history span {self.span_label}", timeout=1.5)
        self.load_history()


GRAPH_SECONDS = 600
_RIGHT = {"pid", "idle", "age", "ctx", "mem"}


def run(**kwargs: object) -> None:
    """Start the TUI (blocks until the user quits)."""
    ClawtopApp(**kwargs).run()  # type: ignore[arg-type]
