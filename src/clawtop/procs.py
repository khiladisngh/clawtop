"""Process discovery: the gateway cgroup, agent run stacks, and memory accounting.

A *run stack* is one external process the gateway started to execute an agent run (a CLI backend
such as Claude CLI or Gemini CLI, or an ACP harness), plus everything it spawned (MCP servers,
shells, helpers). Sizes are PSS (shared pages split between processes), so stacks add up.

Nothing here assumes a particular runtime. A run leader is recognised structurally: it lives in the
gateway's process tree, is not OpenClaw's own code, and its working directory is an agent workspace.
Runtimes that execute inside the gateway process (``openclaw``, ``codex``, ``copilot``, ...) have no
process of their own, so their memory is part of the gateway's "main".

Everything here reads ``/proc`` (root injectable for tests) and is Linux-only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import cast

MB = 1 << 20
DEFAULT_UNIT = "openclaw-gateway"

# Set by OpenClaw in the environment of every process the gateway spawns. A user's own shell does
# not have them, which is what keeps clawtop from ever touching a hand-started `claude` or `gemini`.
GATEWAY_ENV_MARKERS = (b"OPENCLAW_GATEWAY_SERVICE_PID=", b"OPENCLAW_SERVICE_MARKER=openclaw")

_SESSION = re.compile(r"--(?:session-id|resume)[ =]([0-9a-f-]{36})")
# Launchers whose own name says nothing; the label is the thing they run.
_WRAPPERS = {
    "node", "nodejs", "bun", "bunx", "deno", "python", "python3", "uv", "uvx", "npx", "npm", "pnpm",
    "env", "bash", "sh", "zsh", "dash",
}  # fmt: skip
_RUNNERS = {"exec", "x", "dlx", "run", "tool"}


def _clean(token: str) -> str:
    base = token.strip("'\"").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"\.(m?js|cjs|py)$", "", base)


def label_of(cmd: str) -> str:
    """A short name for a process: its executable, or what a launcher (node, npx, sh -c ...) runs."""
    args = cmd.split()
    if not args:
        return "?"
    exe = _clean(args[0])
    if exe not in _WRAPPERS and not exe.startswith("python"):
        return exe
    rest = [a for a in args[1:] if not a.startswith("-")]
    while len(rest) > 1 and rest[0] in _RUNNERS:  # `npm exec pkg`, `uv tool run pkg`
        rest = rest[1:]
    return _clean(rest[0]) if rest else exe


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    age_s: float
    cmd: str
    cwd: str
    mb: float

    @property
    def label(self) -> str:
        return label_of(self.cmd)

    @property
    def is_openclaw_internal(self) -> bool:
        """The gateway's own code (workers, spawn broker, ...), never an agent run."""
        return "/openclaw/dist/" in self.cmd


@dataclass(frozen=True)
class Workspaces:
    """Where agents work, from OpenClaw's config. Maps a working directory to an agent id."""

    agents: Mapping[str, str] = field(default_factory=lambda: {})  # agent id -> workspace path
    roots: tuple[str, ...] = ()  # directories whose children are workspaces

    def agent_for(self, cwd: str) -> str | None:
        if not cwd:
            return None
        for agent, path in sorted(self.agents.items(), key=lambda kv: -len(kv[1])):
            if cwd == path or cwd.startswith(path.rstrip("/") + "/"):
                return agent
        for root in self.roots:
            prefix = root.rstrip("/") + "/"
            if cwd.startswith(prefix) and cwd[len(prefix) :]:
                return cwd[len(prefix) :].split("/", 1)[0]
        return None

    def __bool__(self) -> bool:
        return bool(self.agents or self.roots)


def state_dir(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """OpenClaw's state directory: ``$OPENCLAW_STATE_DIR`` or ``~/.openclaw``."""
    env = os.environ if env is None else env
    if env.get("OPENCLAW_STATE_DIR"):
        return Path(env["OPENCLAW_STATE_DIR"]).expanduser()
    return (home or Path.home()) / ".openclaw"


def config_path(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("OPENCLAW_CONFIG_PATH"):
        return Path(env["OPENCLAW_CONFIG_PATH"]).expanduser()
    return state_dir(env, home) / "openclaw.json"


def _obj(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def load_workspaces(env: Mapping[str, str] | None = None, home: Path | None = None) -> Workspaces:
    """Agent workspaces from ``CLAWTOP_WORKSPACES`` (``:``-separated roots) and the OpenClaw config.

    The config is read, never written. If it cannot be parsed, only the environment variable counts.
    """
    env = os.environ if env is None else env
    roots = [p for p in env.get("CLAWTOP_WORKSPACES", "").split(":") if p]
    agents: dict[str, str] = {}
    try:
        text = config_path(env, home).read_text()
    except OSError:
        return Workspaces(agents, tuple(roots))
    try:
        data = json.loads(text)
        cfg = _obj(_obj(data).get("agents"))
        default = _obj(cfg.get("defaults")).get("workspace")
        if isinstance(default, str):
            roots.append(default)
        for agent, entry in _obj(cfg.get("entries")).items():
            ws = _obj(entry).get("workspace")
            if isinstance(ws, str):
                agents[agent] = ws
    except ValueError:  # JSON5 (comments, unquoted keys): fall back to a lenient scan
        roots += re.findall(r"""workspace["']?\s*:\s*["']([^"']+)["']""", text)
    return Workspaces(agents, tuple(dict.fromkeys(roots)))


@dataclass(frozen=True)
class Transcript:
    """A runtime's own conversation log for a stack: a real activity and context signal."""

    size_mb: float
    idle_s: float


@dataclass
class Stack:
    kind: str  # "run" (child of the gateway tree) or "orphan" (gateway-spawned, parent gone)
    leader: Proc
    procs: list[Proc]
    agent: str = "?"
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
    def runtime(self) -> str:
        """The leader's executable (``claude``, ``gemini``, ...), not OpenClaw's runtime id."""
        return self.leader.label

    @property
    def idle_s(self) -> float | None:
        """Seconds since the run last wrote to its transcript, or None when the runtime has none."""
        return self.transcript.idle_s if self.transcript else None

    def is_idle_over(self, minutes: float) -> bool:
        return self.idle_s is not None and self.idle_s > minutes * 60

    @property
    def session_id(self) -> str:
        m = _SESSION.search(self.leader.cmd)
        return m.group(1) if m else ""

    @property
    def parts(self) -> list[str]:
        return sorted({p.label for p in self.procs if p.pid != self.leader.pid})


@dataclass
class Snapshot:
    ts: int
    main_pid: int
    main_mb: float
    main_age_s: float
    cg_mb: float
    cg_cache_mb: float
    cg_high: int | None
    cg_max: int | None
    vm_total_mb: float
    vm_avail_mb: float
    swap_used_mb: float
    psi: float
    infra_mb: float
    stacks: list[Stack] = field(default_factory=lambda: [])
    workspaces_known: bool = True

    @property
    def stacks_mb(self) -> float:
        return sum(s.mb for s in self.stacks)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "stacks"}
        d["stacks"] = [
            {
                "pid": s.pid,
                "kind": s.kind,
                "runtime": s.runtime,
                "agent": s.agent,
                "session_id": s.session_id,
                "mb": round(s.mb, 1),
                "age_s": round(s.age_s),
                "idle_s": None if s.idle_s is None else round(s.idle_s),
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


def spawned_by_gateway(pid: int, root: Path = Path("/proc")) -> bool:
    """True if the process environment carries OpenClaw's gateway markers."""
    try:
        env = (root / str(pid) / "environ").read_bytes()
    except OSError:
        return False
    return any(m in env for m in GATEWAY_ENV_MARKERS)


def build_stacks(
    procs: dict[int, Proc],
    members: set[int],
    main: int,
    workspaces: Workspaces,
    signed: Callable[[int], bool] = lambda _pid: False,
) -> tuple[list[Stack], list[Proc]]:
    """Group gateway-owned processes into run stacks; return (stacks, remaining gateway procs).

    ``members`` are the gateway cgroup's PIDs. A process outside the cgroup (left over from a crash,
    or while the gateway is down) only counts if ``signed(pid)`` says the gateway spawned it.
    """

    def is_candidate(pid: int) -> bool:
        p = procs[pid]
        return (
            pid != main
            and not p.is_openclaw_internal
            and workspaces.agent_for(p.cwd) is not None
            and (pid in members or signed(pid))
        )

    candidates = {pid for pid in procs if is_candidate(pid)}

    def has_candidate_ancestor(pid: int) -> bool:
        seen = {pid}
        parent = procs[pid].ppid
        while parent in procs and parent not in seen:
            if parent in candidates:
                return True
            seen.add(parent)
            parent = procs[parent].ppid
        return False

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

    stacks: list[Stack] = []
    seen: set[int] = set()
    for pid in sorted(c for c in candidates if not has_candidate_ancestor(c)):
        parent = procs[pid].ppid
        kind = "run" if parent == main or parent in members else "orphan"
        group = tree(pid)
        seen.update(p.pid for p in group)
        agent = workspaces.agent_for(procs[pid].cwd) or "?"
        stacks.append(Stack(kind=kind, leader=procs[pid], procs=group, agent=agent))
    infra = [procs[pid] for pid in members if pid in procs and pid != main and pid not in seen]
    stacks.sort(key=lambda s: -s.mb)
    return stacks, infra


def find_transcript(stack: Stack, home: Path | None = None, now: float | None = None) -> Transcript | None:
    """Claude Code's transcript for a stack, or None.

    Only Claude Code is supported today: it is the one CLI backend that keeps a transcript file
    keyed by the session id on its command line. For other runtimes idle time is simply unknown.
    """
    sid = stack.session_id
    if stack.runtime != "claude" or not sid or not stack.leader.cwd:
        return None
    slug = re.sub(r"[/.]", "-", stack.leader.cwd)
    path = (home or Path.home()) / ".claude" / "projects" / slug / f"{sid}.jsonl"
    try:
        st = path.stat()
    except OSError:
        return None
    return Transcript(size_mb=st.st_size / MB, idle_s=max(0.0, (now or time.time()) - st.st_mtime))


def _systemctl_pid(unit: str) -> int:
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")}
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


def unit_name() -> str:
    return os.environ.get("CLAWTOP_UNIT") or DEFAULT_UNIT


def take_snapshot(
    unit: str | None = None,
    root: Path = Path("/proc"),
    cgroot: Path = Path("/sys/fs/cgroup"),
    home: Path | None = None,
    workspaces: Workspaces | None = None,
) -> Snapshot:
    main = _systemctl_pid(unit or unit_name())
    cg: Path | None = None
    if main:
        for line in _read(root / str(main) / "cgroup").splitlines():
            if line.startswith("0::"):
                cg = cgroot / line[4:]
    members: set[int] = {int(x) for x in _read(cg / "cgroup.procs").split()} if cg else set()
    procs = read_procs(root)
    ws = workspaces if workspaces is not None else load_workspaces(home=home)
    stacks, infra = build_stacks(procs, members, main, ws, lambda pid: spawned_by_gateway(pid, root))
    for s in stacks:
        s.transcript = find_transcript(s, home)

    meminfo = {ln.split(":")[0]: int(ln.split()[1]) for ln in _read(root / "meminfo").splitlines() if ln.strip()}
    psi = re.search(r"some avg10=([\d.]+)", _read(root / "pressure" / "memory"))
    cache_mb = 0.0
    if cg:
        m = re.search(r"^file (\d+)", _read(cg / "memory.stat"), re.M)
        cache_mb = int(m.group(1)) / MB if m else 0.0

    def limit(name: str) -> int | None:
        v = _read(cg / name, "max").strip() if cg else "max"
        return None if v == "max" else int(v)

    return Snapshot(
        ts=int(time.time()),
        main_pid=main,
        main_mb=procs[main].mb if main in procs else 0.0,
        main_age_s=procs[main].age_s if main in procs else 0.0,
        cg_mb=int(_read(cg / "memory.current", "0")) / MB if cg else 0.0,
        cg_cache_mb=cache_mb,
        cg_high=limit("memory.high"),
        cg_max=limit("memory.max"),
        vm_total_mb=meminfo.get("MemTotal", 0) / 1024,
        vm_avail_mb=meminfo.get("MemAvailable", 0) / 1024,
        swap_used_mb=(meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)) / 1024,
        psi=float(psi.group(1)) if psi else 0.0,
        infra_mb=sum(p.mb for p in infra),
        stacks=stacks,
        workspaces_known=bool(ws),
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
