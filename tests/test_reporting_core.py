"""Reporting core (gate B): criteria, streaming n-1 comparison, statistics, episodes and coverage.

Uses only SYNTHETIC TEST DATA (tests/synthetic_grid.py) and hand-built sources; no PowerFactory.
"""

from __future__ import annotations

import importlib.util
import tracemalloc

import pytest

import synthetic_grid as sg
from _paths import delivered

SPEC = importlib.util.spec_from_file_location("gridlens_reporting_core", delivered("main.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)

H = 3600.0
T0 = sg.EPOCH
OK, NR, FAIL, NA, MISSING = gl.STATE_OK, gl.STATE_NOT_RECORDED_CELL, gl.STATE_FAILED, gl.STATE_NOT_APPLICABLE, gl.STATE_MISSING


@pytest.fixture(autouse=True)
def _defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


def status(criterion, threshold, reference, scenario, recording=sg.RECORDING):
    return gl.classify_criterion(criterion, threshold, reference, scenario, recording=recording)["status"]


# ---------------------------------------------------------------------------
# Classification per criterion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reference, scenario, expected", [
    ((OK, 90.0), (OK, 95.0), "OK"),
    ((OK, 90.0), (OK, 105.0), "NEW"),
    ((OK, 105.0), (OK, 110.0), "WORSENED"),
    ((OK, 105.0), (OK, 105.05), "PRE_EXISTING"),
    ((OK, 110.0), (OK, 105.0), "IMPROVED"),
    ((OK, 105.0), (OK, 95.0), "RESOLVED"),
    ((FAIL, None), (OK, 95.0), "FAILED"),
    ((OK, 90.0), (NA, None), "NOT_APPLICABLE"),
    ((OK, 90.0), (MISSING, None), "NOT_EVALUATED"),
])
def test_every_status_of_a_loading_criterion(reference, scenario, expected):
    assert status("loading", 100.0, reference, scenario) == expected


def test_values_on_the_limit_and_at_the_tolerance_edges():
    assert status("loading", 100.0, (OK, 100.0), (OK, 100.0)) == "OK", "on the limit is no violation"
    assert status("loading", 100.0, (OK, 100.0), (OK, 100.000001)) == "NEW"
    # Worsened tolerance 0.1 percentage points: exactly 0.1 more stays PRE-EXISTING, more is WORSENED.
    assert status("loading", 100.0, (OK, 105.0), (OK, 105.1)) == "PRE_EXISTING"
    assert status("loading", 100.0, (OK, 105.0), (OK, 105.2)) == "WORSENED"
    assert status("loading", 100.0, (OK, 105.2), (OK, 105.0)) == "IMPROVED"


def test_under_and_overvoltage_are_separate_criteria():
    assert dict(gl.criterion_thresholds("voltage", {"min": 0.95, "max": 1.05})) == {"voltage_low": 0.95, "voltage_high": 1.05}
    assert status("voltage_low", 0.95, (OK, 0.97), (OK, 0.93)) == "NEW"
    assert status("voltage_high", 1.05, (OK, 0.97), (OK, 0.93)) == "OK", "low voltage is no overvoltage"
    assert status("voltage_high", 1.05, (OK, 1.04), (OK, 1.07)) == "NEW"
    assert status("voltage_low", 0.95, (OK, 1.04), (OK, 1.07)) == "OK"
    outcome = gl.classify_criterion("voltage_low", 0.95, (OK, 0.94), (OK, 0.92))
    assert outcome["status"] == "WORSENED" and outcome["change"] == pytest.approx(0.02), "lower voltage is worse"


def test_quality_statuses_are_never_ok():
    assert status("loading", (100.0, 110.0), (OK, 90.0), (OK, 95.0)) == "NOT_COMPARABLE"
    assert status("loading", None, (OK, 90.0), (OK, 95.0)) == "NOT_EVALUATED"
    # Inside the recording limits: OK only when the recording limit proves it.
    assert status("loading", 100.0, (NR, None), (NR, None)) == "OK"
    assert status("loading", 70.0, (NR, None), (NR, None)) == "NOT_EVALUATED", "recording limit 80 % proves nothing for 70 %"
    assert status("loading", 100.0, (NR, None), (OK, 104.0)) == "NEW"
    for code in ("FAILED", "NOT_EVALUATED", "NOT_APPLICABLE", "NOT_COMPARABLE"):
        assert gl.CLASSIFICATION_CODES[code] >= 90


def test_reduced_margin_is_a_modifier_of_ok():
    outcome = gl.classify_criterion("loading", 100.0, (OK, 82.0), (OK, 95.0))
    assert outcome["status"] == "OK" and outcome["indicators"] == ["MARGIN_REDUCED"]


# ---------------------------------------------------------------------------
# Streaming aggregate with hand-built sources
# ---------------------------------------------------------------------------
LINE, OTHER, NODE = "TEST\\L1.ElmLne", "TEST\\L2.ElmLne", "TEST\\N1.ElmTerm"
C1, C2 = "TEST\\C1.ComOutage", "TEST\\C2.ComOutage"


def meta():
    return {"elements": {LINE: "L1", OTHER: "L2", NODE: "N1"},
            "categories": {LINE: "line", OTHER: "line", NODE: "voltage"},
            "nominal_kv": {NODE: 220.0}, "grids": {LINE: "TEST area", OTHER: "TEST area", NODE: "TEST area"},
            "contingencies": {C1: "C1", C2: "C2"}}


class Source:
    def __init__(self, steps):
        self.steps = steps
        self.times = sorted(steps)
        self.meta = meta()
        self.recording_limits = sg.RECORDING

    def read(self, moment):
        present, values = self.steps[moment]
        return set(present), dict(values), set()


def compare(reference, scenario, times, **options):
    return gl.compare_scenario("RUN", "TEST S01", reference, scenario, times, contingencies=[C1, C2], **options)


def total(statistics):
    return sum(statistics["events"].values())


def test_independent_maxima_are_never_a_coincident_change():
    times = [T0, T0 + H]
    # REF peaks at 110 at t0, the scenario at 112 at t1; at the same instant the scenario differs by +1 and +2.
    reference = Source({T0: ({C1, C2}, {(C1, LINE, "loading"): 110.0}), T0 + H: ({C1, C2}, {(C1, LINE, "loading"): 101.0})})
    scenario = Source({T0: ({C1, C2}, {(C1, LINE, "loading"): 111.0}), T0 + H: ({C1, C2}, {(C1, LINE, "loading"): 112.0})})
    statistics = compare(reference, scenario, times)
    worst = statistics["max_worsening"]["loading"]
    assert worst["change"] == pytest.approx(11.0) and worst["time"] == T0 + H, "the same-time pair 101 -> 112"
    assert worst["change"] != pytest.approx(2.0), "not the difference of the two independent maxima (112 - 110)"
    assert (worst["contingency"], worst["phase"], worst["element"], worst["run_id"]) == (C1, "post-fault", LINE, "RUN")
    assert statistics["max_violation"]["loading"]["violation"] == pytest.approx(12.0)


def test_switched_off_missing_and_not_applicable_cells_are_never_ok():
    times = [T0, T0 + H, T0 + 2 * H]
    reference = Source({T0: ({C1, C2}, {}), T0 + H: ({C1, C2}, {}), T0 + 2 * H: ({C1, C2}, {})})
    # The scenario switches L1 off; C1 outages L1, so C1 has no row (not applicable); C2 has no row at t1 (failed);
    # study time t2 is missing in the scenario.
    scenario = Source({T0: ({C2}, {}), T0 + H: (set(), {})})
    statistics = compare(reference, scenario, times, switched_off={LINE}, contingency_elements={C1: {LINE}, C2: {OTHER}})
    cells = 3  # L2 loading + N1 below and above the band; L1 is switched off and not monitored
    assert statistics["monitored"] == {"line": 1, "transformer": 0, "node": 1} and statistics["switched_off"] == 1
    events = statistics["events"]
    assert events["NOT_APPLICABLE"] == 2 * cells and events["FAILED"] == 1 * cells
    assert events["NOT_EVALUATED"] == 2 * cells, "missing study time: both contingencies"
    assert events["OK"] == 1 * cells, "only C2 at t0 was examined"
    assert total(statistics) == statistics["coverage"]["cells_required"] == 3 * 2 * cells
    assert statistics["coverage"]["times_missing"] == [T0 + 2 * H]
    assert statistics["coverage"]["cells_quality"]["NOT_APPLICABLE"] == 2 * cells
    counters = gl.element_counters(statistics, OTHER, "loading")
    assert counters["OK"] == 1 and counters["NOT_APPLICABLE"] == 2 and counters["FAILED"] == 1
    assert counters["NOT_EVALUATED"] == 2
    causes = {row["cause"] for row in statistics["quality"]}
    assert "study time not calculated in the (n-1)' scenario" in causes


def test_an_element_with_many_events_keeps_every_counter_and_counts_once_as_distinct():
    times = [T0 + index * H for index in range(4)]
    values = [104.0, 106.0, 106.05, 101.0]
    reference = Source({moment: ({C1, C2}, {(C1, LINE, "loading"): ref}) for moment, ref in zip(times, (95.0, 103.0, 106.0, 99.0))})
    scenario = Source({moment: ({C1, C2}, {(C1, LINE, "loading"): value, (C2, LINE, "loading"): 102.0})
                       for moment, value in zip(times, values)})
    statistics = compare(reference, scenario, times)
    counters = gl.element_counters(statistics, LINE, "loading")
    # C1: NEW at t0, WORSENED at t1, PRE-EXISTING at t2, NEW at t3; C2: NEW at every study time (REF unrecorded, proven).
    assert (counters["NEW"], counters["WORSENED"], counters["PRE_EXISTING"]) == (2 + 4, 1, 1)
    assert statistics["new_elements"]["line"] == 1 and statistics["worsened_elements"]["line"] == 1
    assert statistics["critical"]["line"] == 1, "one distinct element, however many events"
    assert statistics["critical_contingencies"] == 2 and statistics["critical_times"] == 4
    assert total(statistics) == statistics["coverage"]["cells_required"]


def test_episodes_follow_consecutive_examined_study_times_with_the_same_finding():
    times = [T0 + index * H for index in range(6)]
    loadings = [105.0, 106.0, 90.0, 104.0, 104.0, 104.0]
    reference = Source({moment: ({C1, C2}, {}) for moment in times})
    scenario = Source({moment: ({C1, C2}, {(C1, LINE, "loading"): value}) for moment, value in zip(times, loadings)})
    statistics = compare(reference, scenario, times)
    episodes = [(e["first"], e["last"], e["points"], e["status"]) for e in statistics["episode_list"]]
    assert episodes == [(times[0], times[1], 2, "NEW"), (times[3], times[5], 3, "NEW")], "a gap breaks an episode"
    peak = statistics["episode_list"][0]
    assert peak["peak"] == pytest.approx(6.0) and peak["peak_time"] == times[1]
    assert statistics["episodes"] == 2


def test_empty_register_errors_only_and_partial_coverage():
    times = [T0, T0 + H]
    quiet = Source({moment: ({C1, C2}, {}) for moment in times})
    empty = compare(quiet, Source({moment: ({C1, C2}, {}) for moment in times}), times)
    assert empty["events_top"] == [] and empty["episode_list"] == [] and empty["events"]["OK"] == total(empty)
    errors = compare(quiet, Source({}), times)
    assert errors["events"]["NOT_EVALUATED"] == total(errors) and errors["events"]["OK"] == 0
    assert errors["coverage"]["times_calculated"] == 0
    partial = compare(quiet, Source({T0: ({C1, C2}, {})}), times)
    assert partial["coverage"]["times_calculated"] == 1 and partial["coverage"]["times_missing"] == [T0 + H]
    assert total(partial) == partial["coverage"]["cells_required"]


def test_level_statistics_of_the_n1_reference_and_of_the_n0_qds():
    times = [T0, T0 + H]
    reference = Source({T0: ({C1, C2}, {(C1, LINE, "loading"): 108.0, (C2, NODE, "voltage"): 0.93}),
                        T0 + H: ({C1, C2}, {(C1, LINE, "loading"): 99.0})})
    level = gl.level_statistics("RUN", "n-1", reference)
    assert level["critical"] == {"line": 1, "transformer": 0, "node": 1}
    assert level["critical_contingencies"] == 2 and level["critical_times"] == 1
    assert level["max_violation"]["loading"]["violation"] == pytest.approx(8.0)
    assert level["max_violation"]["voltage_low"]["value"] == 0.93 and "voltage_high" not in level["max_violation"]
    import test_cases as tc
    n0 = gl.qds_level_statistics("RUN", tc._result("REF", "Reference"))
    assert n0["monitored"] == {"line": 4, "transformer": 1, "node": 1}
    assert n0["critical"] == {"line": 0, "transformer": 1, "node": 0}
    assert n0["max_violation"]["loading"]["violation"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Synthetic network profiles
# ---------------------------------------------------------------------------
def run_profile(grid, scenarios=None, **options):
    reference = grid.sweep()
    results = {}
    for name in scenarios if scenarios is not None else grid.scenarios:
        results[name] = gl.compare_scenario("TEST-RUN", name, reference, grid.sweep(name), grid.times,
                                            switched_off=grid.switched_off(name),
                                            contingency_elements=grid.contingency_elements,
                                            contingencies=grid.contingency_list, **options)
    return results


@pytest.mark.parametrize("count", [0, 1, 3, 6, 8])
def test_any_number_of_scenarios_is_assessed_without_a_six_case_limit(count):
    grid = sg.Grid(nodes=300, lines=200, transformers=20, contingencies=40, times=12, scenarios=count)
    results = run_profile(grid)
    assert len(results) == count
    for statistics in results.values():
        assert total(statistics) == statistics["coverage"]["cells_required"]
        assert statistics["coverage"]["pairs_not_applicable"] > 0, "the scenario's own outages are no contingency"


def test_the_same_run_gives_identical_statistics_for_main_and_detail_report():
    grid = sg.Grid(nodes=300, lines=200, transformers=20, contingencies=40, times=12, scenarios=2, long_names=True)
    assert run_profile(grid) == run_profile(grid)


def test_outage_windows_are_half_open_and_every_requested_study_time_is_accounted_for():
    grid = sg.Grid(nodes=200, lines=100, transformers=10, contingencies=20, times=10, scenarios=1)
    name = next(iter(grid.scenarios))
    line, start, end = grid.scenarios[name][0]
    assert line in grid.active(name, start) and line not in grid.active(name, end), "the window end is no longer active"
    dropped = grid.times[-1]
    statistics = gl.compare_scenario("TEST-RUN", name, grid.sweep(), grid.sweep(name, drop_times=[dropped]), grid.times,
                                     switched_off=grid.switched_off(name), contingency_elements=grid.contingency_elements,
                                     contingencies=grid.contingency_list)
    coverage = statistics["coverage"]
    assert (coverage["times_requested"], coverage["times_calculated"], coverage["times_missing"]) == (10, 9, [dropped])
    assert total(statistics) == coverage["cells_required"]


def test_the_minimum_test_profile_streams_without_a_dense_result_cube():
    grid = sg.Grid()  # 5,000 nodes, 3,400 lines, 210 transformers, 320 contingencies, 6 scenarios, 84 x 2 h
    assert (len(grid.nodes), len(grid.lines), len(grid.transformers), len(grid.contingency_list), len(grid.scenarios),
            len(grid.times)) == (5000, 3400, 210, 320, 6, 84)
    assert grid.times[1] - grid.times[0] == 2 * H
    tracemalloc.start()
    try:
        reference = grid.sweep()
        sweeps = {name: grid.sweep(name) for name in grid.scenarios}
        results = {name: gl.compare_scenario("TEST-RUN", name, reference, sweeps[name], grid.times,
                                             switched_off=grid.switched_off(name),
                                             contingency_elements=grid.contingency_elements,
                                             contingencies=grid.contingency_list)
                   for name in grid.scenarios}
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # A dense cube would be 84 x 320 x 13,610 cells per scenario; the streaming core stays far below that.
    assert peak < 300 * 1024 * 1024, "peak {:.0f} MB".format(peak / 2 ** 20)
    assert all(sweep.reads == len(grid.times) for sweep in sweeps.values()), "every study time is read exactly once"
    cells = 3400 + 210 + 2 * 5000
    for name, statistics in results.items():
        assert total(statistics) == statistics["coverage"]["cells_required"]
        assert statistics["coverage"]["cells_required"] == 84 * 320 * (cells - statistics["switched_off"])
        assert statistics["monitored"]["node"] == 5000 and statistics["events"]["NEW"] > 0
        assert len(statistics["events_top"]) <= 500 and statistics["events_listed"] >= len(statistics["events_top"])
        assert statistics["new_elements"]["line"] <= statistics["critical"]["line"] <= 3400


def test_weak_profile_keeps_violations_on_few_elements_and_over_consecutive_study_times():
    grid = sg.Grid(nodes=400, lines=300, transformers=20, contingencies=60, times=36, scenarios=1, weak=25)
    assert len(grid.loaded) == 25 and len(grid.weak_nodes) == 25
    name = sorted(grid.scenarios)[0]
    stats = gl.compare_scenario("RUN", name, grid.sweep(None), grid.sweep(name), grid.times, grid.switched_off(name),
                                grid.contingency_elements)
    critical = set(stats["element_status"])
    assert critical <= set(grid.loaded) | set(grid.weak_nodes)
    # Time-coherent: some episodes span several study times (the default stress profile is random per time).
    assert max(episode["points"] for episode in stats["episode_list"]) > 1
    assert sum(stats["events"].values()) == stats["coverage"]["cells_required"]
