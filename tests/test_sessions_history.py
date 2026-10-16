from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawtop import history as hist
from clawtop import sessions as sess

from .conftest import snapshot, stack

RAW = json.dumps(
    {
        "sessions": [
            {"key": "agent:forge:subagent:a", "ageMs": 7_200_000, "totalTokens": 5},
            {"key": "agent:forge:subagent:b", "ageMs": 60_000, "status": ""},
            {"key": "agent:forge:subagent:c", "ageMs": 9_000_000, "status": "done"},
            {"key": "agent:maya:discord:channel:1", "ageMs": 99_000_000},
            {"key": "agent:atlas:node-80db96a94980", "ageMs": 1000},
            {"key": "agent:ledger:cron:x", "ageMs": 8_000_000, "status": "killed"},
        ]
    }
)


def test_open_means_not_terminal_and_kind_is_parsed() -> None:
    rows = {s.key: s for s in sess.parse_sessions(RAW)}
    assert rows["agent:forge:subagent:a"].is_open and rows["agent:forge:subagent:b"].is_open
    assert not rows["agent:forge:subagent:c"].is_open
    assert not rows["agent:ledger:cron:x"].is_open
    assert rows["agent:atlas:node-80db96a94980"].kind == "node"
    assert rows["agent:maya:discord:channel:1"].kind == "discord"


def test_prune_selection_is_idle_open_subagents_only_by_default() -> None:
    rows = sess.parse_sessions(RAW)
    picked = sess.select(rows, idle_s=3600, kinds=sess.DEFAULT_PRUNE_KINDS)
    # a: open+idle 2h. b: idle 1m. c: already done. discord channel: not a subagent.
    assert [s.key for s in picked] == ["agent:forge:subagent:a"]
    everything = sess.select(rows, idle_s=0)
    assert everything[0].key == "agent:maya:discord:channel:1"  # longest idle first


def test_archive_batches_one_call_per_agent() -> None:
    calls: list[list[str]] = []

    def fake(args: list[str]) -> str:
        calls.append(args)
        return json.dumps(
            {
                "results": [
                    {"key": k, "ok": True, "status": "archived"}
                    for k in args[args.index("--json") + 1 :]
                    if k.startswith("agent:")
                ]
            }
        )

    items = [sess.from_key(k) for k in ("agent:forge:subagent:a", "agent:forge:subagent:b", "agent:maya:cron:z")]
    res = sess.archive(items, run=fake)
    assert len(res) == 3
    assert len(calls) == 2
    forge = next(c for c in calls if "forge" in c)
    assert forge[:5] == ["sessions", "archive", "--agent", "forge", "--json"]
    assert "--dry-run" not in forge


def test_from_key_rejects_non_keys() -> None:
    with pytest.raises(ValueError):
        sess.from_key("just-a-uuid")


def test_history_roundtrip_skips_torn_lines_and_old_rows(tmp_path: Path) -> None:
    log = tmp_path / "s.jsonl"
    snap = snapshot([stack(7)])
    hist.append_sample(snap, log)
    with log.open("a") as f:
        f.write('{"ts": 17000000\n')  # torn write
    rows = hist.load(log, since_s=60, now=snap.ts + 30)
    assert len(rows) == 1 and rows[0]["cg_mb"] == 4000
    assert hist.load(log, since_s=60, now=snap.ts + 3600) == []


def test_history_rotates_past_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hist, "MAX_BYTES", 10)
    log = tmp_path / "s.jsonl"
    hist.append_sample(snapshot([]), log)
    hist.append_sample(snapshot([]), log)
    assert log.with_suffix(".jsonl.1").exists()
    assert len(log.read_text().splitlines()) == 1


def test_sparkline_keeps_a_spike_when_downsampling() -> None:
    values = [1.0] * 500
    values[250] = 100.0
    line = hist.sparkline(values, width=50)
    assert len(line) == 50
    assert "█" in line
    assert hist.sparkline([]) == ""
    assert set(hist.sparkline([5, 5, 5])) == {"▁"}  # flat series must not divide by zero
