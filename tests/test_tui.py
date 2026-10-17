from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from textual.pilot import Pilot
from textual.widgets import DataTable, Static, TabbedContent

from clawtop import history as hist
from clawtop import sessions as sess
from clawtop.procs import Snapshot, Stack
from clawtop.tui.app import ClawtopApp, ConfirmScreen, HelpScreen

from .conftest import snapshot, stack


def drive(app: ClawtopApp, script: Callable[[ClawtopApp, Pilot[None]], Awaitable[None]]) -> None:
    """Run ``script`` against the app in a headless terminal."""

    async def go() -> None:
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            await script(app, pilot)

    asyncio.run(go())


async def settle(app: ClawtopApp, pilot: Pilot[None]) -> None:
    await pilot.pause(0.1)
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


def make_app(
    stacks: list[Stack], *, killed: list[int] | None = None, survivors: bool = False, **kwargs: object
) -> ClawtopApp:
    snap = snapshot(stacks)

    def kill(s: Stack) -> list[int]:
        if killed is not None:
            killed.append(s.pid)
        return [s.pid] if survivors else []

    return ClawtopApp(
        interval=30,
        snapshot_fn=lambda: snap,
        kill_fn=kill,
        log_path=Path("nowhere.jsonl"),
        load_history_fn=lambda _span: [],
        **kwargs,  # type: ignore[arg-type]
    )


def three() -> list[Stack]:
    return [
        stack(10, mb=300, idle_s=60),
        stack(20, mb=700, idle_s=3 * 3600),  # stale
        stack(30, mb=500, cmd="gemini --yolo", agent="writer"),  # unknown idle
    ]


def test_runs_are_listed_biggest_first_and_the_first_is_highlighted() -> None:
    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        assert [s.pid for s in app.shown] == [20, 30, 10]
        assert app.query_one("#runs-table", DataTable).row_count == 3
        assert app._highlighted() is app.shown[0]  # pyright: ignore[reportPrivateUsage]

    drive(make_app(three()), script)


def test_sort_key_cycles_and_reverses_and_filter_narrows_then_clears() -> None:
    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("s")  # mem -> idle: known idle first (longest), unknown last
        assert app.sort_key == "idle" and [s.pid for s in app.shown] == [20, 10, 30]
        await pilot.press("i")
        assert [s.pid for s in app.shown] == [10, 20, 30]
        await pilot.press("slash")
        await pilot.press(*"gemini")
        assert [s.pid for s in app.shown] == [30]
        await pilot.press("escape")
        assert app.filter_text == "" and len(app.shown) == 3

    drive(make_app(three()), script)


def test_marking_two_runs_and_confirming_kills_exactly_those() -> None:
    killed: list[int] = []

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("space", "space")  # marks the first row, moves down, marks the second
        assert app.marked == {20, 30}
        await pilot.press("x")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await settle(app, pilot)
        assert sorted(killed) == [20, 30]
        assert app.marked == set()

    drive(make_app(three(), killed=killed), script)


def test_declining_the_confirmation_kills_nothing() -> None:
    killed: list[int] = []

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("x")
        await pilot.press("n")
        await settle(app, pilot)
        assert killed == []
        assert not isinstance(app.screen, ConfirmScreen)

    drive(make_app(three(), killed=killed), script)


def test_with_nothing_marked_x_kills_the_highlighted_run_only() -> None:
    killed: list[int] = []

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("down")  # second row (pid 30)
        await pilot.press("x", "y")
        await settle(app, pilot)
        assert killed == [30]

    drive(make_app(three(), killed=killed), script)


def test_mark_stale_selects_stale_and_orphans_but_not_unknown_idle() -> None:
    runs = [*three(), stack(40, kind="orphan", idle_s=5)]

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("A")
        assert app.marked == {20, 40}
        await pilot.press("A")  # again: clears
        assert app.marked == set()

    drive(make_app(runs), script)


def test_survivors_are_reported_and_the_ui_keeps_running() -> None:
    killed: list[int] = []

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("x", "y")
        await settle(app, pilot)
        assert killed == [20]
        assert app.screen is app.screen_stack[0]  # back on the main screen, not crashed
        assert any("survived" in n.message for n in app._notifications)  # pyright: ignore[reportPrivateUsage]

    drive(make_app(three(), killed=killed, survivors=True), script)


def test_cursor_stays_on_the_same_run_when_a_refresh_reorders_the_table() -> None:
    calls = {"n": 0}

    def snap_fn() -> Snapshot:
        calls["n"] += 1
        sizes = (500, 400, 300) if calls["n"] == 1 else (200, 600, 400)  # after a refresh pid 3 is second
        return snapshot([stack(pid, mb=mb) for pid, mb in zip((1, 2, 3), sizes, strict=True)])

    app = ClawtopApp(interval=30, snapshot_fn=snap_fn, log_path=Path("x"), load_history_fn=lambda _s: [])

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "down")  # highlight pid 3, the last row
        assert app._highlighted().pid == 3  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
        await pilot.press("r")
        await settle(app, pilot)
        assert [s.pid for s in app.shown] == [2, 3, 1]
        assert app._highlighted().pid == 3  # followed the run, not the row number  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]

    drive(app, script)


def test_pause_stops_refreshing_and_resume_continues() -> None:
    calls = {"n": 0}

    def snap_fn() -> Snapshot:
        calls["n"] += 1
        return snapshot(three())

    app = ClawtopApp(interval=0.1, snapshot_fn=snap_fn, log_path=Path("x"), load_history_fn=lambda _s: [])

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("p")
        await settle(app, pilot)
        before = calls["n"]
        await pilot.pause(0.6)
        assert app.paused and calls["n"] == before
        await pilot.press("p")
        await pilot.pause(0.6)
        assert calls["n"] > before

    drive(app, script)


def test_interval_keys_change_the_refresh_rate_within_limits() -> None:
    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("minus")
        assert app.interval == 30  # already at the 30 s ceiling: slower is clamped
        await pilot.press("plus")
        assert app.interval == 15  # faster halves it
        for _ in range(8):
            await pilot.press("plus")
        assert app.interval == 0.5  # and never goes below the 0.5 s floor

    drive(make_app(three()), script)


def _sessions() -> list[sess.Session]:
    main = sess.Session("agent:builder:main", "builder", "main", "open", 20, 0)
    sub = sess.Session("agent:builder:subagent:x", "builder", "subagent", "open", 99, 0, "Refactor billing", main.key)
    done = sess.Session("agent:builder:subagent:y", "builder", "subagent", "done", 60, 0, "Old job", main.key)
    return [main, sub, done]


def test_sessions_tab_shows_subagents_under_their_parent_and_archives_after_confirmation() -> None:
    archived: list[str] = []

    def archive(items: Sequence[sess.Session]) -> list[dict[str, object]]:
        archived.extend(s.key for s in items)
        return [{"key": s.key, "ok": True} for s in items]

    app = make_app(three(), sessions_fn=_sessions, archive_fn=archive)

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("2")
        await settle(app, pilot)
        tree = app._tree()  # pyright: ignore[reportPrivateUsage]
        group = tree.root.children[0]
        assert str(group.label) == "builder"
        parent = group.children[0]
        assert [c.data.label for c in parent.children if c.data] == ["Refactor billing", "Old job"]
        sub = next(c for c in parent.children if c.data and c.data.key.endswith(":x"))
        tree.move_cursor(sub)
        await pilot.pause(0.1)
        await pilot.press("a")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await settle(app, pilot)
        assert archived == ["agent:builder:subagent:x"]

    drive(app, script)


def test_archiving_a_group_row_or_a_finished_session_does_nothing() -> None:
    archived: list[str] = []
    app = make_app(three(), sessions_fn=_sessions, archive_fn=lambda items: archived.extend(s.key for s in items) or [])

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("2")
        await settle(app, pilot)
        tree = app._tree()  # pyright: ignore[reportPrivateUsage]
        tree.move_cursor(tree.root.children[0])  # the agent row, not a session
        await pilot.press("a")
        assert not isinstance(app.screen, ConfirmScreen)
        done = next(c for c in tree.root.children[0].children[0].children if c.data and c.data.status == "done")
        tree.move_cursor(done)
        await pilot.pause(0.1)
        await pilot.press("a")
        assert not isinstance(app.screen, ConfirmScreen) and archived == []

    drive(app, script)


def test_history_tab_uses_the_chosen_span_and_survives_an_empty_log() -> None:
    spans: list[float] = []

    def load(span: float) -> list[hist.Sample]:
        spans.append(span)
        return []

    app = ClawtopApp(interval=30, snapshot_fn=lambda: snapshot(three()), log_path=Path("x"), load_history_fn=load)

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        spans.clear()
        await pilot.press("3")
        await settle(app, pilot)
        assert spans == [6 * 3600.0]  # default 6h
        await pilot.press("h")
        await settle(app, pilot)
        assert spans[-1] == 24 * 3600.0
        assert app.query_one(TabbedContent).active == "history"
        assert app.query_one("#history-body", Static) is not None

    drive(app, script)


def test_tab_specific_keys_are_hidden_on_other_tabs_and_help_opens_and_closes() -> None:
    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        assert app.check_action("kill", ()) is True and app.check_action("archive", ()) is False
        await pilot.press("2")
        await settle(app, pilot)
        assert app.check_action("kill", ()) is False and app.check_action("archive", ()) is True
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpScreen)

    drive(make_app(three(), sessions_fn=_sessions), script)


def test_a_failing_snapshot_is_reported_and_does_not_end_the_session() -> None:
    def boom() -> Snapshot:
        raise OSError("proc vanished")

    app = ClawtopApp(interval=30, snapshot_fn=boom, log_path=Path("x"), load_history_fn=lambda _s: [])

    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        assert app.snap is None
        assert any("proc vanished" in n.message for n in app._notifications)  # pyright: ignore[reportPrivateUsage]
        await pilot.press("question_mark")  # still responsive
        assert isinstance(app.screen, HelpScreen)

    drive(app, script)


def test_j_and_k_move_the_cursor_but_are_plain_text_inside_the_filter_box() -> None:
    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        first = app.shown[0].pid
        await pilot.press("j")
        assert app._highlighted().pid == app.shown[1].pid  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
        await pilot.press("k")
        assert app._highlighted().pid == first  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
        await pilot.press("slash")
        await pilot.press("j", "k")  # typed into the box, not interpreted as movement
        assert app.filter_text == "jk"

    drive(make_app(three()), script)


def test_arrow_keys_work_on_the_sessions_tab_without_clicking_first() -> None:
    async def script(app: ClawtopApp, pilot: Pilot[None]) -> None:
        await pilot.press("2")
        await settle(app, pilot)
        tree = app._tree()  # pyright: ignore[reportPrivateUsage]
        assert app.focused is tree
        start = tree.cursor_line
        await pilot.press("down")
        assert tree.cursor_line == start + 1
        await pilot.press("j")
        assert tree.cursor_line == start + 2  # j/k work here too

    drive(make_app(three(), sessions_fn=_sessions), script)
