"""Time planner, case validation and the time-aligned comparison (tests A to E of the specification)."""

from __future__ import annotations

import calendar
import importlib.util
import json
import time

import pytest


from _paths import delivered
SCRIPT = delivered("main.py")
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
# Test C - outages far apart: no time optimisation, the complete period runs
# ---------------------------------------------------------------------------
def test_c_kw10_and_kw40_run_over_the_complete_period_without_proposed_windows():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(40), kw(41))
    request = gl.resolve_request(config([case("A", fs1, fs2)], mode="optimized"), [fs1, fs2], PERIOD)

    plan = request["cases"][0]
    assert plan["status"] == gl.PLAN_READY and "calc_windows" not in plan
    assert "mode" not in request and "optimization" not in request
    assert gl.qds_mode_text(request).startswith("Complete ComStatsim period")
    assert "proposed" not in gl.preview_text(request, PERIOD)


def test_no_time_optimisation_remains_in_the_runtime():
    for name in ("QDS_WINDOW_MODE", "WINDOW_WARMUP_HOURS", "WINDOW_MERGE_GAP_HOURS", "calculation_windows",
                 "optimization_summary"):
        assert not hasattr(gl, name), name
    saved = gl.empty_case_config()
    assert "mode" not in saved


# ---------------------------------------------------------------------------
# Test D and E - alternatives are never combined, joint plans only on request
# ---------------------------------------------------------------------------
def test_d_alternative_dates_stay_separate_cases():
    fs1_kw10 = record("FS1 KW10", kw(10), kw(11), ["Project\\L100.ElmLne"])
    fs1_kw40 = record("FS1 KW40", kw(40), kw(41), ["Project\\L100.ElmLne"])
    records = gl.assign_definitions([fs1_kw10, fs1_kw40])
    request = gl.resolve_request(config([case("A", fs1_kw10), case("B", fs1_kw40)]), records, PERIOD)

    assert [plan["id"] for plan in request["cases"]] == ["A", "B"]
    assert all(len(plan["members"]) == 1 for plan in request["cases"])
    assert fs1_kw10["definition_id"] == fs1_kw40["definition_id"], "two occurrences of one technical outage"


def test_any_explicit_combination_is_allowed():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(40), kw(41))
    request = gl.resolve_request(config([case("A", fs1), case("B", fs2), case("AB", fs1, fs2)]), [fs1, fs2], PERIOD)

    assert all(plan["status"] == gl.PLAN_READY for plan in request["cases"])
    assert [item["name"] for item in plans(request)["AB"]["members"]] == ["FS1", "FS2"]


def test_e_a_joint_plan_calculates_both_outages_together():
    fs1 = record("FS1", kw(10), kw(11))
    fs2 = record("FS2", kw(10), kw(11))
    request = gl.resolve_request(config([case("A", fs1), case("B", fs2), case("AB", fs1, fs2)]), [fs1, fs2], PERIOD)

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
    request = gl.resolve_request(config([case("A", fs1), case("B", fs1), case("AB", fs1, fs1)]), [fs1], PERIOD)

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


def test_removed_relations_cannot_silently_affect_current_configurations():
    fs1 = record("FS1", kw(10), kw(11))
    for field in ("includes", "requires"):
        data = config([case("A", fs1, **{field: ["missing"]})])
        with pytest.raises(gl.GridLensError, match="case relations are no longer supported"):
            gl.resolve_request(data, [fs1], PERIOD)


def test_legacy_cycle_is_rejected_before_assignments_can_be_lost(tmp_path):
    fs1 = record("FS1", kw(10), kw(11))
    data = config([case("A", fs1, includes=["B"]), case("B", fs1, includes=["A"])], schema_version=1)
    path = tmp_path / "cases.json"
    original = json.dumps(data)
    path.write_text(original)

    with pytest.raises(gl.GridLensError, match="include each other"):
        gl.load_case_config(str(path))
    assert path.read_text() == original


def test_own_dates_are_refused_while_overrides_are_off():
    fs1 = record("FS1", kw(10), kw(11))
    data = config([case("B", fs1, overrides={fs1["key"]: [kw(40), kw(41)]})])

    plan = gl.resolve_request(data, [fs1], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_NOT_EVALUATED
    assert "ALLOW_OUTAGE_TIME_OVERRIDE" in plan["reason"]
    assert plan["windows"][fs1["key"]] == (kw(40), kw(41)), "the case documents its own dates"


def test_v13_overlapping_outages_are_normal_planning_not_a_warning():
    fs1 = record("FS1", kw(10), kw(11), ["Project\\L100.ElmLne"])
    fs2 = record("FS2", kw(10) + 24 * H, kw(12), ["Project\\L100.ElmLne"])
    fs3 = record("FS3", kw(10), kw(12), ["Project\\L200.ElmLne"])

    plan = gl.resolve_request(config([case("A", fs1, fs2, fs3)]), [fs1, fs2, fs3], PERIOD)["cases"][0]

    assert plan["status"] == gl.PLAN_READY and plan["warnings"] == []
    assert len(plan["relations"]) == 3, "the overlap is only recorded as a relation for the report"
    edit = gl.CaseEditor([fs1, fs2, fs3], config([case("A", fs1, fs2, fs3)]), PERIOD)
    assert edit.problem_rows() == []


def test_the_check_box_adds_and_removes_one_outage(editor):
    edit, outages = editor
    marks = lambda: {key: cells[0] for key, cells in edit.available_rows("B")}

    assert marks()[outages[0]["key"]] == gl.MARK_FREE
    assert edit.toggle_outage("B", outages[0]["key"]) is None
    assert marks()[outages[0]["key"]] == gl.MARK_IN_CASE
    assert edit.toggle_outage("B", outages[0]["key"]) is None
    assert marks()[outages[0]["key"]] == gl.MARK_FREE
    edit.set_fixed(outages[4]["key"], True)
    assert "fixed background outage" in edit.toggle_outage("B", outages[4]["key"])
    assert edit.toggle_outage(None, outages[0]["key"]) == "Select a planning case first."


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
    (lambda data: data.update(exclusive_groups=[["A", "B"]]), "alternatives are no longer supported"),
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

    def GetColumnValues(self, vector, column):
        vector.V = list(self.columns[column])
        return 0


@pytest.fixture(autouse=True)
def _column_buffer(monkeypatch):
    class IntVec:
        def GetClassName(self):
            return "IntVec"
    monkeypatch.setattr(gl, "COLUMN_BUFFER", IntVec())


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
# Case editor: every step of the case manager, without a window
# (gui_NN refers to the functional checks 1-20 of the GUI specification)
# ---------------------------------------------------------------------------
@pytest.fixture
def editor():
    outages = [record("FS1", kw(10), kw(11), ["Project\\L1.ElmLne"]), record("FS2", kw(10) + 2 * 24 * H, kw(12), ["Project\\L2.ElmLne"]),
               record("FS3", kw(40), kw(41), ["Project\\L3.ElmLne"]), record("FS4 Ignored", kw(20), kw(21), ignored=True),
               record("FS0 Background", kw(9), kw(13), ["Project\\L9.ElmLne"])]
    outages[2]["equipment_name"] = "Transformer T300"
    data = config([case("A", outages[0], outages[1]), case("B", outages[2])])
    return gl.CaseEditor(outages, data, PERIOD), outages


def members(edit, case_id):
    return [row[1][0] for row in edit.member_rows(case_id)]


def test_gui_01_to_03_each_case_shows_its_own_outages_and_switching_back_changes_nothing(editor):
    edit, _ = editor

    first = members(edit, "A")
    other = members(edit, "B")

    assert first == ["FS1", "FS2"] and other == ["FS3"]
    assert members(edit, "A") == first


def test_gui_04_and_06_adding_updates_the_case_and_an_outage_may_be_in_several_cases(editor):
    edit, outages = editor

    assert edit.add_outage("A", outages[2]["key"]) is None

    assert members(edit, "A") == ["FS1", "FS2", "FS3"]
    marks = dict((key, cells[0]) for key, cells in edit.available_rows("A"))
    assert marks[outages[2]["key"]] == gl.MARK_IN_CASE
    assert members(edit, "B") == ["FS3"]


def test_gui_no_duplicate_assignment_and_no_case_means_no_assignment(editor):
    edit, outages = editor

    assert edit.add_outage("A", outages[0]["key"]) == "FS1 is already part of Case A."
    assert edit.add_outage(None, outages[0]["key"]) == "Select a planning case first."
    assert edit.add_outage("A", "gone") == "This planned outage no longer exists in the project."
    assert members(edit, "A") == ["FS1", "FS2"]


def test_gui_05_and_09_removing_and_deleting_never_touch_the_planned_outages(editor):
    edit, outages = editor
    before = [dict(item) for item in outages]

    edit.remove_outage("A", outages[0]["key"])
    edit.delete_case("B")

    assert members(edit, "A") == ["FS2"]
    assert edit.case_ids() == ["A"]
    assert outages == before and len(edit.records) == 5
    assert [cells[1] for _, cells in edit.available_rows("A")] == ["FS1", "FS2", "FS3", "FS4 Ignored", "FS0 Background"]


def test_gui_07_copying_a_case_copies_its_assignments_and_stays_independent(editor):
    edit, outages = editor

    identifier, problem = edit.copy_case("A")
    edit.remove_outage(identifier, outages[0]["key"])

    assert (identifier, problem) == ("C1", None)
    assert members(edit, "C1") == ["FS2"]
    assert members(edit, "A") == ["FS1", "FS2"]
    assert edit.case("C1")["name"] == "Case A (copy)"


def test_gui_08_renaming_keeps_the_id_and_other_cases(editor):
    edit, _ = editor
    other = json.loads(json.dumps(edit.case("B")))

    edit.rename_case("A", "  Summer measures  ")

    assert edit.case("A")["name"] == "Summer measures"
    assert edit.case("A")["id"] == "A"
    assert edit.case("B") == other


def test_gui_deleting_a_case_keeps_shared_assignments_in_other_cases(editor):
    edit, _ = editor
    third, _ = edit.copy_case("A")
    other = json.loads(json.dumps(edit.case(third)))

    edit.delete_case("A")

    assert edit.case("A") is None
    assert edit.case(third) == other
    assert edit.case_statuses()[third] == "ready"
    assert gl.validate_case_config(edit.config) == []


def test_gui_10_fixed_outages_stay_apart_from_case_outages(editor):
    edit, outages = editor
    background = outages[4]["key"]

    assert edit.set_fixed(background, True) is None
    assert "fixed background outage" in edit.add_outage("A", background)
    assert "remove it from that case first" in edit.set_fixed(outages[0]["key"], True)
    assert edit.counts_text("A") == "2 case outages · 1 fixed background outage"
    assert dict(edit.summary()[0])["Reference"].startswith("Rfix")
    edit.set_fixed(background, False)
    assert dict(edit.summary()[0])["Reference"].startswith("R0")


def test_gui_11_and_12_search_and_filters_cope_with_many_outages(editor):
    _, outages = editor
    many = outages + [record("FS{:04d}".format(i), kw(10), kw(11), ["Project\\X{}.ElmLne".format(i)]) for i in range(5000)]
    edit = gl.CaseEditor(many, config([case("A", many[0])]), PERIOD)

    started = time.perf_counter()
    found = edit.available_rows("A", "transformer")
    elapsed = time.perf_counter() - started

    assert [cells[1] for _, cells in found] == ["FS3"]
    assert elapsed < 0.5
    assert [cells[1] for _, cells in edit.available_rows("A", "", gl.OUTAGE_FILTERS[3])] == ["FS4 Ignored"]
    assert outages[0]["key"] not in [key for key, _ in edit.available_rows("A", "", gl.OUTAGE_FILTERS[1])]


def test_gui_13_timeline_shows_overlaps_and_keeps_far_apart_outages_readable(editor):
    edit, outages = editor
    edit.add_outage("A", outages[2]["key"])

    items, overlaps = edit.timeline("A")
    position, breaks = gl.timeline_scale([(start, end) for _, start, end, _ in items], 600)

    assert [name for name, *_ in items] == ["FS1", "FS2", "FS3"]
    assert overlaps == [(kw(10) + 2 * 24 * H, kw(11))]
    assert len(breaks) == 1, "the 29 empty weeks between KW11 and KW40 are shortened"
    widths = [position(end) - position(start) for _, start, end, _ in items]
    assert min(widths) > 100, widths
    assert [round(position(moment)) for moment in (kw(10), kw(41))] == [0, 600]


def test_timeline_scale_is_monotonic_and_needs_a_window():
    position, _ = gl.timeline_scale([(0, 10), (1000, 1010)], 500)

    xs = [position(moment) for moment in (0, 5, 10, 500, 1000, 1005, 1010)]
    assert xs == sorted(xs) and xs[0] == 0 and round(xs[-1]) == 500
    assert gl.timeline_scale([(None, None)], 500) == (None, [])


def test_gui_14_and_16_n1_rules_and_no_time_optimisation_remains(editor):
    edit, _ = editor

    assert edit.set_assessments(False, False) == "Select at least one assessment."
    assert "always calculated" in edit.set_assessments(False, True)
    assert "needs n-1" in edit.set_assessments(True, False, True)
    assert edit.set_assessments(True, True, True) is None
    assert edit.config["assessments"] == ["n-0", "n-1", "(n-1)'"]
    assert not gl.validate_case_config(edit.config)
    assert edit.set_assessments(True, False) is None
    assert edit.config["assessments"] == ["n-0"] and "mode" not in edit.config
    optimised = gl.CaseEditor(edit.records, dict(edit.config, mode="optimized"), PERIOD)
    assert "mode" not in optimised.config
    assert not any("optimi" in (label + value).lower() or "window" in label.lower() for label, value in edit.summary()[0])


def test_gui_15_preview_names_the_comstatsim_period_and_the_runs(editor):
    edit, _ = editor

    values = dict(edit.summary()[0])

    assert values["QDS period"].startswith(gl.qds_period_text(PERIOD))
    assert values["Cases selected"] == "2 of 2: Case A, Case B"
    assert values["Valid cases"] == "2"
    assert values["Calculation runs"] == "1 reference + 2 case run(s)"
    assert values["Assessment"] == "n-0 quasi-dynamic simulation"


def test_gui_preview_lists_problems_instead_of_hiding_them(editor):
    edit, outages = editor
    edit.add_case("Empty")

    lines, problems = edit.summary()

    assert dict(lines)["Valid cases"] == "2"
    assert problems == ["Empty: Not calculated: no planned outage is assigned."]
    assert edit.problem_rows() == [("Empty", "Not calculated: no planned outage is assigned.")]


def test_gui_switched_off_cases_are_neither_calculated_nor_lost(editor):
    edit, _ = editor

    edit.set_enabled("B", False)
    request = edit.request()

    assert [plan["id"] for plan in request["cases"]] == ["A"] and request["disabled"] == ["B"]
    assert [row[0] for row in edit.case_rows()] == ["A", "B"]
    assert dict(edit.summary()[0])["Cases selected"] == "1 of 2: Case A"


def test_cases_can_freely_share_outages_without_affecting_each_other(editor):
    edit, outages = editor
    key = outages[0]["key"]
    assert edit.add_outage("B", key) is None
    before = json.loads(json.dumps(edit.case("B")))

    edit.remove_outage("A", key)
    edit.set_enabled("A", False)
    edit.delete_case("A")

    assert edit.case("B") == before
    assert key in edit.case("B")["outages"]
    assert edit.case_statuses()["B"] == "ready"


def test_gui_rules_between_outages_are_checked(editor):
    edit, outages = editor
    first, second = outages[0]["key"], outages[1]["key"]

    assert edit.add_rule("not_overlap", first, second) is None
    assert edit.add_rule("not_overlap", first, second) == "This rule exists already."
    assert edit.add_rule("order", first, first) == "A rule needs two different planned outages."
    assert edit.rule_rows() == [(0, ("FS1", "must not overlap", "FS2"))]
    assert "must not overlap" in edit.request()["cases"][0]["reason"]
    edit.remove_rule(0)
    assert edit.config["rules"] == []


def test_gui_own_dates_are_checked_and_removable(editor):
    edit, outages = editor
    key = outages[0]["key"]

    assert edit.set_own_dates("B", key, "2026-10-01 00:00", "2026-10-02 00:00") == "Select a planned outage that belongs to the selected case."
    assert edit.set_own_dates("A", key, "01.10.2026", "x") == "Use the format YYYY-MM-DD HH:MM."
    assert edit.set_own_dates("A", key, "2026-10-02 00:00", "2026-10-01 00:00") == "The end must lie after the start."
    assert edit.set_own_dates("A", key, "2026-10-01 00:00", "2026-10-02 00:00") is None
    assert dict(edit.member_rows("A"))[key][2].endswith(" *")
    assert edit.set_own_dates("A", key, "", "") is None and edit.case("A")["overrides"] == {}


def test_gui_ids_are_generated_and_the_engineer_only_names_cases(editor):
    edit, outages = editor

    assert edit.next_case_id() == "C1"
    first, _ = edit.add_case("")
    second, _ = edit.add_case("  Winter  ")
    edit.delete_case(first)

    assert (first, second) == ("C1", "C2")
    assert edit.case(second)["name"] == "Winter"
    assert edit.next_case_id() == "C1", "a freed number is used again"
    assert dict(edit.details(outages[0]["key"]))["Used in cases"] == "Case A"


def test_gui_at_most_five_cases(editor):
    edit, _ = editor
    created = [edit.add_case("Extra {}".format(number)) for number in range(3)]

    assert [problem for _, problem in created] == [None, None, None]
    assert len(edit.case_ids()) == gl.MAX_CASES == 5
    assert edit.add_case("Sixth") == (None, edit.limit_problem())
    assert edit.copy_case("A") == (None, edit.limit_problem())
    assert "At most 5 planning cases" in edit.limit_problem()
    assert len(edit.case_ids()) == 5


def test_gui_one_case_per_outage_stops_at_five(editor):
    edit, outages = editor
    edit.set_fixed(outages[4]["key"], True)

    assert edit.one_case_per_outage() is None
    assert [row[2] for row in edit.case_rows()] == ["FS1", "FS2", "FS3"], "ignored and fixed outages get no case"
    many = outages + [record("FS{:02d}".format(i), kw(10), kw(11), ["Project\\Y{}.ElmLne".format(i)]) for i in range(6)]
    crowded = gl.CaseEditor(many, config([]), PERIOD)
    assert crowded.one_case_per_outage() == "Only the first 5 of 10 planned outages got a case (at most 5 cases)."
    assert crowded.case_ids() == ["C1", "C2", "C3", "C4", "C5"]


def test_the_upgrade_note_is_shown_until_the_cases_are_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "CASE_CONFIG_DIR", str(tmp_path))
    fs1, fs2 = record("FS1", kw(10), kw(11)), record("FS2", kw(12), kw(13))
    old = config([case("A", fs1), case("B", fs2, includes=["A"])], schema_version=1, exclusive_groups=[])
    legacy = gl.legacy_case_config_path("Project")
    with open(legacy, "w", encoding="utf-8") as handle:
        json.dump(old, handle)
    path = gl.case_config_path("Project")

    edit = gl.CaseEditor([fs1, fs2], gl.load_case_config(path), PERIOD)
    assert any(where == "configuration" for where, _ in edit.problem_rows()), "the note is shown once"
    gl.save_case_config(path, edit.config, "operator")

    assert "migration_note" not in edit.config
    stored = json.loads(open(path, encoding="utf-8").read())
    assert "migration_note" not in stored and stored["schema_version"] == 2
    again = gl.CaseEditor([fs1, fs2], gl.load_case_config(path), PERIOD)
    assert again.problem_rows() == [] and again.case("B")["outages"] == [fs2["key"], fs1["key"]]


def test_this_version_never_overwrites_the_file_of_the_delivered_script(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "CASE_CONFIG_DIR", str(tmp_path))
    legacy, path = gl.legacy_case_config_path("Project\\Grid.IntPrj"), gl.case_config_path("Project\\Grid.IntPrj")
    assert path.endswith(".v2.json") and path != legacy and path[:-len(".v2.json")] == legacy[:-len(".json")]
    old = config([case("A")], schema_version=1, exclusive_groups=[])
    with open(legacy, "w", encoding="utf-8") as handle:
        json.dump(old, handle)
    before = open(legacy, encoding="utf-8").read()

    loaded = gl.load_case_config(path)  # nothing saved by this version yet: read the 8.0 file
    assert loaded["schema_version"] == 2 and loaded["cases"][0]["id"] == "A"
    gl.save_case_config(path, loaded, "operator")

    assert open(legacy, encoding="utf-8").read() == before, "the schema-1 file stays for the delivered script"
    assert gl.load_case_config(path)["revision"] == 1


def test_outage_choices_are_built_once(editor):
    edit, _ = editor
    assert edit.outage_choices() is edit.outage_choices()


def test_the_window_fits_the_screen_and_opens_centred():
    assert gl.window_geometry(1920, 1080) == "1480x860+220+90"
    assert gl.window_geometry(1366, 768) == "1174x660+96+34"
    assert gl.window_geometry(1024, 600) == "900x600+62+0"
    for width, height in ((1920, 1080), (1366, 768), (1024, 600), (800, 500)):
        size, x, y = gl.window_geometry(width, height).split("+")
        w, h = (int(part) for part in size.split("x"))
        assert w <= width and h <= height and int(x) + w <= width and int(y) + h <= height
        assert gl.minimum_window_size(width, height) <= (width, height)


def test_one_case_per_outage_takes_only_outages_in_the_simulated_period():
    outside = record("FS Next year", PERIOD[1] + WEEK, PERIOD[1] + 2 * WEEK)
    inside = [record("FS{}".format(i), kw(10), kw(11), ["Project\\W{}.ElmLne".format(i)]) for i in range(5)]
    edit = gl.CaseEditor([outside] + inside, config([]), PERIOD)

    assert edit.one_case_per_outage() is None
    assert [row[2] for row in edit.case_rows()] == ["FS0", "FS1", "FS2", "FS3", "FS4"]


def test_copy_keeps_own_dates_independent(editor):
    edit, outages = editor
    key = outages[0]["key"]
    edit.case("A")["overrides"] = {key: [kw(10), kw(11)]}
    copy, _ = edit.copy_case("A")
    edit.case(copy)["overrides"][key][0] = kw(9)

    assert edit.case("A")["overrides"][key] == [kw(10), kw(11)]
    assert edit.case(copy)["overrides"][key][0] == kw(9)
    assert "includes" not in edit.case(copy) and "requires" not in edit.case(copy)


def test_legacy_cases_are_flattened_once_and_then_stay_independent(tmp_path):
    fs1, fs2 = record("FS1", kw(10), kw(11)), record("FS2", kw(10), kw(11))
    data = config([case("A", fs1, overrides={fs1["key"]: [kw(20), kw(21)]}),
                   case("B", fs2, includes=["A"], requires=["A"]),
                   case("C", includes=["B", "A"])], schema_version=1, exclusive_groups=[["A", "B"]])
    path = tmp_path / "cases.json"
    original = json.dumps(data)
    path.write_text(original)

    loaded = gl.load_case_config(str(path))
    assert path.read_text() == original, "loading or cancelling must not rewrite the saved configuration"
    assert loaded["schema_version"] == 2 and "exclusive_groups" not in loaded
    assert all("includes" not in item and "requires" not in item for item in loaded["cases"])
    assert loaded["cases"][1]["outages"] == [fs2["key"], fs1["key"]]
    assert loaded["cases"][2]["outages"] == [fs2["key"], fs1["key"]]
    assert loaded["cases"][2]["overrides"] == {fs1["key"]: [kw(20), kw(21)]}
    edit = gl.CaseEditor([fs1, fs2], loaded, PERIOD)
    assert any("independent" in text for _, text in edit.problem_rows())
    edit.delete_case("A")
    edit.remove_outage("B", fs1["key"])
    assert edit.case("C")["outages"] == [fs2["key"], fs1["key"]]
    assert edit.case("B").get("enabled", True) is True
    gl.save_case_config(str(path), edit.config)
    assert gl.load_case_config(str(path)) == json.loads(path.read_text())


def test_rule_choices_keep_outages_with_the_same_name_apart():
    first = record("FS Line", kw(10), kw(11), ["Project\\A.ElmLne"])
    second = dict(record("FS Line", kw(12), kw(13), ["Project\\B.ElmLne"]), key="Project\\Other\\FS Line.IntPlannedout")
    edit = gl.CaseEditor([first, second], config([]), PERIOD)
    choices = dict(edit.outage_choices())

    assert len(choices) == 2 and set(choices.values()) == {first["key"], second["key"]}
    label = next(label for label, key in choices.items() if key == second["key"])
    assert edit.add_rule("not_overlap", choices[label], first["key"]) is None
    assert edit.config["rules"] == [{"kind": "not_overlap", "first": second["key"], "second": first["key"]}]
    assert edit.rule_rows()[0][1][0] == label


def test_statuses_problems_and_preview_share_one_resolution(editor, monkeypatch):
    edit, outages = editor
    calls = []
    original = gl.resolve_request
    monkeypatch.setattr(gl, "resolve_request", lambda *args, **kw: calls.append(1) or original(*args, **kw))

    edit.case_statuses(), edit.problem_rows(), edit.summary(), edit.case_statuses()
    assert len(calls) == 1
    edit.remove_outage("A", outages[0]["key"])
    edit.case_statuses()
    assert len(calls) == 2, "a change resolves again"


def test_calculation_preview_lists_effective_settings_and_keeps_blocked_cases_out(editor):
    edit, outages = editor
    edit.set_fixed(outages[4]['key'], True)
    clone, _ = edit.copy_case('A')
    empty, _ = edit.add_case('Empty')
    preview = edit.calculation_preview()
    assert 'Reference: Rfix' in preview
    assert 'Shared background: FS0 Background' in preview
    assert 'reuse result from A' in preview
    assert 'n-0; complete QDS period' in preview
    assert 'FS1: ' + gl._format_pf_time(outages[0]['window'][0]) in preview
    assert 'Not calculated: Empty' in preview
    assert 'Empty ({})'.format(empty) not in preview
    edit.set_enabled('A', False)
    preview = edit.calculation_preview()
    assert 'Case A (A)' not in preview
    assert 'reuse result from A' not in preview
    assert 'Case A (copy) ({})'.format(clone) in preview


def test_more_than_five_cases_are_refused_where_engineers_define_them():
    outages = [record("FS{}".format(i), kw(10), kw(11), ["Project\\Z{}.ElmLne".format(i)]) for i in range(6)]
    data = config([case("K{}".format(i), item) for i, item in enumerate(outages)])

    assert "at most 5 planning cases" in " ".join(gl.validate_case_config(data))
    with pytest.raises(gl.GridLensError, match="at most 5 planning cases"):
        gl.resolve_request(data, outages, PERIOD, "saved")
    assert len(gl.resolve_request(data, outages, PERIOD, "per_outage")["cases"]) == 6, "the window-less mode keeps every outage"


def test_a_saved_file_with_too_many_cases_still_opens_so_cases_can_be_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "CASE_CONFIG_DIR", str(tmp_path))
    outages = [record("FS{}".format(i), kw(10), kw(11), ["Project\\Z{}.ElmLne".format(i)]) for i in range(6)]
    data = config([case("K{}".format(i), item) for i, item in enumerate(outages)])
    data["cases"][5]["enabled"] = False
    path = str(tmp_path / "old.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)  # as GridLens 8.0 saved it, without a case limit

    loaded = gl.load_case_config(path)
    edit = gl.CaseEditor(outages, loaded, PERIOD)
    statuses = edit.case_statuses()
    assert statuses["K5"] == "excluded" and statuses["K0"] == "not calculated"
    assert "at most 5 planning cases" in " ".join(problem for _, problem in edit.problem_rows())
    with pytest.raises(gl.GridLensError, match="at most 5 planning cases"):
        gl.save_case_config(path, loaded, "operator")
    edit.delete_case("K5")
    assert set(edit.case_statuses().values()) == {"ready"}, "after deleting one the configuration works again"


def test_gui_20_saved_assignments_come_back_unchanged(editor, tmp_path):
    edit, outages = editor
    edit.add_outage("B", outages[0]["key"])
    edit.set_enabled("A", False)
    path = str(tmp_path / "cases.json")

    gl.save_case_config(path, edit.config, "operator")
    again = gl.CaseEditor(outages, gl.load_case_config(path), PERIOD)

    assert members(again, "A") == ["FS1", "FS2"] and members(again, "B") == ["FS3", "FS1"]
    assert again.case("A")["enabled"] is False and again.config["assessments"] == ["n-0"]


def test_gui_the_editor_never_changes_the_configuration_it_was_given(editor):
    _, outages = editor
    original = gl.empty_case_config()

    edit = gl.CaseEditor(outages, original, PERIOD)
    edit.add_case("A")

    assert original["cases"] == []


@pytest.mark.parametrize("change, message", [
    (lambda data: data.update(assessments=[]), "assessments must name"),
    (lambda data: data.update(assessments=["n-2"]), "assessments must name"),
    (lambda data: data.update(assessments=["n-1"]), "n-0 quasi-dynamic assessment is always calculated"),
    (lambda data: data.update(assessments=["n-0", "(n-1)'"]), "needs n-1"),
    (lambda data: data["cases"].append({"id": "E", "outages": [], "enabled": "yes"}), "enabled must be"),
])
def test_assessments_and_enabled_flags_are_validated(change, message):
    data = config([])
    change(data)

    assert any(message in problem for problem in gl.validate_case_config(data))


# ---------------------------------------------------------------------------
# Table filters, sorting and column widths of the case manager
# ---------------------------------------------------------------------------
ROWS = [("a", ("FS Bedarf 1", "NE_L1", 2, "in case")), ("b", ("FS Bedarf 2", "NE_L2", 10, "")),
        ("c", ("FS Nord", "Transformer T3", 1, "fixed"))]


@pytest.mark.parametrize("filters, keys", [
    ({}, ["a", "b", "c"]),
    ({0: ("contains", "bedarf")}, ["a", "b"]),
    ({1: ("contains", "t3")}, ["c"]),
    ({0: ("contains", "bedarf"), 1: ("contains", "l2")}, ["b"]),
    ({3: ("equals", "")}, ["b"]),
    ({3: ("equals", "fixed")}, ["c"]),
    ({2: ("contains", "1")}, ["b", "c"]),  # numbers filter as text: "1" is in 10 and 1
])
def test_filter_rows_matches_every_column_filter(filters, keys):
    assert [key for key, _ in gl.filter_rows(ROWS, filters)] == keys


def test_filter_rows_never_changes_the_rows():
    before = list(ROWS)
    gl.filter_rows(ROWS, {0: ("contains", "x")})
    assert ROWS == before


def test_sort_rows_orders_numbers_by_value_and_text_alphabetically():
    assert [key for key, _ in gl.sort_rows(ROWS, 2)] == ["c", "a", "b"]
    assert [key for key, _ in gl.sort_rows(ROWS, 2, descending=True)] == ["b", "a", "c"]
    assert [key for key, _ in gl.sort_rows(ROWS, 1)] == ["a", "b", "c"]
    assert [key for key, _ in gl.sort_rows(ROWS, 3)] == ["b", "c", "a"], "empty first, then alphabetical"


@pytest.mark.parametrize("width", [200, 400, 532, 800, 1200])
def test_column_widths_fill_the_table_and_keep_flexible_columns_readable(width):
    columns = [(66, False), (140, True), (110, True), (106, False), (106, False), (132, False)]

    widths = gl.column_widths(columns, width)

    assert sum(widths) == width
    if width >= 410 + 0.6 * 250:
        assert widths[0] == 66 and widths[3] == 106, "fixed columns keep their width while there is room"
        assert widths[1] >= 0.6 * 140 - 1
    else:
        assert widths[1] / 140.0 == pytest.approx(widths[0] / 66.0 * 0.6, rel=0.1), "everything shrinks in proportion"


@pytest.mark.parametrize("changes", [
    {"includes": "A"}, {"requires": [None]}, {"includes": ["missing"]},
])
def test_invalid_legacy_references_are_reported_without_rewriting_the_file(tmp_path, changes):
    data = config([case("A", **changes)], schema_version=1)
    path = tmp_path / "cases.json"
    original = json.dumps(data)
    path.write_text(original)
    with pytest.raises(gl.GridLensError, match="cannot be upgraded"):
        gl.load_case_config(str(path))
    assert path.read_text() == original


def test_migration_preserves_parent_first_dates_and_explicit_disabled_cases():
    fs1 = record("FS1", kw(10), kw(11))
    data = config([case("A", fs1, includes=["B"], overrides={fs1["key"]: [kw(20), kw(21)]}),
                   case("B", fs1, enabled=False, overrides={fs1["key"]: [kw(30), kw(31)]})], schema_version=1)
    upgraded = gl.upgrade_case_config(data)
    assert upgraded["cases"][0]["outages"] == [fs1["key"]]
    assert upgraded["cases"][0]["overrides"][fs1["key"]] == [kw(20), kw(21)]
    assert upgraded["cases"][1]["enabled"] is False
    assert data["schema_version"] == 1 and data["cases"][0]["includes"] == ["B"]


def test_plain_legacy_configuration_opens_without_a_migration_warning():
    data = config([case("A", includes=[], requires=[])], schema_version=1, exclusive_groups=[])
    upgraded = gl.upgrade_case_config(data)
    assert gl.validate_case_config(upgraded) == []
    assert "migration_note" not in upgraded
