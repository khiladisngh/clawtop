"""The interactive TUI (``clawtop top``): htop/bottom-style live view of the gateway and its runs."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar, cast

from rich.console import RenderableType
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Static, TabbedContent, TabPane, Tree
from textual.widgets.tree import TreeNode

from clawtop import history as hist
from clawtop import sessions as sess
from clawtop import ui
from clawtop.procs import MB, Snapshot, Stack, kill_stack, take_snapshot
from clawtop.tui import model

SnapshotFn = Callable[[], Snapshot]
SessionsFn = Callable[[], list[sess.Session]]
ArchiveFn = Callable[[Sequence[sess.Session]], list[dict[str, object]]]
KillFn = Callable[[Stack], list[int]]
LoadHistoryFn = Callable[[float], list[hist.Sample]]

COLUMNS: tuple[tuple[str, str, int | None], ...] = (
    ("mark", " ", 1),
    ("pid", "PID", 6),
    ("runtime", "RUNTIME", 9),
    ("agent", "AGENT", 12),
    ("idle", "IDLE", 7),
    ("age", "AGE", 7),
    ("ctx", "CTX", 6),
    ("mem", "MEM", 7),
    ("parts", "PARTS", 24),
    ("flag", "", 8),
)

HELP = """\
[b]Runs[/b]
  up/down, j/k   move            space   mark / unmark the row
  x, F9          kill marked (or the highlighted) run
  A              mark every STALE / ORPHAN run
  s              next sort key   i   reverse   (or click a column header)
  /              filter          esc  clear the filter

[b]Sessions[/b]
  a              archive the highlighted session
  w              window of finished sessions to show: open only, 6h, 24h

[b]History[/b]
  h              change the time span

[b]Anywhere[/b]
  1 2 3          switch tab        r   refresh now      p   pause / resume
  + / -          refresh interval  ?   this help        q   quit
"""


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
            yield Static(self._title, id="dialog-title")
            yield Static(self._body, id="dialog-body")
            yield Static("[b]y[/b] confirm   [b]n[/b] cancel", id="dialog-keys")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,q,question_mark,enter", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("clawtop keys", id="dialog-title")
            yield Static(HELP, id="dialog-body")

    def action_close(self) -> None:
        self.dismiss(None)


class ClawtopApp(App[None]):
    """Live gateway memory, run stacks, sessions and history in one screen."""

    TITLE = "clawtop"
    CSS = """
    #titlebar { height: 1; background: $primary-darken-2; color: $text; padding: 0 1; }
    #top { height: 6; }
    TabbedContent { height: 1fr; }
    TabbedContent > ContentSwitcher { height: 1fr; }
    TabPane { height: 1fr; padding: 0; }
    #meters { width: 1fr; padding: 0 1; border: round $primary-darken-1; }
    #graphbox { width: 42%; border: round $primary-darken-1; padding: 0 1; }
    #graph { height: 1fr; width: 1fr; }
    #filter { display: none; height: 3; }
    #filter.-open { display: block; }
    #runs-table { height: 1fr; }
    #detail { height: 8; border: round $primary-darken-1; padding: 0 1; }
    #sessions-info { height: 1; color: $text-muted; padding: 0 1; }
    #sessions-tree { height: 1fr; }
    ConfirmScreen, HelpScreen { align: center middle; }
    #dialog { width: 78%; max-width: 110; height: auto; max-height: 80%; padding: 1 2;
              border: thick $primary; background: $surface; }
    #dialog-title { text-style: bold; padding-bottom: 1; }
    #dialog-keys { padding-top: 1; color: $text-muted; }
    DataTable > .datatable--header { text-style: bold; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("j", "cursor(1)", "Down", show=False),
        Binding("k", "cursor(-1)", "Up", show=False),
        Binding("x,f9", "kill", "Kill"),
        Binding("space", "mark", "Mark"),
        Binding("A", "mark_stale", "Mark stale"),
        Binding("s", "sort", "Sort"),
        Binding("i", "invert", "Reverse"),
        Binding("slash", "filter", "Filter"),
        Binding("a", "archive", "Archive"),
        Binding("w", "window", "Window"),
        Binding("h", "span", "Span"),
        Binding("p", "pause", "Pause"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("plus,equals_sign", "faster", "+", show=False),
        Binding("minus", "slower", "-", show=False),
        Binding("1", "tab('runs')", "Runs", show=False),
        Binding("2", "tab('sessions')", "Sessions", show=False),
        Binding("3", "tab('history')", "History", show=False),
    ]

    # Which tab each tab-specific action belongs to; the footer hides the others.
    _SCOPE: ClassVar[dict[str, str]] = {
        "kill": "runs", "mark": "runs", "mark_stale": "runs", "sort": "runs", "invert": "runs", "filter": "runs",
        "archive": "sessions", "window": "sessions",
        "span": "history",
    }  # fmt: skip

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
        self.descending = True
        self.filter_text = ""
        self.marked: set[int] = set()
        self.shown: list[Stack] = []
        self.ring = model.Ring(max(30, int(GRAPH_SECONDS / interval)))
        self.span_label = "6h"
        self.window_hours = 6
        self.sessions_loaded_at = 0.0
        self._sessions_cache: list[sess.Session] | None = None
        self._timer = None

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Static(id="titlebar")
        with Horizontal(id="top"):
            yield Static(id="meters")
            with Vertical(id="graphbox"):
                yield Static(id="graph")
        with TabbedContent(id="tabs", initial="runs"):
            with TabPane("Runs", id="runs"):
                yield Input(
                    placeholder="filter: runtime, agent, pid, helper ...  (enter to keep, esc to clear)", id="filter"
                )
                yield DataTable(id="runs-table", cursor_type="row", zebra_stripes=True)
                yield Static(id="detail")
            with TabPane("Sessions", id="sessions"):
                yield Static(id="sessions-info")
                yield Tree[sess.Session | None]("sessions", id="sessions-tree")
            with TabPane("History", id="history"), VerticalScroll(id="history-scroll"):
                yield Static(id="history-body")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#meters").border_title = "memory"
        self.query_one("#graphbox").border_title = "gateway memory, last 10 min"
        self.query_one("#detail").border_title = "process tree"
        self._tree().show_root = False
        self._build_columns()
        self._seed_ring()
        self.refresh_snapshot()
        self._timer = self.set_interval(self.interval, self._tick)
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
        self.ring.extend_front([float(r["cg_mb"]) for r in rows for _ in range(repeat)])

    def _table(self) -> DataTable[Text]:
        return cast("DataTable[Text]", self.query_one("#runs-table", DataTable))

    def _tree(self) -> Tree[sess.Session | None]:
        return cast("Tree[sess.Session | None]", self.query_one("#sessions-tree", Tree))

    # ------------------------------------------------------------------ data refresh

    def _tick(self) -> None:
        if not self.paused:
            self.refresh_snapshot()

    @work(exclusive=True, group="snapshot")
    async def refresh_snapshot(self) -> None:
        try:
            snap = await asyncio.to_thread(self._snapshot_fn)
        except Exception as e:
            self.notify(f"snapshot failed: {e}", severity="error", timeout=4)
            return
        self.apply_snapshot(snap)

    def apply_snapshot(self, snap: Snapshot) -> None:
        self.snap = snap
        self.ring.add(snap.cg_mb)
        self.marked &= {s.pid for s in snap.stacks}
        self.query_one("#meters", Static).update(model.meters(snap))
        self._draw_graph()
        self._rebuild_table()
        self._update_titlebar()

    def _draw_graph(self) -> None:
        snap = self.snap
        graph = self.query_one("#graph", Static)
        raw_limit = (snap.cg_high or snap.cg_max) if snap else None
        limit: float | None = raw_limit / MB if raw_limit else None
        width = graph.size.width or 40
        height = graph.size.height or 4
        graph.update(model.graph(self.ring.values(), width, height, limit))
        box = self.query_one("#graphbox")
        if snap and snap.main_pid:
            box.border_subtitle = f"now {ui.gib(snap.cg_mb)}" + (f" \u00b7 limit {ui.gib(limit)}" if limit else "")

    def on_resize(self) -> None:
        if self.snap is not None:
            self._draw_graph()

    def _update_titlebar(self) -> None:
        snap = self.snap
        t = Text()
        t.append(" clawtop ", style="bold")
        if snap is not None:
            if snap.main_pid:
                t.append(f"gateway {snap.main_pid} up {ui.dur(snap.main_age_s)}")
            else:
                t.append("gateway NOT RUNNING", style="bold red")
            t.append(f"   runs {len(snap.stacks)}  {ui.gib(snap.stacks_mb)}")
        t.append(f"   every {self.interval:g}s")
        if self.paused:
            t.append("  PAUSED", style="bold yellow")
        arrow = "\u25bc" if self.descending else "\u25b2"
        t.append(f"   sort {self.sort_key}{arrow}")
        if self.filter_text:
            t.append(f"   filter '{self.filter_text}'", style="bold cyan")
        if self.marked:
            t.append(f"   {len(self.marked)} marked", style="bold cyan")
        self.query_one("#titlebar", Static).update(t)

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
        detail = self.query_one("#detail", Static)
        s = self._highlighted()
        if s is None:
            note = ui.no_stacks_note(self.snap) if self.snap and not self.snap.stacks else "no runs match the filter"
            detail.update(Text(note, style="dim"))
            return
        detail.border_title = f"process tree \u2014 {s.runtime} {s.pid} ({s.agent})"
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
        self._update_titlebar()

    # ------------------------------------------------------------------ actions

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        scope = self._SCOPE.get(action)
        if scope is None:
            return True
        try:
            return self.query_one(TabbedContent).active == scope
        except Exception:
            return True

    def action_cursor(self, delta: int) -> None:
        """vim-style j/k: move the cursor of whatever list has focus."""
        move = getattr(self.focused, "action_cursor_down" if delta > 0 else "action_cursor_up", None)
        if move is not None:
            move()

    def action_tab(self, name: str) -> None:
        self.query_one(TabbedContent).active = name

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        self.refresh_bindings()
        tab = event.pane.id
        if tab == "sessions":
            self._tree().focus()  # so the arrow keys work straight away
            self.load_sessions()
        elif tab == "history":
            self.query_one("#history-scroll", VerticalScroll).focus()
            self.load_history()
        else:
            self._table().focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_pause(self) -> None:
        self.paused = not self.paused
        self._update_titlebar()
        self.notify("paused" if self.paused else "resumed", timeout=1.5)

    def action_refresh_now(self) -> None:
        active = self.query_one(TabbedContent).active
        if active == "sessions":
            self.load_sessions()
        elif active == "history":
            self.load_history()
        self.refresh_snapshot()

    def _set_interval(self, value: float) -> None:
        self.interval = min(30.0, max(0.5, value))
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self.interval, self._tick)
        self._update_titlebar()

    def action_faster(self) -> None:
        self._set_interval(self.interval / 2 if self.interval > 1 else self.interval - 0.25)

    def action_slower(self) -> None:
        self._set_interval(self.interval * 2 if self.interval >= 1 else self.interval + 0.25)

    def action_sort(self) -> None:
        self._set_sort(model.next_in(model.SORT_KEYS, self.sort_key), descending=None)

    def action_invert(self) -> None:
        self._set_sort(self.sort_key, descending=not self.descending)

    def action_mark(self) -> None:
        s = self._highlighted()
        if s is None:
            return
        self.marked ^= {s.pid}
        self._rebuild_table()
        self._update_titlebar()
        table = self._table()
        if table.cursor_row < len(self.shown) - 1:
            table.move_cursor(row=table.cursor_row + 1, animate=False)

    def action_mark_stale(self) -> None:
        stale = {s.pid for s in self.shown if s.kind == "orphan" or s.is_idle_over(self.stale_min)}
        self.marked = stale if stale != self.marked else set()
        self._rebuild_table()
        self._update_titlebar()
        if not stale:
            self.notify("no stale or orphaned runs", timeout=2)

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("-open")
        box.value = self.filter_text
        box.focus()

    @on(Input.Changed, "#filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self._rebuild_table()
        self._update_titlebar()

    def _close_filter(self, clear: bool) -> None:
        box = self.query_one("#filter", Input)
        if clear:
            box.value = ""
            self.filter_text = ""
            self._rebuild_table()
            self._update_titlebar()
        if not self.filter_text:
            box.remove_class("-open")
        self._table().focus()

    @on(Input.Submitted, "#filter")
    def _filter_submitted(self) -> None:
        self._close_filter(clear=False)

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        if key == "escape" and self.query_one("#filter", Input).has_focus:
            self._close_filter(clear=True)
            getattr(event, "stop", lambda: None)()

    # ------------------------------------------------------------------ kill

    def action_kill(self) -> None:
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

    @work(exclusive=True, group="kill")
    async def _do_kill(self, targets: list[Stack]) -> None:
        results: list[tuple[Stack, list[int]]] = []
        for s in targets:
            left = await asyncio.to_thread(self._kill_fn, s)
            results.append((s, left))
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
        info = self.query_one("#sessions-info", Static)
        info.update("loading sessions from openclaw ...")
        try:
            rows = await asyncio.to_thread(self._sessions_fn)
        except Exception as e:
            info.update(Text(f"could not load sessions: {e}", style="red"))
            return
        self._sessions_cache = rows
        self.sessions_loaded_at = time.time()
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
        window = f"open + finished in the last {self.window_hours}h" if self.window_hours else "open only"
        self.query_one("#sessions-info", Static).update(
            f"{len(picked)} sessions ({window})  \u00b7  loaded {time.strftime('%H:%M:%S')}  \u00b7  r reload"
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

    @work(exclusive=True, group="archive")
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
        body = self.query_one("#history-body", Static)
        try:
            rows = await asyncio.to_thread(self._load_history_fn, span)
        except Exception as e:
            body.update(Text(f"could not read history: {e}", style="red"))
            return
        body.update(ui.history(rows, width=max(20, self.size.width - 22)))

    def action_span(self) -> None:
        self.span_label = model.next_in([label for label, _ in model.SPANS], self.span_label)
        self.notify(f"history span {self.span_label}", timeout=1.5)
        self.load_history()


GRAPH_SECONDS = 600
_RIGHT = {"pid", "idle", "age", "ctx", "mem"}


def run(**kwargs: object) -> None:
    """Start the TUI (blocks until the user quits)."""
    ClawtopApp(**kwargs).run()  # type: ignore[arg-type]
