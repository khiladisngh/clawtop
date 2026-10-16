"""OpenClaw session management, via the ``openclaw sessions`` CLI (the supported gateway API)."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

TERMINAL = {"done", "failed", "killed", "timeout"}
# Kinds that are safe to archive when idle. Channel/main sessions carry conversation context
# you probably want to keep, so they are never selected unless asked for explicitly.
DEFAULT_PRUNE_KINDS = ("subagent",)

Runner = Callable[[list[str]], str]


class OpenClawError(RuntimeError):
    pass


def run_openclaw(args: list[str], timeout: float = 120) -> str:
    try:
        r = subprocess.run(["openclaw", *args], capture_output=True, text=True, timeout=timeout)
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
            )
        )
    return out


def list_sessions(run: Runner = run_openclaw) -> list[Session]:
    return parse_sessions(run(["sessions", "--all-agents", "--limit", "all", "--json"]))


def select(
    sessions: Iterable[Session],
    *,
    idle_s: float = 0,
    kinds: Iterable[str] | None = None,
    agents: Iterable[str] | None = None,
) -> list[Session]:
    """Open sessions idle for at least ``idle_s``, optionally limited to kinds/agents."""
    kinds_, agents_ = set(kinds or ()), set(agents or ())
    return sorted(
        (
            s
            for s in sessions
            if s.is_open
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
