"""Run the real clawtop CLI against made-up sample data: no gateway, no WSL, nothing is killed.

    uv run python scripts/demo.py status
    uv run python scripts/demo.py sessions tree
    CLAWTOP_DEMO_ANSWERS="stale;y" uv run python scripts/demo.py kill      # scripted picker answers

Process list, memory figures, session titles and the memory history are invented. The commands,
option parsing and rendering are the real code. ``kill`` and ``sessions archive`` are simulated.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import typer

from clawtop import cli
from clawtop import sessions as sess
from clawtop.procs import Proc, Snapshot, Stack, Transcript

NOW = time.time()
UUID = "{:08x}-1111-4222-8333-{:012x}"


def _stack(pid: int, agent: str, mb: float, idle_s: float, age_s: float, ctx_mb: float, n: int) -> Stack:
    cwd = f"/opt/openclaw/workspaces/{agent}"
    sid = UUID.format(n * 0x1111111, n * 0x10101)
    leader = Proc(pid, 1, age_s, f"/home/user/.local/bin/claude --session-id {sid}", cwd, mb * 0.42)
    kids = [
        Proc(pid + 1, pid, age_s, "node /usr/lib/bin/rea mcp", cwd, mb * 0.35),
        Proc(pid + 2, pid, age_s, "npm exec @notionhq/notion-mcp-server", cwd, mb * 0.10),
        Proc(pid + 3, pid + 2, age_s, "node .bin/notion-mcp-server", cwd, mb * 0.13),
    ]
    return Stack("run", leader, [leader, *kids], Transcript(ctx_mb, idle_s))


def snapshot() -> Snapshot:
    stacks = [
        _stack(4102, "builder", 734, 95, 640, 2.1, 1),
        _stack(3877, "researcher", 612, 8 * 60, 1500, 0.9, 2),
        _stack(2950, "writer", 530, 54 * 60, 3500, 0.4, 3),
        _stack(2211, "builder", 498, 2 * 3600 + 600, 9000, 1.6, 4),
    ]
    return Snapshot(
        ts=int(NOW), main_pid=999, main_mb=2350, main_age_s=5 * 3600, cg_mb=8200, cg_cache_mb=2900,
        cg_high=11 << 30, cg_max=13 << 30, vm_total_mb=15996, vm_avail_mb=8400, swap_used_mb=0, psi=0.4,
        infra_mb=1100, stacks=stacks,
    )  # fmt: skip


def _session(
    agent: str, kind: str, status: str, idle_s: float, tokens: int, label: str | None, n: int, parent: str | None
):
    tail = {"main": "main", "cron": f"cron:{n:04x}", "subagent": f"subagent:{UUID.format(n * 0x3A3A3A3, n * 0x777)}"}[
        kind
    ]
    return sess.Session(f"agent:{agent}:{tail}", agent, kind, status, idle_s, tokens, label, parent)


def sessions() -> list[sess.Session]:
    out = [
        _session("builder", "main", "open", 20, 188_000, None, 1, None),
        _session("researcher", "main", "open", 600, 96_000, None, 2, None),
        _session("writer", "main", "open", 3 * 3600, 71_000, None, 3, None),
    ]
    bm = "agent:builder:main"
    for n, (status, idle, label) in enumerate(
        [
            ("open", 190, "Refactor billing module"),
            ("done", 17 * 60, "Triage failing tests in CI"),
            ("done", 40 * 60, "Draft release notes for v2.4"),
            ("open", 14 * 3600, "Investigate flaky upload test"),
        ],
        start=1,
    ):
        out.append(_session("builder", "subagent", status, idle, 0 if status == "open" else 120_000, label, n, bm))
    out.append(
        _session(
            "researcher",
            "subagent",
            "done",
            25 * 60,
            88_000,
            "Summarise competitor pricing pages",
            9,
            "agent:researcher:main",
        )
    )
    out.append(
        _session(
            "researcher", "subagent", "open", 15 * 3600, 0, "Collect benchmark datasets", 10, "agent:researcher:main"
        )
    )
    out.append(_session("writer", "cron", "open", 7 * 3600, 64_000, "Automation: daily-digest", 11, None))
    return out


def history_log() -> str:
    """Six hours of per-minute samples with one burst of concurrent runs (the shape of a real spike)."""
    path = Path(tempfile.mkdtemp()) / "samples.jsonl"
    rows = []
    for i in range(360):
        t = 359 - i
        burst = max(0.0, 1 - abs(i - 215) / 40)  # peak about 2h20m ago
        cg = 3300 + 5200 * burst + 900 * (i / 360) + (i % 7) * 18
        stacks = [
            [4100 + k, a, 520 + 40 * k, 30 + k]
            for k, a in enumerate(["builder", "researcher", "writer", "builder", "builder"][: int(1 + 4 * burst)])
        ]
        rows.append({
            "ts": int(NOW - t * 60), "main": 999, "main_mb": 2100 + 200 * burst, "cg_mb": round(cg, 1),
            "vm_avail": 9000 - 2000 * burst, "swap_used": round(max(0.0, 420 * (burst - 0.8)) * 5, 1), "psi": 0.0,
            "infra_mb": 1000, "stacks": stacks,
        })  # fmt: skip
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


def main() -> int:
    answers = [a for a in os.environ.get("CLAWTOP_DEMO_ANSWERS", "").split(";") if a]
    interactive = bool(answers)  # read once: answers are consumed as the prompts are answered

    def answer(text: str, suffix: str) -> str:  # echo the answer the way a terminal would
        ans = answers.pop(0) if answers else ""
        sys.stdout.write(f"{text}{suffix}{ans}\n")
        return ans

    typer.prompt = lambda text, default=None, **_k: answer(text, ": ") or default
    typer.confirm = lambda text, default=False, **_k: answer(text, " [y/N]: ").lower() in {"y", "yes"}
    os.environ.setdefault("CLAWTOP_LOG", history_log())
    cli.take_snapshot = snapshot
    cli.kill_stack = lambda *_a, **_k: []
    sess.list_sessions = lambda *_a, **_k: sessions()
    sess.archive = lambda items, **_k: [{"key": s.key, "ok": True, "status": "archived"} for s in items]
    cli.sys = SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: interactive), platform="linux", argv=sys.argv)  # type: ignore[assignment]
    try:
        cli.app(sys.argv[1:], prog_name="clawtop")
    except SystemExit as e:
        return int(e.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
