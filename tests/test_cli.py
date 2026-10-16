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
        sess.Session("agent:forge:subagent:old", "forge", "subagent", "open", 10 * 3600, 0),
        sess.Session("agent:forge:subagent:new", "forge", "subagent", "open", 60, 0),
        sess.Session("agent:maya:discord:channel:1", "maya", "discord", "open", 50 * 3600, 0),
    ]
    monkeypatch.setattr(cli.sess, "list_sessions", lambda: rows)
    seen: list[list[str]] = []

    def fake_archive(items: list[sess.Session], dry_run: bool = False) -> list[dict[str, object]]:
        seen.append([s.key for s in items])
        return [{"key": s.key, "ok": True} for s in items]

    monkeypatch.setattr(cli.sess, "archive", fake_archive)
    r = runner.invoke(cli.app, ["sessions", "prune", "--idle-hours", "6", "--yes"])
    assert r.exit_code == 0
    assert seen == [["agent:forge:subagent:old"]]


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
