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


def _s(
    key: str, parent: str | None = None, status: str = "open", label: str | None = None, idle: float = 60
) -> sess.Session:
    return sess.Session(
        key, key.split(":")[1], "subagent" if "subagent" in key else "main", status, idle, 0, label, parent
    )


def test_parse_reads_title_and_parent_from_gateway_json() -> None:
    raw = json.dumps(
        {
            "sessions": [
                {
                    "key": "agent:forge:subagent:x",
                    "label": "Worktree removal proposal",
                    "parentSessionKey": "agent:forge:main",
                    "spawnDepth": 1,
                },
                {"key": "agent:forge:subagent:y", "spawnedBy": "agent:forge:main"},
                {"key": "agent:forge:main"},
            ]
        }
    )
    x, y, main = sess.parse_sessions(raw)
    assert (x.label, x.parent, x.depth) == ("Worktree removal proposal", "agent:forge:main", 1)
    assert y.parent == "agent:forge:main" and y.label is None  # falls back to spawnedBy
    assert main.parent is None


def test_tree_nests_open_subagent_under_a_finished_parent_marked_as_context() -> None:
    parent = _s("agent:forge:main", status="done")
    kid = _s("agent:forge:subagent:a", parent=parent.key, label="rig survey")
    grandkid = _s("agent:forge:subagent:b", parent=kid.key)
    other = _s("agent:maya:main")
    everything = [parent, kid, grandkid, other]
    roots = sess.build_tree(sess.select(everything), everything)
    assert [r.session.key for r in roots] == [parent.key, other.key]
    root = roots[0]
    assert root.selected is False  # shown only for context: it is finished
    assert [c.session.key for c in root.children] == [kid.key]
    assert [c.session.key for c in root.children[0].children] == [grandkid.key]
    assert root.children[0].selected and root.children[0].children[0].selected


def test_tree_survives_dangling_parent_and_cycles() -> None:
    lost = _s("agent:forge:subagent:lost", parent="agent:forge:subagent:gone")
    a = _s("agent:atlas:subagent:a", parent="agent:atlas:subagent:b")
    b = _s("agent:atlas:subagent:b", parent="agent:atlas:subagent:a")
    everything = [lost, a, b]
    roots = sess.build_tree(everything, everything)
    assert lost.key in {r.session.key for r in roots}  # dangling parent: becomes its own root
    assert roots  # a/b cycle must terminate
