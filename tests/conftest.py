from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from clawtop.procs import Proc, Snapshot, Stack

collect_ignore_glob = ["test_procs.py"] if sys.platform == "win32" else []  # needs real /proc, getuid

UUID_A = "11111111-2222-3333-4444-555555555555"
UUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def make_proc(
    root: Path,
    pid: int,
    ppid: int,
    cmd: str,
    *,
    cwd: str = "",
    pss_kb: int = 1024,
    start_ticks: int = 0,
    comm: str = "node",
    state: str = "S",
    environ: str = "",
) -> None:
    """Write a minimal /proc/<pid> entry that read_procs() can parse."""
    d = root / str(pid)
    d.mkdir(parents=True)
    # fields after ")": state ppid <17 filler> starttime (index 19)
    (d / "stat").write_text(f"{pid} ({comm}) {state} {ppid} " + " ".join(["0"] * 17) + f" {start_ticks} 0 0\n")
    (d / "cmdline").write_text(cmd.replace(" ", "\0") + "\0")
    (d / "smaps_rollup").write_text(f"Rss: {pss_kb} kB\nPss: {pss_kb} kB\n")
    if cwd:
        os.symlink(cwd, d / "cwd")
    if environ:
        (d / "environ").write_bytes(environ.replace(" ", "\0").encode() + b"\0")


def proc(pid: int, ppid: int, cmd: str, cwd: str = "", mb: float = 100, age_s: float = 60) -> Proc:
    return Proc(pid=pid, ppid=ppid, age_s=age_s, cmd=cmd, cwd=cwd, mb=mb)


def stack(
    pid: int,
    *,
    mb: float = 500,
    age_s: float = 60,
    idle_s: float | None = None,
    kind: str = "run",
    cmd: str | None = None,
    agent: str = "builder",
) -> Stack:
    from clawtop.procs import Transcript

    leader = proc(pid, 1, cmd or f"claude --session-id {UUID_A}", f"/srv/ws/{agent}", mb, age_s)
    s = Stack(kind=kind, leader=leader, procs=[leader], agent=agent)
    if idle_s is not None:
        s.transcript = Transcript(size_mb=1.0, idle_s=idle_s)
    return s


def snapshot(stacks: list[Stack]) -> Snapshot:
    return Snapshot(
        ts=1_700_000_000, main_pid=100, main_mb=2000, main_age_s=600, cg_mb=4000, cg_cache_mb=900, cg_high=11 << 30,
        cg_max=13 << 30, vm_total_mb=16000, vm_avail_mb=12000, swap_used_mb=0, psi=0.0, infra_mb=200,
        stacks=stacks,
    )  # fmt: skip


@pytest.fixture
def fake_proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    (root / "uptime").write_text("1000.00 0.00\n")
    return root
