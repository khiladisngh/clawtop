from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from clawtop.procs import Stack, build_stacks, find_transcript, kill_stack, read_procs

from .conftest import UUID_A, make_proc, proc, stack

HZ = os.sysconf("SC_CLK_TCK")
WS = "/opt/openclaw/workspaces/maya"


def test_read_procs_survives_awkward_comm_and_computes_age(fake_proc: Path) -> None:
    # comm may contain spaces and ')' - a naive split() shifts every later field
    make_proc(fake_proc, 42, 7, "claude --session-id x", cwd=WS, pss_kb=2048, start_ticks=400 * HZ,
              comm="a b) c")  # fmt: skip
    p = read_procs(fake_proc)[42]
    assert (p.ppid, p.cwd, p.mb) == (7, WS, 2.0)
    assert p.age_s == 1000 - 400  # uptime minus start time
    assert p.cmd == "claude --session-id x"


def test_stack_groups_children_sums_mem_and_ignores_infra() -> None:
    procs = {
        p.pid: p
        for p in [
            proc(100, 1, "node gateway"),
            proc(200, 100, f"/home/openclaw/.local/bin/claude --session-id {UUID_A}", WS, mb=250),
            proc(201, 200, "node /x/bin/rea mcp", mb=250),
            proc(202, 200, "npm exec @notionhq/notion-mcp-server", mb=80),
            proc(203, 202, "node .bin/notion-mcp-server", mb=60),
            proc(300, 100, "node dist/process/spawn-broker/worker.js", mb=50),
        ]
    }
    stacks, infra = build_stacks(procs, members=set(procs), main=100)
    assert len(stacks) == 1
    s = stacks[0]
    assert (s.kind, s.agent, s.session_id) == ("run", "maya", UUID_A)
    assert {p.pid for p in s.procs} == {200, 201, 202, 203}
    assert s.mb == 640
    assert s.parts == ["notion", "rea"]
    assert [p.pid for p in infra] == [300]


def test_users_own_claude_is_never_a_stack_but_leftover_gateway_run_is_an_orphan() -> None:
    procs = {
        p.pid: p
        for p in [
            proc(100, 1, "node gateway"),
            proc(500, 1, "claude --resume mine", "/home/openclaw/personal"),  # not gateway-signed
            proc(501, 1, "npm exec something-else", "/home/openclaw/personal"),
            proc(600, 1, "claude --strict-mcp-config --mcp-config /tmp/openclaw-cli-mcp-abc/mcp.json"),
            proc(601, 600, "node x/rea mcp"),
        ]
    }
    stacks, _ = build_stacks(procs, members={100}, main=100)
    assert [(s.pid, s.kind) for s in stacks] == [(600, "orphan")]
    assert {p.pid for p in stacks[0].procs} == {600, 601}


def test_transcript_gives_real_idle_time_and_context_size(tmp_path: Path) -> None:
    s = stack(7)
    d = tmp_path / ".claude" / "projects" / "-opt-openclaw-workspaces-forge"
    d.mkdir(parents=True)
    f = d / f"{UUID_A}.jsonl"
    f.write_bytes(b"x" * (3 << 20))
    os.utime(f, (time.time() - 600, time.time() - 600))
    t = find_transcript(s, home=tmp_path)
    assert t is not None
    assert round(t.size_mb) == 3
    assert 590 < t.idle_s < 620
    s.transcript = t
    assert s.idle_s == t.idle_s
    assert find_transcript(stack(7, age_s=5), home=tmp_path / "nowhere") is None


def test_stack_without_transcript_falls_back_to_process_age() -> None:
    assert stack(7, age_s=1234).idle_s == 1234


def _alive_stack(fake_proc: Path) -> Stack:
    make_proc(fake_proc, 10, 1, "claude --session-id x", cwd=WS)
    make_proc(fake_proc, 11, 10, "node rea mcp")
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
