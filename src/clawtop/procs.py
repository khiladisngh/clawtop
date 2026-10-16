"""Process discovery: the gateway cgroup, agent run stacks, and memory accounting.

A *run stack* is one ``claude`` CLI process the gateway spawned for an agent run, plus its
private MCP children (``rea mcp``, ``npm exec @notionhq/notion-mcp-server`` and its node
server). Sizes are PSS (shared pages split between processes), so stacks add up.

Everything here reads ``/proc`` (root injectable for tests) and is Linux-only.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path

MB = 1 << 20
DEFAULT_UNIT = "openclaw-gateway"
WORKSPACES = "/opt/openclaw/workspaces/"

_CLAUDE = re.compile(r"(^|/)claude(\s|$)")
_MCP = re.compile(r"rea mcp|notion-mcp-server|npm exec")
_SESSION = re.compile(r"--(?:session-id|resume)[ =]([0-9a-f-]{36})")
_ROLES = (("rea mcp", "rea"), ("notion-mcp", "notion"), ("npm exec", "npm"))


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    age_s: float
    cmd: str
    cwd: str
    mb: float

    @property
    def is_claude(self) -> bool:
        return bool(_CLAUDE.search(self.cmd))

    @property
    def role(self) -> str:
        if self.is_claude:
            return "claude"
        for needle, role in _ROLES:
            if needle in self.cmd:
                return role
        m = re.search(r"dist/([\w/.-]+?)(?:\.m?js)?(\s|$)", self.cmd)
        if m:
            return m.group(1).split("/")[-1][:18]
        return (self.cmd.split(" ")[0].rsplit("/", 1)[-1] or "?")[:18]

    @property
    def has_gateway_signature(self) -> bool:
        """True if this looks gateway-spawned, so a user's own ``claude``/``npx`` is never touched."""
        return (
            self.cwd.startswith(WORKSPACES)
            or "/tmp/openclaw-cli-mcp-" in self.cmd
            or "--plugin-dir /tmp/openclaw/" in self.cmd
        )


@dataclass(frozen=True)
class Transcript:
    """The claude CLI's own conversation log for a stack: a real activity and context signal."""

    size_mb: float
    idle_s: float


@dataclass
class Stack:
    kind: str  # "run" (child of the gateway) or "orphan" (gateway-signed, parent gone)
    leader: Proc
    procs: list[Proc]
    transcript: Transcript | None = None

    @property
    def pid(self) -> int:
        return self.leader.pid

    @property
    def mb(self) -> float:
        return sum(p.mb for p in self.procs)

    @property
    def age_s(self) -> float:
        return self.leader.age_s

    @property
    def idle_s(self) -> float:
        """Seconds since the run last wrote to its transcript (falls back to process age)."""
        return self.transcript.idle_s if self.transcript else self.age_s

    @property
    def agent(self) -> str:
        m = re.search(r"workspaces/([\w-]+)", self.leader.cwd)
        return m.group(1) if m else "?"

    @property
    def session_id(self) -> str:
        m = _SESSION.search(self.leader.cmd)
        return m.group(1) if m else ""

    @property
    def parts(self) -> list[str]:
        return sorted({p.role for p in self.procs if p.pid != self.leader.pid})


@dataclass
class Snapshot:
    ts: int
    main_pid: int
    main_mb: float
    main_age_s: float
    cg_mb: float
    cg_high: int | None
    cg_max: int | None
    vm_total_mb: float
    vm_avail_mb: float
    swap_used_mb: float
    psi: float
    infra_mb: float
    stacks: list[Stack] = field(default_factory=lambda: [])

    @property
    def stacks_mb(self) -> float:
        return sum(s.mb for s in self.stacks)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "stacks"}
        d["stacks"] = [
            {
                "pid": s.pid,
                "kind": s.kind,
                "agent": s.agent,
                "session_id": s.session_id,
                "mb": round(s.mb, 1),
                "age_s": round(s.age_s),
                "idle_s": round(s.idle_s),
                "transcript_mb": round(s.transcript.size_mb, 2) if s.transcript else None,
                "pids": [p.pid for p in s.procs],
                "parts": s.parts,
            }
            for s in self.stacks
        ]
        return d


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text()
    except OSError:
        return default


def read_procs(root: Path = Path("/proc"), uid: int | None = None) -> dict[int, Proc]:
    """Snapshot every process owned by ``uid`` (default: the current user)."""
    uid = os.getuid() if uid is None else uid
    hz = os.sysconf("SC_CLK_TCK")
    uptime = float(_read(root / "uptime", "0 0").split()[0])
    out: dict[int, Proc] = {}
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            stat = (entry / "stat").read_text()
            # comm is parenthesised and may itself contain spaces or ')': split after the last one.
            rest = stat[stat.rindex(")") + 2 :].split()
            rss = re.search(r"^Pss:\s+(\d+)", _read(entry / "smaps_rollup"), re.M) or re.search(
                r"VmRSS:\s+(\d+)", _read(entry / "status")
            )
            try:
                cwd = os.readlink(entry / "cwd")
            except OSError:
                cwd = ""
            pid = int(entry.name)
            out[pid] = Proc(
                pid=pid,
                ppid=int(rest[1]),
                age_s=uptime - int(rest[19]) / hz,
                cmd=(entry / "cmdline").read_text().replace("\0", " ").strip(),
                cwd=cwd,
                mb=int(rss.group(1)) * 1024 / MB if rss else 0.0,
            )
        except (OSError, ValueError, IndexError):
            continue  # raced with an exiting process
    return out


def build_stacks(procs: dict[int, Proc], members: set[int], main: int) -> tuple[list[Stack], list[Proc]]:
    """Group gateway-owned processes into run stacks; return (stacks, remaining infra procs)."""
    kids: dict[int, list[int]] = {}
    for p in procs.values():
        kids.setdefault(p.ppid, []).append(p.pid)

    def tree(root: int) -> list[Proc]:
        out: list[Proc] = []
        todo = [root]
        while todo:
            pid = todo.pop()
            out.append(procs[pid])
            todo += kids.get(pid, [])
        return out

    relevant = {
        pid
        for pid, p in procs.items()
        if pid != main and (pid in members or ((p.is_claude or _MCP.search(p.cmd)) and p.has_gateway_signature))
    }
    leaders = [pid for pid in relevant if procs[pid].ppid == main and procs[pid].is_claude]
    orphans = [
        pid for pid in relevant if procs[pid].ppid not in relevant and procs[pid].ppid != main and pid not in leaders
    ]
    stacks: list[Stack] = []
    seen: set[int] = set()
    for kind, roots in (("run", leaders), ("orphan", orphans)):
        for root in sorted(roots):
            if root in seen:
                continue
            members_ = tree(root)
            seen.update(p.pid for p in members_)
            stacks.append(Stack(kind=kind, leader=procs[root], procs=members_))
    infra = [procs[pid] for pid in relevant - seen]
    stacks.sort(key=lambda s: -s.mb)
    return stacks, infra


def find_transcript(stack: Stack, home: Path | None = None, now: float | None = None) -> Transcript | None:
    sid = stack.session_id
    if not sid or not stack.leader.cwd:
        return None
    slug = re.sub(r"[/.]", "-", stack.leader.cwd)
    path = (home or Path.home()) / ".claude" / "projects" / slug / f"{sid}.jsonl"
    try:
        st = path.stat()
    except OSError:
        return None
    return Transcript(size_mb=st.st_size / MB, idle_s=max(0.0, (now or time.time()) - st.st_mtime))


def _systemctl_pid(unit: str) -> int:
    env = {
        **os.environ,
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
    }
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        return int(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def take_snapshot(
    unit: str = DEFAULT_UNIT,
    root: Path = Path("/proc"),
    cgroot: Path = Path("/sys/fs/cgroup"),
    home: Path | None = None,
) -> Snapshot:
    main = _systemctl_pid(unit)
    cg: Path | None = None
    if main:
        for line in _read(root / str(main) / "cgroup").splitlines():
            if line.startswith("0::"):
                cg = cgroot / line[4:]
    members: set[int] = {int(x) for x in _read(cg / "cgroup.procs").split()} if cg else set()
    procs = read_procs(root)
    stacks, infra = build_stacks(procs, members, main)
    for s in stacks:
        s.transcript = find_transcript(s, home)

    meminfo = {ln.split(":")[0]: int(ln.split()[1]) for ln in _read(root / "meminfo").splitlines() if ln.strip()}
    psi = re.search(r"some avg10=([\d.]+)", _read(root / "pressure" / "memory"))

    def limit(name: str) -> int | None:
        v = _read(cg / name, "max").strip() if cg else "max"
        return None if v == "max" else int(v)

    return Snapshot(
        ts=int(time.time()),
        main_pid=main,
        main_mb=procs[main].mb if main in procs else 0.0,
        main_age_s=procs[main].age_s if main in procs else 0.0,
        cg_mb=int(_read(cg / "memory.current", "0")) / MB if cg else 0.0,
        cg_high=limit("memory.high"),
        cg_max=limit("memory.max"),
        vm_total_mb=meminfo.get("MemTotal", 0) / 1024,
        vm_avail_mb=meminfo.get("MemAvailable", 0) / 1024,
        swap_used_mb=(meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)) / 1024,
        psi=float(psi.group(1)) if psi else 0.0,
        infra_mb=sum(p.mb for p in infra),
        stacks=stacks,
    )


def _alive(pid: int, root: Path) -> bool:
    stat = _read(root / str(pid) / "stat")
    return bool(stat) and stat[stat.rindex(")") + 2 :].split()[0] != "Z"


def kill_stack(
    stack: Stack,
    *,
    grace_s: float = 5.0,
    root: Path = Path("/proc"),
    kill: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
) -> list[int]:
    """SIGTERM the whole stack, then SIGKILL survivors. Returns PIDs still alive.

    A PID is only signalled if its cmdline is unchanged since the snapshot, which guards
    against PID reuse between listing and killing.
    """

    def signal_all(sig: int) -> None:
        for p in stack.procs:
            now = _read(root / str(p.pid) / "cmdline").replace("\0", " ").strip()
            if now == p.cmd and _alive(p.pid, root):
                with contextlib.suppress(OSError):  # process exited between check and signal
                    kill(p.pid, sig)

    def survivors() -> list[int]:
        return [p.pid for p in stack.procs if _alive(p.pid, root)]

    signal_all(signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while survivors() and time.monotonic() < deadline:
        sleep(0.1)
    if survivors():
        signal_all(signal.SIGKILL)
        sleep(0.2)
    return survivors()
