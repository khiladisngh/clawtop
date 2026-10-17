"""OpenClaw session management, via the ``openclaw sessions`` CLI (the supported gateway API)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from clawtop.procs import state_dir

TERMINAL = {"done", "failed", "killed", "timeout", "archived"}
# Kinds that are safe to archive when idle. Channel/main sessions carry conversation context
# you probably want to keep, so they are never selected unless asked for explicitly.
DEFAULT_PRUNE_KINDS = ("subagent",)

Runner = Callable[[list[str]], str]


class OpenClawError(RuntimeError):
    pass


def run_openclaw(args: list[str], timeout: float = 120) -> str:
    try:
        r = subprocess.run(
            ["openclaw", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.home(),  # openclaw's runtime guard crashes if the caller's cwd was deleted
        )
    except FileNotFoundError as e:
        raise OpenClawError("`openclaw` not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise OpenClawError(f"`openclaw {' '.join(args[:2])}` timed out after {timeout:.0f}s") from e
    if r.returncode != 0:
        raise OpenClawError((r.stderr or r.stdout).strip() or f"openclaw exited {r.returncode}")
    return r.stdout


@dataclass(frozen=True)
class Session:
    key: str
    agent: str
    kind: str
    status: str
    idle_s: float
    tokens: int
    label: str | None = None  # the session title shown in OpenClaw, if it has one
    parent: str | None = None  # key of the session that spawned this one
    depth: int = 0
    runtime: str | None = None  # OpenClaw's agent runtime id, e.g. claude-cli, codex, openclaw

    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL


def _kind(key: str) -> str:
    parts = key.split(":")
    k = parts[2] if len(parts) > 2 else "?"
    return "node" if k.startswith("node") else k


def from_key(key: str) -> Session:
    """A minimal Session for a key the user typed (status/idle unknown, only agent is needed)."""
    if key.count(":") < 2 or not key.startswith("agent:"):
        raise ValueError(f"not a session key (expected agent:<id>:<kind>:...): {key}")
    return Session(key, key.split(":")[1], _kind(key), "open", 0.0, 0)


def _runtime_id(value: object) -> str | None:
    """OpenClaw's ``agentRuntime`` is ``{"id": "claude-cli", "source": ...}`` (the id may be absent)."""
    if isinstance(value, dict):
        rid = cast("dict[str, object]", value).get("id")
        return rid if isinstance(rid, str) else None
    return None


def parse_sessions(raw: str) -> list[Session]:
    data = json.loads(raw)
    out: list[Session] = []
    for s in data["sessions"]:
        key = s["key"]
        out.append(
            Session(
                key=key,
                agent=key.split(":")[1] if ":" in key else "?",
                kind=_kind(key),
                status=s.get("status") or "open",
                idle_s=s.get("ageMs", 0) / 1000,
                tokens=s.get("totalTokens") or 0,
                label=s.get("label") or None,
                parent=s.get("parentSessionKey") or s.get("spawnedBy") or None,
                depth=s.get("spawnDepth") or 0,
                runtime=_runtime_id(s.get("agentRuntime")),
            )
        )
    return out


@dataclass
class Node:
    session: Session
    selected: bool  # False for ancestors pulled in only to give context
    children: list[Node] = field(default_factory=lambda: [])


def build_tree(selected: Iterable[Session], everything: Iterable[Session]) -> list[Node]:
    """Group ``selected`` sessions under the sessions that spawned them.

    Ancestors that were not selected (e.g. a finished parent) are included, marked
    ``selected=False``, so a subagent always appears under its parent. Roots come back
    sorted by agent, then longest idle first.
    """
    by_key = {s.key: s for s in everything}
    chosen = {s.key for s in selected}
    nodes: dict[str, Node] = {}

    def node(key: str) -> Node:
        if key not in nodes:
            nodes[key] = Node(by_key[key], key in chosen)
        return nodes[key]

    roots: dict[str, Node] = {}
    for key in chosen:
        if key not in by_key:
            continue
        cur, seen = key, {key}
        while True:
            n = node(cur)
            parent = by_key[cur].parent
            if parent is None or parent not in by_key or parent in seen:  # root, dangling, or a cycle
                roots[cur] = n
                break
            p = node(parent)
            if not any(c is n for c in p.children):
                p.children.append(n)
            seen.add(parent)
            cur = parent
    for n in nodes.values():
        n.children.sort(key=lambda c: -c.session.idle_s)
    return sorted(roots.values(), key=lambda n: (n.session.agent, -n.session.idle_s))


def archived_keys(agents_dir: Path | None = None) -> set[str]:
    """Keys of archived sessions, read (read-only) from each agent's database.

    ``openclaw sessions --json`` does not say whether a session is archived: an archived
    session keeps its old status (blank = "open"). The flag lives in ``session_nodes.archived_at``.
    That schema is internal to OpenClaw, so any failure just yields no archived keys.
    """
    root = agents_dir or state_dir() / "agents"
    keys: set[str] = set()
    for db in root.glob("*/agent/openclaw-agent.sqlite"):
        try:
            con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=2)
            try:
                keys.update(
                    r[0] for r in con.execute("SELECT session_key FROM session_nodes WHERE archived_at IS NOT NULL")
                )
            finally:
                con.close()
        except sqlite3.Error:
            continue
    return keys


def list_sessions(run: Runner = run_openclaw, agents_dir: Path | None = None) -> list[Session]:
    rows = parse_sessions(run(["sessions", "--all-agents", "--limit", "all", "--json"]))
    archived = archived_keys(agents_dir)
    return [replace(s, status="archived") if s.key in archived and s.is_open else s for s in rows]


def select(
    sessions: Iterable[Session],
    *,
    idle_s: float = 0,
    kinds: Iterable[str] | None = None,
    agents: Iterable[str] | None = None,
    recent_s: float = 0,
) -> list[Session]:
    """Open sessions idle for at least ``idle_s``, optionally limited to kinds/agents.

    ``recent_s`` also includes closed sessions active within that many seconds (used by the tree,
    because subagents finish within minutes and would otherwise never be visible).
    """
    kinds_, agents_ = set(kinds or ()), set(agents or ())
    return sorted(
        (
            s
            for s in sessions
            if (s.is_open or s.idle_s < recent_s)
            and s.idle_s >= idle_s
            and (not kinds_ or s.kind in kinds_)
            and (not agents_ or s.agent in agents_)
        ),
        key=lambda s: -s.idle_s,
    )


def archive(
    sessions: Iterable[Session], *, dry_run: bool = False, run: Runner = run_openclaw
) -> list[dict[str, object]]:
    """Archive sessions via the gateway (it needs ``--agent`` per call, so batch by agent)."""
    by_agent: dict[str, list[str]] = defaultdict(list)
    for s in sessions:
        by_agent[s.agent].append(s.key)
    results: list[dict[str, object]] = []
    for agent, keys in by_agent.items():
        args = [
            "sessions",
            "archive",
            "--agent",
            agent,
            "--json",
            *(["--dry-run"] if dry_run else []),
            *keys,
        ]
        results += json.loads(run(args))["results"]
    return results
