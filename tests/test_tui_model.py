from __future__ import annotations

from rich.console import Console

from clawtop.procs import Stack
from clawtop.tui import model

from .conftest import UUID_A, proc, snapshot, stack


def _pids(stacks: list[Stack]) -> list[int]:
    return [s.pid for s in stacks]


def test_sort_by_memory_biggest_first_and_reversible() -> None:
    a, b, c = stack(1, mb=300), stack(2, mb=700), stack(3, mb=500)
    assert _pids(model.sort_stacks([a, b, c], "mem", True)) == [2, 3, 1]
    assert _pids(model.sort_stacks([a, b, c], "mem", False)) == [1, 3, 2]


def test_sort_by_idle_puts_unknown_idle_last_in_both_directions() -> None:
    known_long = stack(1, idle_s=7200)
    known_short = stack(2, idle_s=30)
    unknown = stack(3, cmd="gemini --yolo")  # no transcript: idle is unknown, not zero
    for descending, expected in ((True, [1, 2, 3]), (False, [2, 1, 3])):
        assert _pids(model.sort_stacks([unknown, known_short, known_long], "idle", descending)) == expected


def test_sort_by_name_is_case_insensitive_with_pid_as_tiebreak() -> None:
    s = [stack(5, agent="Zed"), stack(2, agent="alpha"), stack(9, agent="alpha")]
    assert _pids(model.sort_stacks(s, "agent", False)) == [2, 9, 5]
    assert _pids(model.sort_stacks([stack(1), stack(2, cmd="gemini")], "runtime", False)) == [1, 2]


def test_filter_requires_every_term_in_any_field() -> None:
    claude = stack(100, agent="builder")
    gemini = stack(200, agent="writer", cmd="gemini --yolo")
    everything = [claude, gemini]
    assert _pids(model.filter_stacks(everything, "")) == [100, 200]
    assert _pids(model.filter_stacks(everything, "GEMINI")) == [200]
    assert _pids(model.filter_stacks(everything, "builder claude")) == [100]
    assert model.filter_stacks(everything, "builder gemini") == []
    assert _pids(model.filter_stacks(everything, "200")) == [200]


def test_next_in_wraps_and_recovers_from_an_unknown_value() -> None:
    assert model.next_in(("a", "b", "c"), "a") == "b"
    assert model.next_in(("a", "b", "c"), "c") == "a"
    assert model.next_in(("a", "b", "c"), "zzz") == "a"


def test_flags_orphans_and_only_known_stale_idle() -> None:
    assert model.flag_of(stack(1, kind="orphan"), 30) == "ORPHAN"
    assert model.flag_of(stack(2, idle_s=31 * 60), 30) == "STALE"
    assert model.flag_of(stack(3, idle_s=29 * 60), 30) == ""
    assert model.flag_of(stack(4, cmd="gemini", age_s=99999), 30) == ""  # unknown idle is never stale


def test_cells_show_mark_and_dash_for_unknown_idle() -> None:
    marked = [c.plain for c in model.stack_cells(stack(1, idle_s=60), 30, marked=True)]
    assert marked[0] == "\u2714" and marked[1] == "1" and marked[2] == "claude"
    plain = [c.plain for c in model.stack_cells(stack(2, cmd="gemini"), 30, marked=False)]
    assert plain[0] == " " and plain[4] == "-" and plain[6] == "-"  # idle and context unknown


def test_process_tree_nests_children_under_their_parent_with_memory() -> None:
    leader = proc(10, 1, f"claude --session-id {UUID_A}", "/srv/ws/a", mb=300)
    kid = proc(11, 10, "node tools/docs-mcp", mb=200)
    grandkid = proc(12, 11, "node helper", mb=50)
    outsider = proc(99, 55, "node elsewhere", mb=999)  # parent not in the stack: must not appear
    s = Stack("run", leader, [leader, kid, grandkid, outsider], "a")
    con = Console(width=80, color_system=None, record=True)
    con.print(model.stack_tree(s))
    text = con.export_text()
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    assert lines[0].startswith("claude") and "300M" in lines[0]
    assert "docs-mcp" in lines[1] and "200M" in lines[1]
    assert "helper" in lines[2] and lines[2].index("helper") > lines[1].index("docs-mcp")
    assert "elsewhere" not in text


def test_meters_say_so_when_the_gateway_is_down() -> None:
    snap = snapshot([])
    snap.main_pid = 0
    con = Console(width=100, color_system=None, record=True)
    con.print(model.meters(snap))
    assert "NOT RUNNING" in con.export_text()


def test_ring_keeps_the_newest_and_seeds_older_samples_in_front() -> None:
    ring = model.Ring(5)
    for v in (1, 2, 3):
        ring.add(v)
    ring.extend_front([-2, -1, 0, 0.5])  # only two slots free: the newest two of the seed survive
    assert ring.values() == [0, 0.5, 1, 2, 3]
    for v in (4, 5):
        ring.add(v)
    assert ring.values() == [1, 2, 3, 4, 5]


def test_graph_is_scaled_from_zero_to_the_limit_so_flat_looks_flat() -> None:
    flat = model.graph([5000.0] * 10, width=10, height=4, limit_mb=10000).plain.split("\n")
    assert len(flat) == 4 and all(len(r) == 10 for r in flat)
    assert flat[-1] == "\u2588" * 10  # half the limit fills the bottom two rows completely
    assert flat[-2] == "\u2588" * 10
    assert flat[0].strip("\u2504 ") == ""  # nothing in the top rows apart from the limit marker
    assert "\u2504" in "".join(flat)  # the limit line is drawn when it fits


def test_graph_right_aligns_short_history_and_keeps_spikes_when_downsampling() -> None:
    short = model.graph([1000.0, 2000.0], width=6, height=2, limit_mb=2000).plain.split("\n")
    assert all(row[:4].strip("\u2504 ") == "" for row in short)  # the empty left side stays blank
    values = [100.0] * 100
    values[50] = 9000.0
    squeezed = model.graph(values, width=10, height=3, limit_mb=10000).plain.split("\n")
    assert any(row.strip("\u2504 ") for row in squeezed[:2])  # the spike survives being squeezed 10:1
    assert model.graph([], 10, 3).plain == "waiting for data ..."
