"""Append-only memory samples (JSONL) and a text sparkline for ``clawtop history``."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

from clawtop.procs import Snapshot, state_dir

MAX_BYTES = 20 * (1 << 20)
_BARS = "▁▂▃▄▅▆▇█"


class Sample(TypedDict):
    ts: int
    main: int
    main_mb: float
    cg_mb: float
    vm_avail: float
    swap_used: float
    psi: float
    infra_mb: float
    stacks: list[list[int | str]]  # [pid, agent, mb, age_min]


def default_log() -> Path:
    if os.environ.get("CLAWTOP_LOG"):
        return Path(os.environ["CLAWTOP_LOG"]).expanduser()
    return state_dir() / "logs" / "mem-samples.jsonl"


def append_sample(snap: Snapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > MAX_BYTES:
        path.replace(path.with_suffix(path.suffix + ".1"))
    line: Sample = {
        "ts": snap.ts,
        "main": snap.main_pid,
        "main_mb": round(snap.main_mb, 1),
        "cg_mb": round(snap.cg_mb, 1),
        "vm_avail": round(snap.vm_avail_mb, 1),
        "swap_used": round(snap.swap_used_mb, 1),
        "psi": snap.psi,
        "infra_mb": round(snap.infra_mb, 1),
        "stacks": [[s.pid, s.agent, round(s.mb), round(s.age_s / 60)] for s in snap.stacks],
    }
    with path.open("a") as f:
        f.write(json.dumps(line, separators=(",", ":")) + "\n")


def load(path: Path, since_s: float, now: float | None = None) -> list[Sample]:
    """Samples newer than ``since_s`` seconds ago. Corrupt lines (torn writes) are skipped."""
    cutoff = (now or time.time()) - since_s
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out: list[Sample] = []
    for ln in lines:
        try:
            row: object = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        d = cast("dict[str, object]", row)
        ts = d.get("ts")
        if isinstance(ts, int) and ts >= cutoff and "cg_mb" in d:
            out.append(cast("Sample", d))
    return out


def sparkline(values: Sequence[float], width: int = 60) -> str:
    if not values:
        return ""
    if len(values) > width:  # bucket by max so spikes survive downsampling
        step = len(values) / width
        values = [max(values[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)]) for i in range(width)]
    lo, hi = min(values), max(values)
    span = hi - lo or 1
    return "".join(_BARS[min(7, int((v - lo) / span * 8))] for v in values)
