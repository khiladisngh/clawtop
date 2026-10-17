from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from clawtop import cli
from clawtop import sessions as sess
from clawtop.procs import Stack

from .conftest import snapshot, stack

runner = CliRunner()


@pytest.fixture
def two_stacks(monkeypatch: pytest.MonkeyPatch) -> tuple[Stack, Stack]:
    fresh = stack(200, mb=300, idle_s=60)
    stale = stack(201, mb=700, idle_s=3 * 3600)
    monkeypatch.setattr(cli, "take_snapshot", lambda: snapshot([stale, fresh]))
    return fresh, stale


@pytest.fixture
def killed(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    pids: list[int] = []

    def fake_kill(s: Stack, **_: object) -> list[int]:
        pids.append(s.pid)
        return []

    monkeypatch.setattr(cli, "kill_stack", fake_kill)
    return pids


def test_status_json_exposes_stacks(two_stacks: object) -> None:
    r = runner.invoke(cli.app, ["status", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert [s["pid"] for s in data["stacks"]] == [201, 200]
    assert data["stacks"][0]["idle_s"] == 3 * 3600


def test_bare_command_shows_status_and_flags_stale_runs(two_stacks: object) -> None:
    r = runner.invoke(cli.app, [])
    assert r.exit_code == 0
    assert "STALE" in r.output and "clawtop kill --idle 30" in r.output


def test_kill_idle_selects_only_stale_and_respects_dry_run(two_stacks: object, killed: list[int]) -> None:
    r = runner.invoke(cli.app, ["kill", "--idle", "30", "--dry-run"])
    assert r.exit_code == 0 and "1 stack(s)" in r.output
    assert killed == []
    r = runner.invoke(cli.app, ["kill", "--idle", "30", "--yes"])
    assert r.exit_code == 0
    assert killed == [201]


def test_kill_refuses_pid_that_is_not_a_stack_leader(two_stacks: object, killed: list[int]) -> None:
    r = runner.invoke(cli.app, ["kill", "1", "--yes"])
    assert r.exit_code == 1 and "not an agent run-stack leader" in r.output
    assert killed == []


def test_kill_declined_confirmation_kills_nothing(two_stacks: object, killed: list[int]) -> None:
    r = runner.invoke(cli.app, ["kill", "200"], input="n\n")
    assert r.exit_code == 1
    assert killed == []


def test_kill_without_selector_needs_a_terminal(two_stacks: object, killed: list[int]) -> None:
    r = runner.invoke(cli.app, ["kill"])  # CliRunner stdin is not a tty
    assert r.exit_code == 1 and "not a terminal" in r.output
    assert killed == []


def test_kill_survivors_give_nonzero_exit(two_stacks: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "kill_stack", lambda s, **_: [s.pid])
    assert runner.invoke(cli.app, ["kill", "200", "-y"]).exit_code == 1


def test_sessions_prune_archives_only_idle_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        sess.Session("agent:builder:subagent:old", "builder", "subagent", "open", 10 * 3600, 0),
        sess.Session("agent:builder:subagent:new", "builder", "subagent", "open", 60, 0),
        sess.Session("agent:writer:discord:channel:1", "writer", "discord", "open", 50 * 3600, 0),
    ]
    monkeypatch.setattr(cli.sess, "list_sessions", lambda: rows)
    seen: list[list[str]] = []

    def fake_archive(items: list[sess.Session], dry_run: bool = False) -> list[dict[str, object]]:
        seen.append([s.key for s in items])
        return [{"key": s.key, "ok": True} for s in items]

    monkeypatch.setattr(cli.sess, "archive", fake_archive)
    r = runner.invoke(cli.app, ["sessions", "prune", "--idle-hours", "6", "--yes"])
    assert r.exit_code == 0
    assert seen == [["agent:builder:subagent:old"]]


def test_sessions_error_from_openclaw_is_a_clean_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> list[sess.Session]:
        raise sess.OpenClawError("gateway down")

    monkeypatch.setattr(cli.sess, "list_sessions", boom)
    r = runner.invoke(cli.app, ["sessions", "list"])
    assert r.exit_code == 1 and "gateway down" in r.output


def test_history_window_must_be_valid(tmp_path: object) -> None:
    r = runner.invoke(cli.app, ["history", "--last", "soon", "--log", "/nonexistent"])
    assert r.exit_code != 0
    r = runner.invoke(cli.app, ["history", "--last", "6h", "--log", "/nonexistent"])
    assert r.exit_code == 0 and "No samples" in r.output


def test_status_when_gateway_is_down_still_lists_leftover_orphans(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = snapshot([stack(300, kind="orphan")])
    snap.main_pid = 0
    monkeypatch.setattr(cli, "take_snapshot", lambda: snap)
    r = runner.invoke(cli.app, [])
    assert "NOT RUNNING" in r.output and "ORPHAN" in r.output


def test_sessions_tree_and_titles_show_the_label(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = sess.Session("agent:builder:main", "builder", "main", "open", 10, 0)
    kid = sess.Session("agent:builder:subagent:a", "builder", "subagent", "open", 5, 0, "rig survey", parent.key)
    monkeypatch.setattr(cli.sess, "list_sessions", lambda: [parent, kid])
    tree = runner.invoke(cli.app, ["sessions", "tree"])
    assert tree.exit_code == 0
    assert tree.output.index("main") < tree.output.index("rig survey")  # child listed under parent
    assert "rig survey" not in runner.invoke(cli.app, ["sessions", "list"]).output
    assert "rig survey" in runner.invoke(cli.app, ["sessions", "list", "--titles"]).output


def test_tree_shows_recently_finished_subagents_under_their_parent_but_not_old_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = sess.Session("agent:builder:main", "builder", "main", "open", 30, 0)
    fresh = sess.Session("agent:builder:subagent:a", "builder", "subagent", "done", 600, 0, "fresh job", main.key)
    old = sess.Session("agent:builder:subagent:b", "builder", "subagent", "done", 3 * 86400, 0, "ancient job", main.key)
    monkeypatch.setattr(cli.sess, "list_sessions", lambda: [main, fresh, old])
    r = runner.invoke(cli.app, ["sessions", "tree"])
    assert "fresh job" in r.output and "ancient job" not in r.output
    assert r.output.index("main") < r.output.index("fresh job")
    assert "fresh job" not in runner.invoke(cli.app, ["sessions", "tree", "--within", "0"]).output
    assert "ancient job" in runner.invoke(cli.app, ["sessions", "tree", "--all"]).output


def test_idle_selector_skips_runtimes_with_no_activity_source_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    claude = stack(200, mb=300, idle_s=3 * 3600)  # has a transcript: idle is known
    gemini = stack(201, mb=700, cmd="gemini --yolo", age_s=5 * 3600)  # no activity source: idle unknown
    monkeypatch.setattr(cli, "take_snapshot", lambda: snapshot([gemini, claude]))
    killed: list[int] = []
    monkeypatch.setattr(cli, "kill_stack", lambda s, **_: killed.append(s.pid) or [])

    r = runner.invoke(cli.app, ["kill", "--idle", "30", "--yes"])
    assert r.exit_code == 0 and killed == [200]  # never guessed from age
    assert "1 run(s) skipped by --idle" in r.output

    killed.clear()
    assert runner.invoke(cli.app, ["kill", "--older-than", "120", "--yes"]).exit_code == 0
    assert killed == [201]  # age works for every runtime


def test_status_shows_each_runtime_and_a_dash_where_idle_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = snapshot([stack(200, idle_s=60), stack(201, cmd="gemini --yolo")])
    monkeypatch.setattr(cli, "take_snapshot", lambda: snap)
    out = runner.invoke(cli.app, []).output
    assert "claude" in out and "gemini" in out
    assert "STALE" not in out  # an unknown idle time is not stale
    data = json.loads(runner.invoke(cli.app, ["status", "--json"]).output)
    assert {s["runtime"]: s["idle_s"] for s in data["stacks"]} == {"claude": 60, "gemini": None}


def test_empty_status_explains_embedded_runtimes_and_missing_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = snapshot([])
    monkeypatch.setattr(cli, "take_snapshot", lambda: snap)
    assert "run inside the gateway" in runner.invoke(cli.app, []).output
    snap.workspaces_known = False
    assert "CLAWTOP_WORKSPACES" in runner.invoke(cli.app, []).output


def test_top_refuses_to_run_without_a_terminal_and_points_at_status() -> None:
    r = runner.invoke(cli.app, ["top"])  # CliRunner's stdout is not a tty
    assert r.exit_code == 1
    assert "needs a terminal" in r.output and "clawtop status" in r.output


def test_the_old_watch_command_is_gone_in_favour_of_top() -> None:
    assert runner.invoke(cli.app, ["watch"]).exit_code == 2  # unknown command
    assert "top" in runner.invoke(cli.app, ["--help"]).output
