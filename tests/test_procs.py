from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from clawtop.procs import (
    Stack,
    Workspaces,
    build_stacks,
    find_transcript,
    kill_stack,
    label_of,
    load_workspaces,
    read_procs,
    spawned_by_gateway,
)

from .conftest import UUID_A, make_proc, proc, stack

HZ = os.sysconf("SC_CLK_TCK")
WS = Workspaces({"maya": "/srv/ws/maya"}, ("/srv/ws",))
MARKER = "OPENCLAW_GATEWAY_SERVICE_PID=999"


def test_read_procs_survives_awkward_comm_and_computes_age(fake_proc: Path) -> None:
    # comm may contain spaces and ')' - a naive split() shifts every later field
    make_proc(fake_proc, 42, 7, "gemini --yolo", cwd="/srv/ws/maya", pss_kb=2048, start_ticks=400 * HZ, comm="a b) c")
    p = read_procs(fake_proc)[42]
    assert (p.ppid, p.cwd, p.mb) == (7, "/srv/ws/maya", 2.0)
    assert p.age_s == 1000 - 400  # uptime minus start time
    assert p.cmd == "gemini --yolo"


def test_labels_name_what_a_launcher_runs_not_the_launcher() -> None:
    assert label_of("/home/u/.local/bin/claude --strict-mcp-config") == "claude"
    assert label_of("/usr/bin/gemini --yolo") == "gemini"
    assert label_of("node /opt/tools/bin/some-mcp serve") == "some-mcp"
    assert label_of("npm exec @scope/pkg-server") == "pkg-server"
    assert label_of("npx -y @scope/pkg-server") == "pkg-server"
    assert label_of("sh -c 'my-server'") == "my-server"
    assert label_of("python3 -m http.server") == "http.server"
    assert label_of("uv tool run thing --x") == "thing"
    assert label_of("node") == "node"
    assert label_of("") == "?"


def test_workspaces_map_a_directory_to_its_agent() -> None:
    assert WS.agent_for("/srv/ws/maya") == "maya"
    assert WS.agent_for("/srv/ws/maya/sub/dir") == "maya"
    assert WS.agent_for("/srv/ws/other") == "other"  # not configured per agent: first dir under a root
    assert WS.agent_for("/srv/ws") is None
    assert WS.agent_for("/srv/ws-evil/x") is None  # a shared prefix is not a match
    assert WS.agent_for("/home/u") is None
    assert WS.agent_for("") is None


def test_load_workspaces_reads_the_openclaw_config(tmp_path: Path) -> None:
    (tmp_path / ".openclaw").mkdir()
    cfg = {
        "agents": {
            "defaults": {"workspace": "/data/ws"},
            "entries": {"atlas": {"workspace": "/data/special/atlas"}, "plain": {}},
        }
    }
    (tmp_path / ".openclaw" / "openclaw.json").write_text(json.dumps(cfg))
    ws = load_workspaces(env={}, home=tmp_path)
    assert ws.agents == {"atlas": "/data/special/atlas"}
    assert ws.roots == ("/data/ws",)
    assert ws.agent_for("/data/special/atlas/x") == "atlas"
    assert ws.agent_for("/data/ws/lumen") == "lumen"


def test_load_workspaces_honours_env_overrides_and_survives_json5_or_a_missing_file(tmp_path: Path) -> None:
    assert not load_workspaces(env={}, home=tmp_path)  # no config, nothing configured
    ws = load_workspaces(env={"CLAWTOP_WORKSPACES": "/a:/b"}, home=tmp_path)
    assert ws.roots == ("/a", "/b")

    custom = tmp_path / "elsewhere.json"
    custom.write_text("{ // comments make this JSON5\n  agents: { defaults: { workspace: '/five/ws' } },\n}")
    ws = load_workspaces(env={"OPENCLAW_CONFIG_PATH": str(custom)}, home=tmp_path)
    assert ws.roots == ("/five/ws",)

    state = tmp_path / "state"
    state.mkdir()
    (state / "openclaw.json").write_text(json.dumps({"agents": {"defaults": {"workspace": "/s/ws"}}}))
    assert load_workspaces(env={"OPENCLAW_STATE_DIR": str(state)}, home=tmp_path).roots == ("/s/ws",)


def test_a_stack_is_the_top_process_in_a_workspace_with_everything_it_spawned() -> None:
    procs = {
        p.pid: p
        for p in [
            proc(100, 1, "node --max-old-space-size=8192 /x/node_modules/openclaw/dist/index.js gateway"),
            proc(200, 100, "/usr/bin/gemini --yolo", "/srv/ws/maya", mb=250),
            proc(201, 200, "node /opt/tools/bin/some-mcp serve", "/srv/ws/maya", mb=250),
            proc(202, 200, "npm exec @scope/pkg-server", "/srv/ws/maya", mb=80),
            proc(203, 202, "sh -c 'pkg-server'", "/srv/ws/maya", mb=60),
            # the gateway's own worker, and an MCP server it runs for itself (home dir, not a workspace)
            proc(300, 100, "node /x/node_modules/openclaw/dist/process/worker.js", "/home/u", mb=50),
            proc(301, 300, "node /opt/tools/bin/shared-mcp serve", "/home/u", mb=120),
        ]
    }
    stacks, infra = build_stacks(procs, set(procs), main=100, workspaces=WS)
    assert len(stacks) == 1
    s = stacks[0]
    assert (s.kind, s.agent, s.runtime) == ("run", "maya", "gemini")
    assert {p.pid for p in s.procs} == {200, 201, 202, 203}
    assert s.mb == 640
    assert s.parts == ["pkg-server", "some-mcp"]
    assert {p.pid for p in infra} == {300, 301}  # shared MCP servers are gateway overhead, not a run


def test_two_different_runtimes_are_two_stacks_of_their_own() -> None:
    procs = {
        p.pid: p
        for p in [
            proc(100, 1, "node /x/node_modules/openclaw/dist/index.js gateway"),
            proc(200, 100, "/bin/claude --session-id " + UUID_A, "/srv/ws/a", mb=300),
            proc(210, 100, "/bin/codex-acp", "/srv/ws/b", mb=400),
        ]
    }
    stacks, _ = build_stacks(procs, set(procs), main=100, workspaces=WS)
    assert [(s.runtime, s.agent) for s in stacks] == [("codex-acp", "b"), ("claude", "a")]  # biggest first


def test_a_hand_started_cli_is_never_a_stack_but_a_leftover_gateway_run_is_an_orphan() -> None:
    procs = {
        p.pid: p
        for p in [
            proc(100, 1, "node /x/node_modules/openclaw/dist/index.js gateway"),
            proc(500, 1, "claude --resume mine", "/srv/ws/maya"),  # in a workspace, but no gateway marker
            proc(600, 1, "gemini", "/srv/ws/maya"),  # gateway marker: left behind by an earlier gateway
            proc(601, 600, "node some-mcp", "/srv/ws/maya"),
            proc(700, 1, "gemini", "/home/u/elsewhere"),  # marker, but not in an agent workspace
        ]
    }
    marked = {600, 601, 700}
    stacks, _ = build_stacks(procs, {100}, main=100, workspaces=WS, signed=lambda pid: pid in marked)
    assert [(s.pid, s.kind) for s in stacks] == [(600, "orphan")]
    assert {p.pid for p in stacks[0].procs} == {600, 601}


def test_gateway_marker_is_read_from_the_process_environment(fake_proc: Path) -> None:
    make_proc(fake_proc, 10, 1, "gemini", environ=f"HOME=/x {MARKER} PATH=/bin")
    make_proc(fake_proc, 11, 1, "gemini", environ="HOME=/x PATH=/bin")
    make_proc(fake_proc, 12, 1, "gemini")  # environ unreadable
    assert spawned_by_gateway(10, fake_proc)
    assert not spawned_by_gateway(11, fake_proc)
    assert not spawned_by_gateway(12, fake_proc)


def test_idle_time_comes_from_a_transcript_only_for_runtimes_that_have_one(tmp_path: Path) -> None:
    claude = stack(7)
    d = tmp_path / ".claude" / "projects" / "-srv-ws-builder"
    d.mkdir(parents=True)
    f = d / f"{UUID_A}.jsonl"
    f.write_bytes(b"x" * (3 << 20))
    os.utime(f, (time.time() - 600, time.time() - 600))
    t = find_transcript(claude, home=tmp_path)
    assert t is not None and round(t.size_mb) == 3 and 590 < t.idle_s < 620
    claude.transcript = t
    assert claude.idle_s == t.idle_s and claude.is_idle_over(5) and not claude.is_idle_over(30)

    gemini = stack(8, cmd=f"gemini --session-id {UUID_A}")  # same flags and path layout, other runtime
    assert find_transcript(gemini, home=tmp_path) is None
    assert gemini.idle_s is None and not gemini.is_idle_over(0)  # unknown is never "stale"
    assert find_transcript(stack(9), home=tmp_path / "nowhere") is None


def _alive_stack(fake_proc: Path) -> Stack:
    make_proc(fake_proc, 10, 1, "gemini", cwd="/srv/ws/maya")
    make_proc(fake_proc, 11, 10, "node some-mcp")
    make_proc(fake_proc, 12, 10, "node stubborn")
    procs = read_procs(fake_proc)
    return Stack(kind="run", leader=procs[10], procs=[procs[10], procs[11], procs[12]])


def test_kill_escalates_to_sigkill_only_for_survivors(fake_proc: Path) -> None:
    s = _alive_stack(fake_proc)
    sent: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        if sig == signal.SIGKILL or pid != 12:  # pid 12 ignores SIGTERM
            (fake_proc / str(pid) / "stat").unlink()

    left = kill_stack(s, grace_s=0, root=fake_proc, kill=fake_kill, sleep=lambda _: None)
    assert left == []
    assert [x for x in sent if x[1] == signal.SIGKILL] == [(12, signal.SIGKILL)]
    assert {pid for pid, sig in sent if sig == signal.SIGTERM} == {10, 11, 12}


def test_kill_skips_pid_that_was_reused_by_another_program(fake_proc: Path) -> None:
    s = _alive_stack(fake_proc)
    (fake_proc / "11" / "cmdline").write_text("vim\0notes.txt\0")  # pid 11 now belongs to someone else
    sent: list[int] = []
    kill_stack(s, grace_s=0, root=fake_proc, kill=lambda pid, _sig: sent.append(pid), sleep=lambda _: None)
    assert 11 not in sent
    assert {10, 12} <= set(sent)


def test_state_dir_follows_openclaw_env_then_home(tmp_path: Path) -> None:
    from clawtop.procs import config_path, state_dir

    assert state_dir({}, tmp_path) == tmp_path / ".openclaw"
    assert state_dir({"OPENCLAW_STATE_DIR": str(tmp_path / "profile")}, tmp_path) == tmp_path / "profile"
    assert config_path({"OPENCLAW_STATE_DIR": str(tmp_path / "p")}, tmp_path) == tmp_path / "p" / "openclaw.json"
    assert config_path({"OPENCLAW_CONFIG_PATH": "/x/c.json", "OPENCLAW_STATE_DIR": "/s"}, tmp_path) == Path("/x/c.json")
