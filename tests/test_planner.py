"""Time planner, case validation and the time-aligned comparison (tests A to E of the specification)."""

from __future__ import annotations

import calendar
import importlib.util
import json
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "powerfactory" / "gridlens_report.py"
SPEC = importlib.util.spec_from_file_location("gridlens_planner", SCRIPT)
gl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gl)

H = 3600.0
WEEK = 7 * 24 * H
YEAR_START = calendar.timegm((2026, 1, 1, 0, 0, 0))
PERIOD = (YEAR_START, YEAR_START + 52 * WEEK)


def kw(week):
    """Start of calendar week `week` in the test year, epoch seconds."""
    return YEAR_START + (week - 1) * WEEK


def record(name, start, end, components=None, ignored=False):
    return {"key": "Project\\Outages\\{}.IntPlannedout".format(name), "id": name, "name": name, "window": (start, end),
            "component_keys": list(components if components is not None else ["Project\\" + name + ".ElmLne"]),
            "equipment_name": name, "start_time": "", "end_time": "", "priority": 1, "originally_ignored": ignored,
            "status": gl.OUTAGE_CONSIDERED}


def config(cases, **extra):
    data = gl.empty_case_config("Project")
    data["cases"] = cases
    data.update(extra)
    return data


def case(identifier, *outages, **extra):
    return dict({"id": identifier, "name": "Case " + identifier, "outages": [item["key"] for item in outages]}, **extra)


def plans(request):
    return {plan["id"]: plan for plan in request["cases"]}


# ---------------------------------------------------------------------------
# Test A - coincident delta against the difference of the maxima
# ---------------------------------------------------------------------------
def _line(values_ref, values_case):
    item = {"category": "line", "key": "L", "element_name": "L", "limits": None}
    hours = [0.0, 1.0]
    labels = ["10:00", "11:00"]
    return gl.compare_element(item, gl.value_array(values_case), gl.value_array(values_ref), [0, 1],
                              gl.row_steps(hours), labels)


def test_a_coincident_delta_is_not_the_difference_of_the_maxima():
    record_a = _line([80.0, 60.0], [70.0, 85.0])

    assert record_a["maxima_difference"] == pytest.approx(5.0)
    assert record_a["coincident_delta"] == pytest.approx(25.0)
    assert record_a["coincident_time"] == "11:00"


# ---------------------------------------------------------------------------
# Test B - overlapping outages give a changing active set
# ---------------------------------------------------------------------------
def test_b_three_overlapping_outages_pass_through_five_states():
    windows = {"FS1": (8 * H, 13 * H), "FS2": (10 * H, 15 * H), "FS3": (11 * H, 14 * H)}

    states = [(start / H, end / H, sorted(active)) for start, end, active in gl.network_states(windows)]

    assert states == [(8, 10, ["FS1"]), (10, 11, ["FS1", "FS2"]), (11, 13, ["FS1", "FS2", "FS3"]),
                      (13, 14, ["FS2", "FS3"]), (14, 15, ["FS2"])]


@pytest.mark.parametrize("first, second, code, sequence", [
    ((0, 2), (3, 5), "T01", [["1"], [], ["2"]]),
    ((3, 5), (0, 2), "T02", [["2"], [], ["1"]]),
    ((0, 2), (2, 4), "T03", [["1"], ["2"]]),
    ((2, 4), (0, 2), "T04", [["2"], ["1"]]),
    ((0, 3), (2, 5), "T05", [["1"], ["1", "2"], ["2"]]),
    ((2, 5), (0, 3), "T06", [["2"], ["1", "2"], ["1"]]),
    ((0, 2), (0, 4), "T07", [["1", "2"], ["2"]]),
    ((0, 4), (0, 2), "T08", [["1", "2"], ["1"]]),
    ((1, 2), (0, 4), "T09", [["2"], ["1", "2"], ["2"]]),
    ((0, 4), (1, 2), "T10", [["1"], ["1", "2"], ["1"]]),
    ((2, 4), (0, 4), "T11", [["2"], ["1", "2"]]),
    ((0, 4), (2, 4), "T12", [["1"], ["1", "2"]]),
    ((0, 4), (0, 4), "T13", [["1", "2"]]),
])
def test_all_thirteen_interval_relations(first, second, code, sequence):
    assert gl.interval_relation(first, second) == code
    states = gl.network_states({"1": first, "2": second})
    assert [sorted(active) for _, _, active in states] == sequence


def test_v05_ten_sequential_outages_keep_their_order():
    windows = {"FS{:02d}".format(i): (i * 10 * H, (i * 10 + 5) * H) for i in range(10)}

    states = gl.network_states(windows)

    active = [sorted(state[2]) for state in states if state[2]]
    assert active == [["FS{:02d}".format(i)] for i in range(10)]


def test_v37_fifty_outages_in_one_case_are_not_limited():
    outages = [record("FS{:02d}".format(i), kw(10) + i * H, kw(10) + (i + 30) * H) for i in range(50)]

    request = gl.resolve_request(config([case("BIG", *outages)]), outages, PERIOD)

    plan = request["cases"][0]
    assert plan["status"] == gl.PLAN_READY
    assert len(plan["members"]) == 50
    assert max(len(active) for _, _, active in plan["states"]) == 30


# ---------------------------------------------------------------------------
# Test C - outages far apart: two windows proposed, nothing skipped unproven
# ---------------------------------------------------------------------------
def test_c_kw10_and_kw40_give_two_proposed_windows_but_run_conservatively():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(40), kw(41))
    request = gl.resolve_request(config([case("A", fs1, fs2)], mode="optimized"), [fs1, fs2], PERIOD)

    plan = request["cases"][0]
    assert len(plan["calc_windows"]) == 2
    assert plan["calc_windows"][0][0] == kw(10) - gl.WINDOW_WARMUP_HOURS * H
    summary = gl.optimization_summary(request, PERIOD)
    assert summary["executed"] is False and summary["admissible"] is False
    assert "2 window(s)" in summary["summary"]
    assert gl.qds_mode_text(dict(request, optimization=summary)).startswith("Conservative")


def test_close_windows_share_one_calculation_window():
    windows = [(kw(10), kw(10) + 10 * H), (kw(10) + 20 * H, kw(10) + 30 * H)]

    assert gl.calculation_windows(windows, warmup_hours=0, merge_gap_hours=48) == [(kw(10), kw(10) + 30 * H)]


def test_time_coupled_models_make_shorter_windows_inadmissible():
    class App:
        def GetCalcRelevantObjects(self, pattern):
            return [object()] if pattern == "*.ElmQdsl" else []

    fs1 = record("FS1", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1)], mode="optimized"), [fs1], PERIOD)

    summary = gl.optimization_summary(request, PERIOD, App())

    assert summary["time_coupled"] == ["1 ElmQdsl"]
    assert "time-coupled" in summary["reason"]


# ---------------------------------------------------------------------------
# Test D and E - alternatives are never combined, joint plans only on request
# ---------------------------------------------------------------------------
def test_d_alternative_dates_stay_separate_cases():
    fs1_kw10 = record("FS1 KW10", kw(10), kw(11), ["Project\\L100.ElmLne"])
    fs1_kw40 = record("FS1 KW40", kw(40), kw(41), ["Project\\L100.ElmLne"])
    records = gl.assign_definitions([fs1_kw10, fs1_kw40])
    request = gl.resolve_request(config([case("A", fs1_kw10), case("B", fs1_kw40)], exclusive_groups=[["A", "B"]]), records, PERIOD)

    assert [plan["id"] for plan in request["cases"]] == ["A", "B"]
    assert all(len(plan["members"]) == 1 for plan in request["cases"])
    assert fs1_kw10["definition_id"] == fs1_kw40["definition_id"], "two occurrences of one technical outage"


def test_d_alternatives_in_one_joint_case_are_refused():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(40), kw(41))
    request = gl.resolve_request(config([case("A", fs1), case("B", fs2), case("AB", includes=["A", "B"])],
                                        exclusive_groups=[["A", "B"]]), [fs1, fs2], PERIOD)

    joint = plans(request)["AB"]
    assert joint["status"] == gl.PLAN_NOT_EVALUATED
    assert "alternatives" in joint["reason"]


def test_e_a_joint_plan_calculates_both_outages_together():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1), case("B", fs2), case("AB", includes=["A", "B"])]), [fs1, fs2], PERIOD)

    joint = plans(request)["AB"]
    assert joint["status"] == gl.PLAN_READY
    assert [item["name"] for item in joint["members"]] == ["FS1", "FS2"]
    assert [sorted(active) for _, _, active in joint["states"]] == [[fs1["key"], fs2["key"]]]


def test_v09_the_same_outage_twice_in_one_case_is_two_real_executions():
    fs1_kw10 = record("FS1 KW10", kw(10), kw(11), ["Project\\L100.ElmLne"])
    fs1_kw40 = record("FS1 KW40", kw(40), kw(41), ["Project\\L100.ElmLne"])

    plan = gl.resolve_request(config([case("A", fs1_kw10, fs1_kw40)]), [fs1_kw10, fs1_kw40], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_READY
    assert [len(active) for _, _, active in plan["states"]] == [1, 0, 1]
    assert plan["relations"] == [("FS1 KW10", "FS1 KW40", "T01")]
    assert not plan["warnings"], "the same line at different times is no conflict"


def test_shared_outage_counts_once_in_a_joint_plan():
    fs1 = record("FS1", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1), case("B", fs1), case("AB", includes=["A", "B"])]), [fs1], PERIOD)

    assert len(plans(request)["AB"]["members"]) == 1


def test_no_combination_is_generated_automatically():
    outages = [record("FS{}".format(i), kw(10), kw(11)) for i in range(4)]
    request = gl.resolve_request(config([case("C{}".format(i), item) for i, item in enumerate(outages)]), outages, PERIOD)

    assert len(request["cases"]) == 4


# ---------------------------------------------------------------------------
# Case rules
# ---------------------------------------------------------------------------
def test_rules_not_overlap_order_and_together():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(10) + 24 * H, kw(12))
    fs3 = record("FS3", kw(20), kw(21))
    rules = [{"kind": "not_overlap", "first": fs1["key"], "second": fs2["key"]},
             {"kind": "order", "first": fs1["key"], "second": fs2["key"]},
             {"kind": "together", "first": fs1["key"], "second": fs3["key"]}]
    request = gl.resolve_request(config([case("X", fs1, fs2), case("Y", fs1)], rules=rules), [fs1, fs2, fs3], PERIOD)

    x, y = plans(request)["X"], plans(request)["Y"]
    assert x["status"] == gl.PLAN_NOT_EVALUATED
    assert "must not overlap" in x["reason"] and "only start after" in x["reason"]
    assert "together" in y["reason"]


def test_conditional_case_needs_its_precondition():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1), case("B", fs2, requires=["A"]),
                                         case("AB", includes=["A", "B"])]), [fs1, fs2], PERIOD)

    assert plans(request)["B"]["status"] == gl.PLAN_NOT_EVALUATED
    assert plans(request)["AB"]["status"] == gl.PLAN_READY


def test_including_cases_in_a_circle_is_refused():
    fs1 = record("FS1", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1, includes=["B"]), case("B", fs1, includes=["A"])]), [fs1], PERIOD)

    assert all("include each other" in plan["reason"] for plan in request["cases"])


def test_own_dates_are_refused_while_overrides_are_off():
    fs1 = record("FS1", kw(10), kw(11))
    data = config([case("B", fs1, overrides={fs1["key"]: [kw(40), kw(41)]})])

    plan = gl.resolve_request(data, [fs1], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_NOT_EVALUATED
    assert "ALLOW_OUTAGE_TIME_OVERRIDE" in plan["reason"]
    assert plan["windows"][fs1["key"]] == (kw(40), kw(41)), "the case documents its own dates"


def test_v13_two_outages_on_the_same_line_warn():
    fs1 = record("FS1", kw(10), kw(11), ["Project\\L100.ElmLne"])
    fs2 = record("FS2", kw(10) + 24 * H, kw(12), ["Project\\L100.ElmLne"])

    plan = gl.resolve_request(config([case("A", fs1, fs2)]), [fs1, fs2], PERIOD)["cases"][0]

    assert any("same equipment" in warning for warning in plan["warnings"])


def test_case_outside_the_simulated_period_is_not_simulated():
    fs1 = record("FS1", PERIOD[1] + WEEK, PERIOD[1] + 2 * WEEK)

    plan = gl.resolve_request(config([case("A", fs1)]), [fs1], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_NOT_SIMULATED


def test_f12_outage_starting_before_the_period_is_kept_with_a_warning():
    fs1 = record("FS1", PERIOD[0] - WEEK, PERIOD[0] + WEEK)

    plan = gl.resolve_request(config([case("A", fs1)]), [fs1], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_READY
    assert any("outside the simulated period" in warning for warning in plan["warnings"])


def test_v12_identical_cases_share_a_fingerprint_and_others_do_not():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1, fs2), case("B", fs2, fs1), case("C", fs1)]), [fs1, fs2], PERIOD)

    a, b, c = (plans(request)[name]["fingerprint"] for name in "ABC")
    assert a == b and a != c


def test_case_ids_must_be_short_unique_and_not_ref():
    assert gl.validate_case_config(config([{"id": "REF"}, {"id": "A"}, {"id": "A"}, {"id": "x" * 17}]))


def test_per_outage_request_reproduces_one_case_per_outage():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(60), kw(61))

    request = gl.per_outage_request([fs1, fs2], [fs1], PERIOD)

    assert [plan["id"] for plan in request["cases"]] == ["OUT01"]
    assert request["skipped"] == [fs2]


def test_preview_names_states_relations_and_runs():
    fs1 = record("FS1", kw(10), kw(10) + 5 * H)
    fs2 = record("FS2", kw(10) + 2 * H, kw(10) + 7 * H)
    request = gl.resolve_request(config([case("A", fs1, fs2), case("B", fs2, fs1)]), [fs1, fs2], PERIOD)

    text = gl.preview_text(request, PERIOD)

    assert "T05" in text and "network states" in text
    assert "identical cases calculated once: A/B" in text


# ---------------------------------------------------------------------------
# Saved configuration
# ---------------------------------------------------------------------------
def test_configuration_is_saved_with_a_revision_and_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "CASE_CONFIG_DIR", str(tmp_path))
    path = gl.case_config_path("Project\\Grid.IntPrj")
    data = config([{"id": "A", "name": "A", "outages": []}])

    gl.save_case_config(path, data, "operator")
    gl.save_case_config(path, data, "operator")

    stored = gl.load_case_config(path)
    assert stored["revision"] == 2 and stored["saved_by"] == "operator"
    assert path.startswith(str(tmp_path))


def test_damaged_configuration_is_reported_not_ignored(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"schema": "other"}), encoding="utf-8")

    with pytest.raises(gl.GridLensError, match="invalid"):
        gl.load_case_config(str(path))


def test_rules_typed_in_the_dialog_are_parsed_by_outage_name():
    fs1, fs2 = record("FS1", 0, 1), record("FS2", 0, 1)

    rules, problems = gl._parse_rules("not_overlap: FS1, FS2\nbogus\norder: FS1, FS9", [fs1, fs2])

    assert rules == [{"kind": "not_overlap", "first": fs1["key"], "second": fs2["key"]}]
    assert len(problems) == 2


# ---------------------------------------------------------------------------
# Per-step classification, durations, coverage
# ---------------------------------------------------------------------------
LINE = {"category": "line", "key": "L", "element_name": "L", "limits": None}
NODE = {"category": "voltage", "key": "N", "element_name": "N", "limits": (0.95, 1.05)}


@pytest.mark.parametrize("item, ref, value, status", [
    (LINE, 90.0, 101.0, gl.STATUS_NEW),
    (LINE, 101.0, 105.0, gl.STATUS_WORSENED),
    (LINE, 101.0, 101.05, gl.STATUS_PREEXISTING),
    (LINE, 105.0, 101.0, gl.STATUS_IMPROVED),
    (LINE, 105.0, 99.0, gl.STATUS_RESOLVED),
    (LINE, 90.0, 100.0, gl.STATUS_OK),
    (NODE, 1.0, 0.94, gl.STATUS_NEW),
    (NODE, 1.0, None, gl.STATUS_DEENERGIZED),
    (NODE, 1.0, 1.05, gl.STATUS_OK),
])
def test_every_time_step_is_classified(item, ref, value, status):
    assert gl.step_status(item, ref, value) == status


def test_violation_duration_weights_uneven_time_steps():
    hours = [0.0, 1.0, 1.25, 3.25]
    record_d = gl.compare_element(LINE, gl.value_array([101, 101, 101, 90]), gl.value_array([90, 90, 90, 90]), [0, 1, 2, 3],
                                  gl.row_steps(hours), ["a", "b", "c", "d"])

    assert record_d["caused_hours"] == pytest.approx(1.0 + 0.25 + 2.0)
    assert record_d["status"] == gl.STATUS_NEW


def test_windows_are_half_open():
    hours = [float(hour) for hour in range(6)]

    assert gl.window_rows(hours, [(1 * H, 3 * H)]) == [1, 2]


def test_v16_short_outage_between_time_steps_has_no_coverage():
    hours = [float(hour) for hour in range(6)]

    assert gl.window_rows(hours, [(1.25 * H, 1.75 * H)]) == []
    assert gl.window_coverage(hours, gl.row_steps(hours), [(1.25 * H, 1.75 * H)]) == 0.0


def test_coverage_of_a_window_partly_after_the_period():
    hours = [float(hour) for hour in range(6)]

    assert gl.window_coverage(hours, gl.row_steps(hours), [(4 * H, 8 * H)]) == pytest.approx(0.5)


def _case_pair(case_values, ref_values, node_case=None, node_ref=None):
    hours = [400000.0 + hour for hour in range(6)]
    labels = ["t{}".format(hour) for hour in range(6)]

    def result(identifier, line, node):
        items = []
        for category, name, values in (("line", "L", line), ("voltage", "N", node)):
            if values is None:
                continue
            item = {"category": category, "key": name, "element_name": name, "limits": (0.95, 1.05) if category == "voltage" else None,
                    "points": [(labels[i], float(i), value) for i, value in enumerate(values)], "unit": "%"}
            item["statistics"] = gl.statistics(item)
            item["values"] = gl.value_array(values)
            items.append(item)
        return gl.case_result({"id": identifier, "name": identifier, "hours": hours, "absolute": True}, items, labels,
                              [float(i) for i in range(6)], "h")

    reference = result("REF", ref_values, node_ref or [1.0] * 6)
    case_result = result("A", case_values, node_case or [1.0] * 6)
    return reference, case_result, hours


def test_effect_after_the_window_is_assessed_as_well():
    reference, case_result, hours = _case_pair([90, 90, 105, 90, 106, 90], [90] * 6)
    window = (hours[2] * H, hours[3] * H)  # only row 2

    gl.compare_case(case_result, reference, [window])

    assert case_result["assessment"]["window_rows"] == 1
    assert case_result["assessment"]["spill_rows"] == 1
    assert case_result["assessment"]["caused_hours"] == pytest.approx(2.0)


def test_v26_node_cut_off_by_the_case_is_reported_not_dropped():
    reference, case_result, hours = _case_pair([90] * 6, [90] * 6, node_case=[1.0, None, None, 1.0, 1.0, 1.0])

    gl.compare_case(case_result, reference, [(hours[1] * H, hours[3] * H)])
    judged = gl.assess_case([reference, case_result], case_result)

    assert judged["deenergized"] == 1
    assert judged["assessment"] == gl.ASSESSMENT_DEENERGIZED
    assert judged["violation"] == 2


def test_incomplete_coverage_is_never_reported_as_secure():
    reference, case_result, hours = _case_pair([90] * 6, [90] * 6)

    gl.compare_case(case_result, reference, [(hours[4] * H, (hours[5] + 4) * H)])
    judged = gl.assess_case([reference, case_result], case_result)

    assert judged["assessment"] == gl.ASSESSMENT_INCOMPLETE


def test_v38_case_without_rows_in_its_window_is_not_assessed():
    reference, case_result, hours = _case_pair([90] * 6, [90] * 6)

    gl.compare_case(case_result, reference, [((hours[5] + 10) * H, (hours[5] + 20) * H)])

    assert gl.assess_case([reference, case_result], case_result) is None


def test_v28_without_reference_violations_are_not_called_new():
    _, case_result, hours = _case_pair([90, 101, 90, 90, 90, 90], [90] * 6)

    gl.compare_case(case_result, None, [(hours[0] * H, hours[3] * H)])

    (line,) = case_result["comparison"]["line"]
    assert line["status"] == gl.STATUS_EXCEEDED
    assert line["coincident_delta"] is None


def test_v29_case_on_another_time_axis_is_not_compared():
    reference, case_result, hours = _case_pair([90] * 6, [90] * 6)
    case_result["labels"] = ["x{}".format(i) for i in range(6)]

    gl.compare_case(case_result, reference, [(hours[0] * H, hours[3] * H)])

    assert case_result["status"] == gl.AXIS_MISMATCH


def test_clock_change_keeps_every_time_label_unique(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        first = calendar.timegm((2026, 10, 25, 0, 30, 0)) / H
        labels = gl.unique_time_labels([first, first + 1.0])
    finally:
        monkeypatch.undo()
        time.tzset()

    assert len(set(labels)) == 2
    assert labels[0].endswith("+0200") and labels[1].endswith("+0100")


# ---------------------------------------------------------------------------
# Robustness against damaged or contradictory input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("change, message", [
    (lambda data: data.update(cases={"A": {}}), "cases must be a list"),
    (lambda data: data["cases"].append({"id": "A.1", "outages": []}), "not allowed"),
    (lambda data: data["cases"].append({"id": "B", "outages": "FS1"}), "outages must be a list"),
    (lambda data: data["cases"].append({"id": "C", "outages": [], "overrides": {"FS1": [5]}}), "own dates"),
    (lambda data: data["cases"].append({"id": "D", "outages": [], "overrides": {"FS1": [9, 5]}}), "own dates"),
    (lambda data: data.update(exclusive_groups=["A|B"]), "exclusive_groups"),
    (lambda data: data.update(rules=[{"kind": "order", "first": "FS1"}]), "needs a first and a second"),
    (lambda data: data.update(background="FS0"), "background"),
])
def test_damaged_configuration_is_named_before_anything_reads_it(change, message):
    data = config([])
    change(data)

    problems = gl.validate_case_config(data)

    assert any(message in problem for problem in problems), problems
    with pytest.raises(gl.GridLensError, match="cannot be used"):
        gl.resolve_request(data, [], PERIOD)


def test_window_that_ends_before_it_starts_is_refused():
    broken = record("FS1", kw(11), kw(10))

    plan = gl.resolve_request(config([case("A", broken)]), [broken], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_NOT_EVALUATED
    assert "ends before it starts" in plan["reason"]


def test_unknown_or_ignored_fixed_outages_are_warned_about():
    ignored = record("FS0", kw(10), kw(11), ignored=True)
    fs1 = record("FS1", kw(10), kw(11))

    request = gl.resolve_request(config([case("A", fs1)], background=[ignored["key"], "gone"]), [ignored, fs1], PERIOD)

    assert [item["name"] for item in request["background"]] == ["FS0"]
    assert len(request["warnings"]) == 2


@pytest.mark.parametrize("fraction, text", [(None, "n/a"), (0.0, "0 %"), (0.0004, "0.1 %"), (0.996, "99.6 %"),
                                            (0.9989, "99.9 %"), (0.9995, "100 %"), (1.0, "100 %")])
def test_coverage_text_never_says_complete_when_the_verdict_does_not(fraction, text):
    assert gl.percent_text(fraction) == text


def test_comparison_of_released_series_is_refused_with_a_clear_message():
    reference, case_result, hours = _case_pair([90] * 6, [90] * 6)
    gl.release_values(case_result)

    with pytest.raises(gl.GridLensError, match="already released"):
        gl.compare_case(case_result, reference, [(hours[0] * H, hours[2] * H)])


# ---------------------------------------------------------------------------
# Fast paths give the same results as the plain definitions
# ---------------------------------------------------------------------------
class _LongElmRes:
    """500 hourly rows: one line and one node that loses its voltage for a while."""

    def __init__(self, rows=500):
        import random
        rng = random.Random(7)
        self.rows = rows
        line = gl_obj("Line", "ElmLne")
        node = gl_obj("Bus", "ElmTerm")
        self.objects = (None, line, node)
        self.variables = ("b:tnow", "c:loading", "m:u")
        self.units = ("h", "%", "p.u.")
        loading = [round(rng.uniform(40, 120), 1) for _ in range(rows)]
        loading[10] = loading[20] = max(loading) + 1  # a tie: the first time counts
        voltage = [rng.uniform(0.9, 1.1) for _ in range(rows)]
        voltage[100:130] = [0.0] * 30
        self.columns = ([float(row) for row in range(rows)], loading, voltage)

    def GetNumberOfRows(self):
        return self.rows

    def GetNumberOfColumns(self):
        return len(self.columns)

    def GetVariable(self, column):
        return self.variables[column]

    def GetObject(self, column):
        return self.objects[column]

    def GetUnit(self, column):
        return self.units[column]

    def GetColumnValues(self, column):
        return self.columns[column]


def gl_obj(name, kind):
    class Obj:
        loc_name = name
        uknom = 110.0

        def GetClassName(self):
            return kind

        def GetFullName(self):
            return "P\\{}.{}".format(name, kind)
    return Obj()


def test_extraction_builds_only_the_plotted_points_and_keeps_the_exact_statistics():
    result = _LongElmRes()

    series, labels, plot_times, *_ = gl.collect_series(result)

    for item in series:
        values = [None if value == gl.MISSING else value for value in item["values"]]
        full = {"points": [(labels[row], plot_times[row], value) for row, value in enumerate(values)]}
        assert len(item["points"]) == gl.MAX_PLOT_POINTS
        assert item["points"] == gl.sampled_plot_points(full)
        assert item["statistics"] == gl.statistics(full)
        assert "p95" not in item["statistics"]
    line = next(item for item in series if item["category"] == "line")
    assert line["statistics"]["time_max"] == labels[10]


@pytest.mark.parametrize("values", [[1.0, 3.0, 3.0, None, 0.5, 0.5], [None, 2.0], [5.0], [None, None]])
def test_array_statistics_equal_the_point_statistics(values):
    labels = ["t{}".format(row) for row in range(len(values))]
    points = {"points": [(label, float(row), value) for row, (label, value) in enumerate(zip(labels, values))]}

    assert gl.array_statistics(gl.value_array(values), labels) == gl.statistics(points)


@pytest.mark.parametrize("item", [LINE, NODE, {"category": "voltage", "limits": (0.98, 1.02)}])
def test_excess_function_keeps_the_definition(item):
    measure = gl.excess_function(item)
    for value in (0.0, 0.5, 0.94, 0.95, 0.951, 1.0, 1.05, 1.0501, 1.2, 99.9, 100.0, 100.01, 150.0):
        if item["category"] == "line":
            expected = max(0.0, value - gl.LOADING_MAX)
        else:
            lower, upper = item["limits"]
            expected = max(0.0, lower - value, value - upper)
        assert measure(value) == pytest.approx(expected, abs=0)


def test_compare_element_agrees_with_step_status_at_every_step():
    import random
    rng = random.Random(3)
    for item, low, high in ((LINE, 80.0, 115.0), (NODE, 0.9, 1.1)):
        ref = [rng.uniform(low, high) for _ in range(300)]
        case_values = [value + rng.uniform(-5, 5) * (0.01 if item is NODE else 1) for value in ref]
        if item is NODE:
            case_values[50:60] = [None] * 10
        hours = [float(row) for row in range(300)]
        steps = gl.row_steps(hours)
        record_c = gl.compare_element(item, gl.value_array(case_values), gl.value_array(ref), range(300), steps,
                                      ["t{}".format(row) for row in range(300)])

        statuses = [gl.step_status(item, r, c) for r, c in zip(ref, case_values)]
        assert record_c["status"] == gl._worst_status([status for status in statuses if status])
        caused = sum(steps[row] for row, status in enumerate(statuses) if status in gl.CAUSED_STATUSES)
        violated = sum(steps[row] for row, value in enumerate(case_values) if value is not None and gl.excess(item, value) > 0)
        assert record_c["caused_hours"] == pytest.approx(caused)
        assert record_c["violation_hours"] == pytest.approx(violated)


# ---------------------------------------------------------------------------
# Case editor (the dialog's logic, without a window)
# ---------------------------------------------------------------------------
@pytest.fixture
def editor():
    outages = [record("FS1", kw(10), kw(11)), record("FS2", kw(10), kw(11)), record("FS3", kw(60), kw(61), ignored=True)]
    return gl.CaseEditor(outages, gl.empty_case_config(), PERIOD), outages


def test_editor_creates_copies_renames_and_deletes_cases(editor):
    edit, outages = editor

    assert edit.suggested_id() == "A"
    edit.add_case("A", "")
    edit.toggle_member("A", outages[0]["key"])
    edit.copy_case("A", "B")
    edit.rename_case("B", "  Variant  ")
    edit.delete_case("A")

    assert [(case["id"], case["name"], case["outages"]) for case in edit.config["cases"]] == [("B", "Variant", [outages[0]["key"]])]
    assert edit.id_problem("B") and edit.id_problem("REF") and edit.id_problem("A.1") and edit.id_problem("C") is None


def test_editor_never_changes_the_configuration_it_was_given(editor):
    _, outages = editor
    original = gl.empty_case_config()

    edit = gl.CaseEditor(outages, original, PERIOD)
    edit.add_case("A", "A")

    assert original["cases"] == []


def test_editor_assigns_fixes_and_shows_outages(editor):
    edit, outages = editor
    edit.add_case("A", "A")

    edit.toggle_member("A", outages[1]["key"])
    edit.toggle_fixed(outages[0]["key"])
    edit.toggle_member("A", "unknown key")
    rows = dict(edit.outage_rows("A"))

    assert rows[outages[1]["key"]][:2] == (gl.CHECKED, gl.UNCHECKED)
    assert rows[outages[0]["key"]][:2] == (gl.UNCHECKED, gl.CHECKED)
    assert rows[outages[2]["key"]][-1] == "Ignored in PowerFactory"
    assert edit.config["cases"][0]["outages"] == [outages[1]["key"]]


def test_editor_own_dates_are_checked_and_removable(editor):
    edit, outages = editor
    edit.add_case("A", "A")
    key = outages[0]["key"]

    assert edit.set_own_dates("A", key, "2026-10-01 00:00", "2026-10-02 00:00") == "Select an outage that belongs to the selected case."
    edit.toggle_member("A", key)
    assert edit.set_own_dates("A", key, "01.10.2026", "x") == "Use the format YYYY-MM-DD HH:MM."
    assert edit.set_own_dates("A", key, "2026-10-02 00:00", "2026-10-01 00:00") == "The end must lie after the start."
    assert edit.set_own_dates("A", key, "2026-10-01 00:00", "2026-10-02 00:00") is None
    assert dict(edit.outage_rows("A"))[key][4].endswith(" *")
    assert edit.set_own_dates("A", key, "", "") is None
    assert edit.config["cases"][0]["overrides"] == {}


def test_editor_request_settings_report_every_problem(editor):
    edit, outages = editor
    edit.add_case("A", "A")

    assert edit.set_request("order: FS1", "", "conservative")
    assert edit.set_request("not_overlap: FS1, FS2", "A|B", "optimized") == []
    assert edit.config["rules"] == [{"kind": "not_overlap", "first": outages[0]["key"], "second": outages[1]["key"]}]
    assert edit.exclusive_text() == "A|B" and edit.rules_text() == "not_overlap: FS1, FS2"
    assert edit.request()["mode"] == "optimized"


def test_editor_one_case_per_outage_leaves_out_ignored_outages(editor):
    edit, _ = editor

    edit.one_case_per_outage()

    assert [case["name"] for case in edit.config["cases"]] == ["FS1", "FS2"]
