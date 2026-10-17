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
            {"key": "agent:builder:subagent:a", "ageMs": 7_200_000, "totalTokens": 5},
            {"key": "agent:builder:subagent:b", "ageMs": 60_000, "status": ""},
            {"key": "agent:builder:subagent:c", "ageMs": 9_000_000, "status": "done"},
            {"key": "agent:writer:discord:channel:1", "ageMs": 99_000_000},
            {"key": "agent:researcher:node-80db96a94980", "ageMs": 1000},
            {"key": "agent:auditor:cron:x", "ageMs": 8_000_000, "status": "killed"},
        ]
    }
)


def test_open_means_not_terminal_and_kind_is_parsed() -> None:
    rows = {s.key: s for s in sess.parse_sessions(RAW)}
    assert rows["agent:builder:subagent:a"].is_open and rows["agent:builder:subagent:b"].is_open
    assert not rows["agent:builder:subagent:c"].is_open
    assert not rows["agent:auditor:cron:x"].is_open
    assert rows["agent:researcher:node-80db96a94980"].kind == "node"
    assert rows["agent:writer:discord:channel:1"].kind == "discord"


def test_prune_selection_is_idle_open_subagents_only_by_default() -> None:
    rows = sess.parse_sessions(RAW)
    picked = sess.select(rows, idle_s=3600, kinds=sess.DEFAULT_PRUNE_KINDS)
    # a: open+idle 2h. b: idle 1m. c: already done. discord channel: not a subagent.
    assert [s.key for s in picked] == ["agent:builder:subagent:a"]
    everything = sess.select(rows, idle_s=0)
    assert everything[0].key == "agent:writer:discord:channel:1"  # longest idle first


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

    items = [sess.from_key(k) for k in ("agent:builder:subagent:a", "agent:builder:subagent:b", "agent:writer:cron:z")]
    res = sess.archive(items, run=fake)
    assert len(res) == 3
    assert len(calls) == 2
    builder = next(c for c in calls if "builder" in c)
    assert builder[:5] == ["sessions", "archive", "--agent", "builder", "--json"]
    assert "--dry-run" not in builder


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
                    "key": "agent:builder:subagent:x",
                    "label": "Worktree removal proposal",
                    "parentSessionKey": "agent:builder:main",
                    "spawnDepth": 1,
                },
                {"key": "agent:builder:subagent:y", "spawnedBy": "agent:builder:main", "agentRuntime": {"id": "codex"}},
                {"key": "agent:builder:main"},
            ]
        }
    )
    x, y, main = sess.parse_sessions(raw)
    assert (x.label, x.parent, x.depth) == ("Worktree removal proposal", "agent:builder:main", 1)
    assert y.parent == "agent:builder:main" and y.label is None  # falls back to spawnedBy
    assert main.parent is None
    assert (x.runtime, y.runtime, main.runtime) == (None, "codex", None)  # whatever OpenClaw reports; never assumed


def test_tree_nests_open_subagent_under_a_finished_parent_marked_as_context() -> None:
    parent = _s("agent:builder:main", status="done")
    kid = _s("agent:builder:subagent:a", parent=parent.key, label="rig survey")
    grandkid = _s("agent:builder:subagent:b", parent=kid.key)
    other = _s("agent:writer:main")
    everything = [parent, kid, grandkid, other]
    roots = sess.build_tree(sess.select(everything), everything)
    assert [r.session.key for r in roots] == [parent.key, other.key]
    root = roots[0]
    assert root.selected is False  # shown only for context: it is finished
    assert [c.session.key for c in root.children] == [kid.key]
    assert [c.session.key for c in root.children[0].children] == [grandkid.key]
    assert root.children[0].selected and root.children[0].children[0].selected


def test_tree_survives_dangling_parent_and_cycles() -> None:
    lost = _s("agent:builder:subagent:lost", parent="agent:builder:subagent:gone")
    a = _s("agent:researcher:subagent:a", parent="agent:researcher:subagent:b")
    b = _s("agent:researcher:subagent:b", parent="agent:researcher:subagent:a")
    everything = [lost, a, b]
    roots = sess.build_tree(everything, everything)
    assert lost.key in {r.session.key for r in roots}  # dangling parent: becomes its own root
    assert roots  # a/b cycle must terminate


def test_archived_sessions_are_not_open_even_though_the_gateway_json_gives_them_no_status(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "builder" / "agent" / "openclaw-agent.sqlite"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE session_nodes (session_key TEXT PRIMARY KEY, archived_at INTEGER)")
    con.executemany(
        "INSERT INTO session_nodes VALUES (?, ?)",
        [("agent:builder:subagent:old", 1792162140061), ("agent:builder:subagent:live", None)],
    )
    con.commit()
    con.close()
    (tmp_path / "broken" / "agent").mkdir(parents=True)
    (tmp_path / "broken" / "agent" / "openclaw-agent.sqlite").write_bytes(b"not a database")  # must not abort

    raw = json.dumps({"sessions": [{"key": "agent:builder:subagent:old"}, {"key": "agent:builder:subagent:live"}]})
    rows = {s.key: s for s in sess.list_sessions(run=lambda _a: raw, agents_dir=tmp_path)}
    assert not rows["agent:builder:subagent:old"].is_open and rows["agent:builder:subagent:old"].status == "archived"
    assert rows["agent:builder:subagent:live"].is_open
    assert [s.key for s in sess.select(rows.values(), kinds=sess.DEFAULT_PRUNE_KINDS)] == [
        "agent:builder:subagent:live"
    ]
    assert sess.archived_keys(tmp_path / "missing") == set()
