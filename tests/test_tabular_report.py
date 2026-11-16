"""The tabular report: location of every element, n-0 violation episodes and the case summary.

Synthetic data only; no PowerFactory.
"""

from __future__ import annotations

import importlib.util

import pytest

from _paths import delivered

SPEC = importlib.util.spec_from_file_location("outage_assessment_tabular", delivered("main.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)


@pytest.fixture(autouse=True)
def _defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


class Obj:
    def __init__(self, name, kind, path=None, **attributes):
        self.loc_name, self._kind = name, kind
        self._path = path or "\\P\\{}.{}".format(name, kind)
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self._kind

    def GetFullName(self):
        return self._path


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def test_element_location_names_grid_and_station():
    grid = Obj("D7", "ElmNet")
    transformer = Obj("TR1", "ElmTr2", "\\P\\D7.ElmNet\\UW Nord.ElmSubstat\\TR1.ElmTr2", cpGrid=grid)
    assert gl.element_location(transformer) == "D7 / UW Nord"
    line = Obj("L1", "ElmLne", "\\P\\D7.ElmNet\\L1.ElmLne", cpGrid=grid)
    assert gl.element_location(line) == "D7"
    assert gl.element_location(Obj("X", "ElmLne", "\\P\\X.ElmLne")) == "-"
    station = Obj("TR2", "ElmTr2", "\\P\\D7.ElmNet\\Site.ElmSite\\Ost.ElmTrfstat\\TR2.ElmTr2")
    assert gl.element_location(station) == "D7 / Ost", "the nearest station; the grid from the path"
    # A variant element lies in an expansion stage, without a station in its path: cpSubstat names it.
    variant = Obj("TR3", "ElmTr2", "\\P\\Stage.IntSstage\\TR3.ElmTr2", cpGrid=grid, cpSubstat=Obj("UW Süd", "ElmSubstat"))
    assert gl.element_location(variant) == "D7 / UW Süd"


# ---------------------------------------------------------------------------
# Violation episodes (n-0)
# ---------------------------------------------------------------------------
START_HOUR = 1388530800.0 / 3600.0  # 2014-01-01 00:00 local in the acceptance project


def _result(case_id, series, absolute=True, steps=None):
    """A converged result; series are (category, name, values) with one value per hourly step (None: no value)."""
    count = len(series[0][2])
    hours = [START_HOUR + row for row in range(count)] if absolute else [float(row) for row in range(count)]
    labels = gl.unique_time_labels(hours) if absolute else [gl.format_clock(value) for value in hours]
    items = []
    for category, name, values in series:
        item = {"category": category, "key": "\\P\\" + name, "element_id": name, "element_name": name,
                "location": "D7 / UW " + name, "voltage_level": "110 kV", "nominal_kv": 110.0,
                "unit": "p.u." if category == "voltage" else "%", "variable": "Loading",
                "limits": (0.95, 1.05) if category == "voltage" else None,
                "points": [(labels[row], float(row), value) for row, value in enumerate(values)]}
        item["statistics"] = gl.statistics(item)
        item["values"] = gl.value_array(values)
        items.append(item)
    return gl.case_result({"id": case_id, "name": "Case " + case_id if case_id != "REF" else "Reference",
                           "hours": hours, "absolute": absolute}, items, labels, [h - hours[0] for h in hours], "h")


def _compared(reference_series, case_series, absolute=True):
    reference = _result("REF", reference_series, absolute)
    case = _result("C1", case_series, absolute)
    window = (reference["hours"][0] * 3600.0, (reference["hours"][-1] + 1) * 3600.0) if absolute else (None, None)
    gl.reference_episodes(reference)
    gl.compare_case(case, reference, [window])
    return reference, case


def _rows(results, request=None):
    payload = gl.empty_payload()
    gl._n0_episodes(payload, results)
    return payload["ScriptedEpisodes"]


def test_episodes_have_start_end_duration_peak_and_the_reference_at_the_peak():
    reference, case = _compared([("line", "L1", [50.0, 60.0, 90.0, 95.0, 90.0, 60.0])],
                                [("line", "L1", [50.0, 60.0, 101.0, 112.4, 104.0, 60.0])])
    rows = _rows([reference, case])
    assert [row["row_kind"] for row in rows] == ["case", "episode"], "REF has no violation: no REF section"
    header, episode = rows
    assert header["case_name"] == "C1 · Case C1" and header["element_name"] == ""
    assert (episode["start_text"], episode["end_text"], episode["duration_text"]) == (
        "2014-01-01 02:00", "2014-01-01 05:00", "3.00 h")
    assert (episode["peak_text"], episode["peak_time"]) == ("112.4 %", "2014-01-01 03:00")
    assert (episode["reference_text"], episode["delta_text"]) == ("95.0 %", "+17.4 pp")
    assert (episode["criterion"], episode["status"], episode["violation"]) == ("loading", "NEW", 1)
    assert (episode["element_name"], episode["location_text"], episode["element_type"]) == ("L1", "D7 / UW L1", "Line")


def test_a_missing_value_ends_an_episode():
    reference, case = _compared([("line", "L1", [50.0] * 6)], [("line", "L1", [101.0, 102.0, None, 103.0, 50.0, 50.0])])
    episodes = [row for row in _rows([reference, case]) if row["row_kind"] == "episode"]
    assert [(row["start_text"][-5:], row["end_text"][-5:]) for row in episodes] == [("00:00", "02:00"), ("03:00", "04:00")]


def test_an_episode_at_the_end_of_the_axis_ends_one_step_later():
    reference, case = _compared([("line", "L1", [50.0] * 3)], [("line", "L1", [50.0, 101.0, 102.0])])
    episode = _rows([reference, case])[1]
    assert (episode["start_text"], episode["end_text"], episode["duration_text"]) == (
        "2014-01-01 01:00", "2014-01-01 03:00", "2.00 h")


def test_reference_episodes_come_first_and_have_no_delta():
    reference, case = _compared([("transformer", "TR1", [99.0, 104.0, 104.0, 99.0])],
                                [("transformer", "TR1", [99.0, 104.0, 104.0, 99.0])])
    rows = _rows([reference, case])
    assert [(row["case_order"], row["row_kind"]) for row in rows] == [(0, "case"), (0, "episode"), (1, "case"), (1, "episode")]
    ref_episode, case_episode = rows[1], rows[3]
    assert rows[0]["case_name"] == "REF · Reference"
    assert (ref_episode["status"], ref_episode["reference_text"], ref_episode["delta_text"], ref_episode["violation"]) == (
        "EXCEEDED", "", "", 2)
    assert (case_episode["status"], case_episode["violation"]) == ("PRE-EXISTING", 2)


def test_voltage_low_and_high_are_separate_episodes_with_their_own_peak():
    reference, case = _compared([("voltage", "Bus", [1.0] * 4)], [("voltage", "Bus", [0.93, 0.92, 1.07, 1.0])])
    episodes = [row for row in _rows([reference, case]) if row["row_kind"] == "episode"]
    assert [(row["criterion"], row["peak_text"], row["delta_text"]) for row in episodes] == [
        ("voltage low", "0.920 p.u.", "-0.080 p.u."), ("voltage high", "1.070 p.u.", "+0.070 p.u.")]
    assert {row["element_type"] for row in episodes} == {"Node"}


def test_an_element_only_in_the_case_is_exceeded_without_a_reference_value():
    reference = _result("REF", [("line", "L1", [50.0, 50.0])])
    case = _result("C1", [("line", "L1", [50.0, 50.0]), ("line", "L9", [101.0, 50.0])])
    gl.reference_episodes(reference)
    gl.compare_case(case, reference, [(reference["hours"][0] * 3600.0, (reference["hours"][-1] + 1) * 3600.0)])
    episode = _rows([reference, case])[1]
    assert (episode["element_name"], episode["status"], episode["reference_text"], episode["delta_text"]) == (
        "L9", "EXCEEDED", "", "")


def test_a_relative_time_axis_uses_clock_labels():
    reference, case = _compared([("line", "L1", [50.0] * 3)], [("line", "L1", [50.0, 101.0, 50.0])], absolute=False)
    episode = _rows([reference, case])[1]
    assert (episode["start_text"], episode["end_text"]) == (gl.format_clock(1.0), gl.format_clock(2.0))


def test_episode_rows_are_cut_fairly_and_keep_the_case_rows(monkeypatch):
    monkeypatch.setattr(gl, "MAX_TABLE_ROWS", 6)
    series = [("line", "L{}".format(number), [101.0 + number, 50.0]) for number in range(6)]
    reference = _result("REF", [("line", name, [50.0, 50.0]) for _, name, _ in series])
    cases = [_result(case_id, series) for case_id in ("C1", "C2")]
    gl.reference_episodes(reference)
    for case in cases:
        gl.compare_case(case, reference, [(reference["hours"][0] * 3600.0, (reference["hours"][-1] + 1) * 3600.0)])
    payload = gl.empty_payload()
    gl._n0_episodes(payload, [reference] + cases)
    rows = payload["ScriptedEpisodes"]
    assert len(rows) == 6 and [row["row_kind"] for row in rows].count("case") == 2
    assert [row["element_name"] for row in rows if row["case_order"] == 1][1:] == ["L5", "L4"], "the highest peaks stay"
    assert [row["row_order"] for row in rows] == list(range(1, 7))
    assert any(row["check_name"] == "Table limit ScriptedEpisodes" for row in payload["ScriptedModelQuality"])


# ---------------------------------------------------------------------------
# Case summary
# ---------------------------------------------------------------------------
def _plan(case_id, status=None, reason=""):
    return {"id": case_id, "name": "Case " + case_id, "status": status or gl.PLAN_READY, "reason": reason, "members": []}


def test_case_summary_has_one_row_per_case_with_reference_first():
    reference, case = _compared([("line", "L1", [50.0, 60.0, 90.0, 95.0]), ("voltage", "Bus", [1.0, 1.0, 1.0, 1.0])],
                                [("line", "L1", [50.0, 60.0, 101.0, 112.4]), ("voltage", "Bus", [1.0, 0.97, 0.99, 1.0])])
    results = gl.judge_cases([reference, case])
    payload = gl.empty_payload()
    gl._case_summary(payload, results, {"cases": [_plan("C1"), _plan("C2", gl.PLAN_NOT_SIMULATED, "no outage assigned")]})
    ref_row, case_row, skipped = payload["ScriptedCaseSummary"]
    assert (ref_row["case_order"], ref_row["case_id"], ref_row["assessment"]) == (0, "REF", "BASELINE")
    assert (ref_row["max_loading_text"], ref_row["max_loading_element"], ref_row["max_loading_location"]) == (
        "95.0 %", "L1", "D7 / UW L1")
    assert ref_row["coincident_delta_text"] == "" and ref_row["lines_text"] == "none"
    assert (case_row["assessment"], case_row["violation"]) == (gl.ASSESSMENT_LOADING, 1)
    assert (case_row["max_loading_text"], case_row["max_loading_time"], case_row["max_loading_location"]) == (
        "112.4 %", "2014-01-01 03:00", "D7 / UW L1")
    assert (case_row["coincident_delta_text"], case_row["coincident_delta_element"]) == ("+17.4 pp", "L1")
    assert case_row["lines_text"] == "1 new" and case_row["nodes_text"] == "none"
    assert (case_row["violation_hours_text"], case_row["voltage_range_text"], case_row["coverage_text"]) == (
        "2.00 h", "0.970 - 1.000 p.u.", "100 %")
    assert (skipped["case_order"], skipped["assessment"], skipped["assessment_reason"]) == (
        2, gl.ASSESSMENT_SKIPPED, "no outage assigned")
    assert skipped["max_loading_text"] == "", "nothing but the reason for a case that was not calculated"


def test_case_summary_names_why_a_calculated_case_was_not_assessed():
    reference = _result("REF", [("line", "L1", [50.0, 50.0])])
    failed = gl.failed_case({"id": "C1", "name": "Case C1"}, "solver stopped")
    skipped = gl.n0_skipped_case({"id": "C2", "name": "Case C2"})
    payload = gl.empty_payload()
    gl._case_summary(payload, [reference, failed, skipped], {"cases": [_plan("C1"), _plan("C2")]})
    rows = payload["ScriptedCaseSummary"][1:]
    assert [(row["assessment"], row["assessment_reason"]) for row in rows] == [
        (gl.ASSESSMENT_NOT_EVALUATED, "solver stopped"), (gl.ASSESSMENT_SKIPPED, gl.N0_SKIPPED_TEXT)]


def test_case_summary_shows_no_increase_within_the_tolerance_and_names_reference_violations_exceeded():
    reference, case = _compared([("transformer", "TR1", [99.0, 104.0])], [("transformer", "TR1", [99.0, 104.0])])
    payload = gl.empty_payload()
    gl._case_summary(payload, gl.judge_cases([reference, case]), {"cases": [_plan("C1")]})
    ref_row, case_row = payload["ScriptedCaseSummary"]
    assert ref_row["transformers_text"] == "1 exceeded"
    assert (case_row["coincident_delta_text"], case_row["coincident_delta_element"]) == ("-", "")
    assert case_row["transformers_text"] == "1 pre-existing"
