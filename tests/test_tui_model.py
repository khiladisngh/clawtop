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


def test_meters_show_gauges_and_where_the_gateways_memory_goes() -> None:
    con = Console(width=100, color_system=None, record=True)
    con.print(model.meters(snapshot([stack(1, mb=300)]), width=60))
    lines = con.export_text().splitlines()
    vm = next(ln for ln in lines if ln.startswith("VM"))
    assert "[" in vm and "]" in vm and "25%" in vm and "3.9G/15.6G" in vm  # 4000 of 16000 MB used (GiB figures)
    gateway = next(ln for ln in lines if ln.startswith("Gateway"))
    assert "3.9G/11.0G high" in gateway
    for name in ("main", "runs", "other", "cache"):
        assert any(ln.strip().startswith(name) for ln in lines), name
    # every gauge ends at the same column, whatever its figures say
    assert len({ln.index("]") for ln in lines if ln.startswith(("VM", "Gateway", "Swap"))}) == 1


def test_pipe_bar_fills_in_proportion_and_never_overflows() -> None:
    assert model.pipe_bar(50, 100, 12).plain == "[|||||     ]"
    assert model.pipe_bar(0, 100, 12).plain == "[          ]"
    assert model.pipe_bar(500, 100, 12).plain == "[||||||||||]"  # over the total: full, not longer
    assert model.pipe_bar(5, 0, 12).plain == "[          ]"  # no total: empty, no division by zero


def test_ring_keeps_the_newest_and_seeds_older_samples_in_front() -> None:
    ring: model.Ring[float] = model.Ring(5)
    for v in (1, 2, 3):
        ring.add(v)
    ring.extend_front([-2, -1, 0, 0.5])  # only two slots free: the newest two of the seed survive
    assert ring.values() == [0, 0.5, 1, 2, 3]
    for v in (4, 5):
        ring.add(v)
    assert ring.values() == [1, 2, 3, 4, 5]


def _dots(rows: list[str]) -> list[str]:
    """Which cell rows hold any braille dot."""
    return [r for r in rows if r.strip()]


def test_plot_draws_a_flat_value_on_one_row_at_the_matching_height() -> None:
    rows = [r.plain for r in model.plot([model.Line([5000.0] * 20, "")], width=10, height=4, ymax=10000.0)]
    assert len(rows) == 4 and all(len(r) == 10 for r in rows)
    lit = [i for i, r in enumerate(rows) if r.strip()]
    assert lit == [2]  # half of ymax lands in the third of four cell rows (dot row 8 of 16)
    assert all(ch != " " for ch in rows[2])  # and the line runs the full width


def test_plot_scales_from_zero_so_the_peak_touches_the_top_and_zero_the_bottom() -> None:
    rows = [r.plain for r in model.plot([model.Line([0.0, 0.0, 10.0, 10.0], "")], width=2, height=3, ymax=10.0)]
    assert rows[0].strip() and rows[-1].strip()  # the rise is joined by a vertical stroke from bottom to top
    assert model.plot([model.Line([99.0], "")], 2, 2, ymax=10.0)[0].plain.strip()  # above ymax: clamped to the top


def test_plot_right_aligns_short_series_and_keeps_spikes_when_squeezed() -> None:
    short = [r.plain for r in model.plot([model.Line([1.0, 2.0], "")], width=6, height=2, ymax=2.0)]
    assert all(r[:5] == " " * 5 for r in short)  # two samples occupy only the right edge
    values = [100.0] * 100
    values[52] = 9000.0  # between sampling points: only a max-per-column squeeze can see it
    squeezed = [r.plain for r in model.plot([model.Line(values, "")], width=10, height=3, ymax=10000.0)]
    assert squeezed[0].strip()  # the spike survives being squeezed 10:1 and reaches the top row


def test_plot_draws_the_limit_as_a_dotted_line_under_the_series() -> None:
    rows = model.plot([model.Line([1000.0] * 10, "red")], width=10, height=4, ymax=10000.0, hline=10000.0)
    assert rows[0].plain.strip() and rows[0].plain.count(" ") > 0  # dotted: gaps between the dots
    assert all(span.style == "dim" for span in rows[0].spans if span.style)  # and dimmed, unlike the series


def test_graph_labels_the_axes_and_says_when_it_has_no_data() -> None:
    points = [model.Point(5000.0, 1000.0, 500.0)] * 12
    out = model.graph(points, width=40, height=7, limit_mb=10000.0, span_s=600).plain.split("\n")
    assert len(out) == 7  # six plot rows plus the time axis
    assert out[0].lstrip().startswith("9.8G") or out[0].lstrip().startswith("10")  # top = the limit
    assert out[-1].strip().startswith("10m") and out[-1].rstrip().endswith("0s")
    assert any(row.strip().startswith("0") for row in out[:-1])  # zero at the bottom of the plot
    assert model.graph([], 40, 7, None, 0).plain == "waiting for data ..."


def test_legend_lists_each_series_with_its_current_value() -> None:
    text = model.legend(snapshot([stack(1, mb=300)]), 11 * 1024).plain
    for word in ("Gateway", "Runs", "Other", "limit", "cache"):
        assert word in text
    assert "3.9G" in text and "11.0G" in text and model.legend(None, None).plain == ""
