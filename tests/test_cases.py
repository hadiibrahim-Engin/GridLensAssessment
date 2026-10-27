"""State guard, planning cases and the case-based report tables."""

from __future__ import annotations

import importlib.util

import pytest


from _paths import delivered
SCRIPT = delivered("gridlens_report.py")
SPEC = importlib.util.spec_from_file_location("gridlens_cases", SCRIPT)
gl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gl)


@pytest.fixture(autouse=True)
def _assess_every_element(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "")


class Obj:
    def __init__(self, name, kind="ElmLne", **attributes):
        self.loc_name = name
        self.kind = kind
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self.kind

    def GetFullName(self):
        return "Project\\{}\\{}.{}".format(self.kind, self.loc_name, self.kind)


class Logger:
    def __init__(self):
        self.lines = []

    def write(self, stage, message, step=None, level="INFO"):
        self.lines.append((stage, level, message))

    def detail(self, message, level="INFO"):
        self.lines.append(("DETAIL", level, message))

    def table(self, header, rows, level="INFO"):
        for row in rows:
            self.lines.append(("TABLE", level, "  ".join(str(cell) for cell in row)))


# ---------------------------------------------------------------------------
# State guard
# ---------------------------------------------------------------------------
def test_state_guard_restores_in_reverse_order_and_verifies():
    flag = Obj("Outage", "IntPlannedout", outserv=0)
    with gl.StateGuard() as guard:
        assert guard.set(flag, "outserv", 1, "flag")
        assert flag.outserv == 1
    assert flag.outserv == 0


def test_state_guard_restores_after_a_failure_in_the_block():
    flag = Obj("Outage", "IntPlannedout", outserv=0)
    with pytest.raises(RuntimeError, match="boom"):
        with gl.StateGuard() as guard:
            guard.set(flag, "outserv", 1, "flag")
            raise RuntimeError("boom")
    assert flag.outserv == 0


def test_state_guard_names_the_value_it_could_not_put_back():
    class Locked(Obj):
        def __setattr__(self, name, value):
            if name == "outserv" and self.__dict__.get("locked"):
                return
            super().__setattr__(name, value)

    flag = Locked("Outage", "IntPlannedout", outserv=0)
    with pytest.raises(gl.StateRestoreError, match=r"flag: expected 0, read back 1"):
        with gl.StateGuard() as guard:
            guard.set(flag, "outserv", 1, "flag")
            flag.locked = True


def test_state_guard_refuses_an_attribute_it_cannot_read():
    with gl.StateGuard() as guard:
        assert guard.set(Obj("x", "IntPlannedout"), "outserv", 1, "flag") is False


# ---------------------------------------------------------------------------
# Case-based report tables
# ---------------------------------------------------------------------------
BASE = 1760486400  # an hour boundary, epoch seconds
HOURS = [BASE / 3600.0 + hour for hour in range(6)]
LABELS = ["2026-10-15 0{}:00".format(hour) for hour in range(6)]
TIMES = [float(hour) for hour in range(6)]
WINDOWS = [(0, 3), (2, 5), (1, 4), (0, 2), (3, 6), (1, 5), (0, 6), (2, 4)]
LINES = {"L-220 Nordring": [76, 80, 85, 82, 88, 84], "L-380 Rhein": [71, 74, 76, 75, 78, 77],
         "L-220 West 1": [78, 80, 82, 81, 84, 80], "L-110 Hafen": [60, 64, 66, 65, 70, 66]}
TRAFOS = {"TR-West T1": [95, 99, 102, 101, 104, 100]}
NODES = {"Busbar West 220 kV": [0.99, 0.98, 0.97, 0.975, 0.96, 0.97]}


def _item(category, name, values):
    obj = Obj(name, {"line": "ElmLne", "transformer": "ElmTr2", "voltage": "ElmTerm"}[category])
    points = [(LABELS[i], TIMES[i], value) for i, value in enumerate(values)]
    item = {"category": category, "object": obj, "key": obj.GetFullName(), "element_id": name, "element_name": name,
            "voltage_level": "220 kV", "nominal_kv": 220.0, "limits": gl.voltage_band(220.0) if category == "voltage" else None,
            "variable_id": "x", "variable": "Loading", "unit": "p.u." if category == "voltage" else "%", "points": points}
    item["statistics"] = gl.statistics(item)
    item["values"] = gl.value_array(values)
    return item


def _record(index, name, rows=None, component_keys=()):
    lo, hi = rows or WINDOWS[index % len(WINDOWS)]
    return {"key": "Project\\Outages\\{}.IntPlannedout".format(name), "id": name, "name": name, "source_class": "IntPlannedout",
            "status": gl.OUTAGE_CONSIDERED, "skip_reason": "", "equipment_name": "Equipment " + name, "equipment_type": "",
            "switching_actions": "", "start_time": LABELS[lo], "end_time": LABELS[hi - 1], "priority": index + 1,
            "window": (BASE + lo * 3600.0, BASE + hi * 3600.0), "component_keys": list(component_keys), "equipment_keys": [],
            "originally_ignored": False}


def _request(records, cases=None, background=()):
    config = gl.empty_case_config()
    config["background"] = [record["key"] for record in background]
    config["cases"] = cases or [{"id": "OUT{:02d}".format(i + 1), "name": record["name"], "outages": [record["key"]]}
                                for i, record in enumerate(records)]
    return gl.resolve_request(config, records + list(background), (BASE, BASE + 6 * 3600.0), "per_outage", "test cases")


def _result(case_id, name, shift=None, plan=None, ref=None, drop=()):
    shift = shift or {}
    rows = set(gl.window_rows(HOURS, plan["windows"].values())) if plan else set()
    series = [_item("line", n, [v + (shift.get(n, 0) if i in rows else 0) for i, v in enumerate(vals)])
              for n, vals in LINES.items() if n not in drop]
    series += [_item("transformer", n, [v + (shift.get(n, 0) if i in rows else 0) for i, v in enumerate(vals)]) for n, vals in TRAFOS.items()]
    series += [_item("voltage", n, [v + (shift.get(n, 0) if i in rows else 0) for i, v in enumerate(vals)]) for n, vals in NODES.items()]
    result = gl.case_result({"id": case_id, "name": name, "plan": plan, "hours": HOURS, "absolute": True}, series, LABELS, TIMES, "h")
    if plan is not None:
        keys = {key for record in plan["members"] for key in record["component_keys"]}
        gl.compare_case(result, ref, list(plan["windows"].values()), keys)
    return result


def _payload(cases=3, shifts=None):
    shifts = shifts or [{"L-380 Rhein": 18, "L-110 Hafen": 11}, {"L-220 West 1": 30, "L-380 Rhein": 25}, {"L-110 Hafen": 25}] + [{}] * 10
    records = [_record(index, "Outage {}".format(index + 1)) for index in range(cases)]
    request = _request(records)
    reference = _result("REF", "Reference")
    results = [reference] + [_result(plan["id"], plan["name"], shifts[index], plan, reference)
                             for index, plan in enumerate(request["cases"])]
    gl.apply_reference(results)
    payload = gl.build_cases_payload(Obj("Europe", "IntCase"), results, "BDS", "Result", request, "operator", "REFERENCE + PLANNING CASES")
    gl.validate_payload(payload)
    return payload, results, request


def test_every_case_is_compared_with_reference_inside_its_own_window():
    payload, results, _ = _payload()

    cases = {row["case_name"]: row for row in payload["ScriptedCases"]}
    assert cases["Reference"]["assessment"] == "BASELINE"
    assert cases["Outage 2"]["assessment"] == gl.ASSESSMENT_LOADING
    assert cases["Outage 2"]["violation"] == 1
    assert "L-220 West 1" in cases["Outage 2"]["assessment_detail"]
    assert "coincident increase +30.0 pp" in cases["Outage 2"]["assessment_detail"]
    assert cases["Outage 2"]["period_text"] == gl.period_text(gl._format_pf_time(BASE + 2 * 3600), gl._format_pf_time(BASE + 5 * 3600))
    assert cases["Outage 2"]["coverage_text"] == "100 %"
    assert cases["Outage 2"]["reference_text"] == "R0: no planned outage"


def test_case_counts_follow_the_whole_period_of_each_case():
    payload, *_ = _payload()

    counts = {row["case_name"]: (row["line_count"], row["transformer_count"], row["node_count"]) for row in payload["ScriptedCaseCounts"]}
    assert counts["Reference"] == (0, 1, 0)
    assert counts["Outage 2"][0] == 2
    assert [row["case_order"] for row in payload["ScriptedCaseCounts"]] == [0, 1, 2, 3]


def test_matrix_tables_continue_in_blocks_of_six_cases():
    payload, *_ = _payload(cases=8, shifts=[{"L-380 Rhein": 20}] * 8)

    rows = payload["ScriptedAppendixLine"]
    assert {row["block"] for row in rows} == {1, 2}
    first = [row for row in rows if row["block"] == 1][0]
    last = [row for row in rows if row["block"] == 2][0]
    assert first["col_count"] == 6 and last["col_count"] == 2
    assert first["case_f_name"] == "Outage 6" and last["case_a_name"] == "Outage 7"
    assert last.get("case_c_text") is None and last.get("case_c_name") is None, "unused slots are not written"
    assert first["ref_text"].endswith(" %")


def test_more_than_six_cases_are_all_assessed_and_compared():
    payload, *_ = _payload(cases=8, shifts=[{"L-380 Rhein": 20}] * 8)

    assert len([row for row in payload["ScriptedCases"] if not row["is_reference"]]) == 8
    comparison = payload["ScriptedCaseComparison"]
    assert {row["block"] for row in comparison} == {1, 2}
    assert comparison[0]["element_name"] == "New overloads"


def test_matrix_without_outage_cases_shows_reference_only():
    payload, *_ = _payload(cases=0)

    rows = payload["ScriptedAppendixLine"]
    assert rows and all(row["col_count"] == 0 and row.get("case_a_name") is None for row in rows)


def test_out_of_service_elements_read_n_a():
    _, results, request = _payload()
    results[1] = _result("OUT01", "Outage 1", {"L-380 Rhein": 18}, request["cases"][0], results[0], drop=("L-110 Hafen",))
    gl.apply_reference(results)

    payload = gl.build_cases_payload(Obj("Europe", "IntCase"), results, "BDS", "Result", request, "operator", "RUN")

    hafen = [row for row in payload["ScriptedAppendixLine"] if row["element_name"] == "L-110 Hafen"][0]
    assert hafen["case_a_text"] == "n/a"


def test_switched_equipment_is_reported_out_of_service_not_resolved():
    hafen = "Project\\ElmLne\\L-110 Hafen.ElmLne"
    records = [_record(0, "Outage 1", (0, 3), component_keys=[hafen])]
    request = _request(records)
    reference = _result("REF", "Reference")
    case = _result("OUT01", "Outage 1", {"L-110 Hafen": -60}, request["cases"][0], reference)

    statuses = {record["item"]["element_name"]: record["status"] for record in case["comparison"]["line"]}
    assert statuses["L-110 Hafen"] == gl.STATUS_OUT_OF_SERVICE


def test_contract_seven_has_no_radar_and_no_multi_line_trend_tables():
    # The assignment removes the radar and the time plots of REF plus six cases; the time course of H09 draws two series.
    payload, *_ = _payload()

    assert not {"ScriptedRadar", "ScriptedTrendMostLoaded", "ScriptedTrendLargestDelta"} & set(payload)
    assert "chart_cases" not in payload["ScriptedReportMeta"][0] and "radar_note" not in payload["ScriptedReportMeta"][0]
    assert [field for field, _ in dict(gl.TABLES)["ScriptedTimeCriticality"]] == [
        "time_label", "timestamp", "series_ref_name", "series_a_name", "value_ref", "value_a"]


def test_more_than_six_cases_stay_in_every_table():
    payload, *_ = _payload(cases=8)

    assert len(payload["ScriptedCaseCounts"]) == 9, "tables still list every case"
    assert [row["block"] for row in payload["ScriptedCaseComparison"]].count(2) > 0


def test_reference_disclaimer_tables():
    payload, *_ = _payload()

    classes = {row["class_label"]: row["element_count"] for row in payload["ScriptedPieLines"]}
    assert classes == {"up to 80 %": 2, "80 to 100 %": 2, "above 100 %": 0}
    base = [row for row in payload["ScriptedReferenceFindings"] if row["level"] == "n-0"]
    violated = [(row["element_type"], row["element_name"], row["value_text"]) for row in base if row["status"] == "VIOLATED"]
    assert violated == [("Transformer", "TR-West T1", "104.0 %")]
    assert {row["status"] for row in base} <= {"VIOLATED", "WARNING"}


def test_metric_view_and_key_cards():
    payload, *_ = _payload()

    metrics = {row["case_name"]: row for row in payload["ScriptedCaseMetrics"]}
    assert metrics["Reference"]["coincident_delta_text"] == "-"
    assert metrics["Outage 2"]["coincident_delta_text"] == "+30.0 pp - L-220 West 1"
    assert metrics["Outage 2"]["maxima_difference_text"] == "+30.0 pp"
    assert metrics["Outage 2"]["violation_hours_text"] == "3.00 h"
    kpi = payload["ScriptedKpis"][0]
    assert kpi["highest_text"].startswith("114.0 %")
    assert kpi["highest_violation"] == 1
    assert kpi["delta_text"] == "+30.0 pp · Outage 2"


def test_top_lines_by_case_rank_each_case_on_its_own():
    payload, *_ = _payload()

    first = payload["ScriptedTopLinesByCase"][0]
    assert first["element_name"] == "1"
    assert first["ref_text"] == "L-220 Nordring - 88.0 %"
    assert first["case_b_text"].startswith("L-220 West 1")


def test_calculation_evidence_lists_every_run_and_its_result_object():
    payload, results, _ = _payload()
    results[1]["result_object"] = "GridLens_261015-000000_OUT01"

    payload = gl.build_cases_payload(Obj("Europe", "IntCase"), results, "BDS", "Result", _payload()[2], "operator", "RUN")

    runs = payload["ScriptedCalculationRuns"]
    assert [row["run_kind"] for row in runs] == ["REFERENCE", "CASE", "CASE", "CASE"]
    assert runs[1]["result_object"] == "GridLens_261015-000000_OUT01"
    assert runs[0]["time_steps"] == 6


def test_comparison_table_flags_rows_with_caused_violations():
    payload, *_ = _payload()

    rows = {row["element_name"]: row for row in payload["ScriptedCaseComparison"]}
    assert rows["New overloads"]["case_b_text"] == "2" and rows["New overloads"]["violation"] == 1
    assert rows["Assessment"]["ref_text"] == "BASELINE"
    assert rows["Outage time covered by results"]["case_a_text"] == "100 %"


def test_report_states_what_the_assessment_does_and_does_not_prove():
    payload, *_ = _payload()

    meta = payload["ScriptedReportMeta"][0]
    assert "Statement A" in meta["coverage_statement"] and "Statement B" in meta["coverage_statement"]
    assert meta["qds_mode_text"].startswith("Complete ComStatsim period")
    assert meta["case_source_text"] == "test cases"


def test_report_text_never_calls_the_data_synthetic():
    payload, *_ = _payload()

    text = " ".join(str(value) for rows in payload.values() for row in rows for value in row.values())
    assert "SYNTHETIC" not in text.upper()


def test_period_text_shortens_a_same_day_window():
    assert gl.period_text("2026-10-15 00:00", "2026-10-15 05:00") == "2026-10-15 00:00 - 05:00"
    assert gl.period_text("2026-10-15 22:00", "2026-10-16 05:00") == "2026-10-15 22:00 - 2026-10-16 05:00"
    assert gl.period_text("", "") == ""


# ---------------------------------------------------------------------------
# Settings: the n-0 QDS assessment with default, changed and restored limits
# ---------------------------------------------------------------------------
def _comparable(payload):
    """The published rows without the generation time, which differs between two builds."""
    return {table: [{field: value for field, value in row.items() if field != "generation_date"} for row in rows]
            for table, rows in payload.items()}


@pytest.fixture
def default_settings_afterwards():
    gl.reset_settings()
    yield
    gl.reset_settings()


def test_default_settings_reproduce_the_n0_report_exactly(default_settings_afterwards):
    before, *_ = _payload()
    snapshot = gl.activate_settings({})
    after, *_ = _payload()

    assert snapshot["overrides"] == {} and snapshot["values"] == gl.default_settings()
    assert _comparable(after) == _comparable(before)


def test_changed_assessment_limits_change_only_the_assessment_and_restore_cleanly(default_settings_afterwards):
    original, *_ = _payload()
    gl.activate_settings({"line_limit": 150.0, "line_warning": 120.0, "loading_change_tolerance": 50.0})
    changed, results, _ = _payload()
    gl.reset_settings()
    restored, *_ = _payload()

    cases = {row["case_name"]: row["assessment"] for row in changed["ScriptedCases"]}
    assert cases["Outage 2"] != gl.ASSESSMENT_LOADING, "no line exceeds 150 %"
    assert {row["class_label"] for row in changed["ScriptedPieLines"]} == {"up to 120 %", "120 to 150 %", "above 150 %"}
    quality = {row["check_id"]: row for row in changed["ScriptedModelQuality"]}
    assert "lines" in quality["limit_loading"]["message"] and "150" in quality["limit_loading"]["message"]
    assert quality["settings"]["status"] == "WARNING" and "GridLens default 100 %" in quality["settings"]["message"]
    # The calculated values themselves are untouched: settings only interpret them.
    second = next(result for result in results if result["name"] == "Outage 2")
    assert max(stats["max"] for _, stats in second["by_category"]["line"]) > 100.0
    assert _comparable(restored) == _comparable(original)


def test_report_names_the_settings_and_the_rules_version(default_settings_afterwards):
    payload, *_ = _payload()

    quality = {row["check_id"]: row for row in payload["ScriptedModelQuality"]}
    assert quality["settings"]["status"] == "INFO"
    assert "classification rules 1.0" in quality["settings"]["message"]
    assert "GridLens defaults" in quality["settings"]["message"]
    assert "provisionally" in quality["settings"]["message"]


# ---------------------------------------------------------------------------
# Did each outage take effect?
# ---------------------------------------------------------------------------
LINE_KEY = "Project\\ElmLne\\L-220 Nordring.ElmLne"


def _effect_result(case_id, values=None):
    """All lines of LINES; `values` replaces whole series by element name."""
    series = [_item("line", name, (values or {}).get(name, vals)) for name, vals in LINES.items()]
    return gl.case_result({"id": case_id, "name": case_id, "hours": HOURS, "absolute": True}, series, LABELS, TIMES, "h")


def _effect_plan(component_keys):
    record = _record(0, "Outage A", rows=(1, 3), component_keys=component_keys)
    return _request([record])["cases"][0]


def test_an_outaged_line_without_load_in_its_window_is_applied():
    plan = _effect_plan([LINE_KEY])
    reference = _effect_result("REF")
    case = _effect_result("OUT01", {"L-220 Nordring": [76, 0, 0, 82, 88, 84], "L-380 Rhein": [71, 90, 91, 75, 78, 77]})
    [(name, status, reason)] = gl.outage_effects(case, reference, plan)
    assert (name, status) == ("Outage A", gl.OUTAGE_APPLIED)
    assert "L-220 Nordring" in reason


def test_an_unrecorded_component_counts_when_the_network_differs_in_the_window():
    plan = _effect_plan(["Project\\ElmCoup\\Switch 7.ElmCoup"])
    case = _effect_result("OUT01", {"L-380 Rhein": [71, 90, 91, 75, 78, 77]})
    [(_, status, _)] = gl.outage_effects(case, _effect_result("REF"), plan)
    assert status == gl.OUTAGE_EFFECT


def test_a_case_equal_to_ref_in_the_window_shows_no_effect():
    plan = _effect_plan([LINE_KEY])
    # A difference outside the window does not count.
    case = _effect_result("OUT01", {"L-380 Rhein": [71, 74, 76, 99, 78, 77]})
    [(_, status, _)] = gl.outage_effects(case, _effect_result("REF"), plan)
    assert status == gl.OUTAGE_NO_EFFECT


def test_the_effect_is_not_checkable_without_reference_or_window_rows():
    plan = _effect_plan([LINE_KEY])
    assert gl.outage_effects(_effect_result("OUT01"), None, plan)[0][1] == gl.OUTAGE_UNCHECKED
    late = _request([_record(0, "Outage A", rows=(1, 3), component_keys=[LINE_KEY])])["cases"][0]
    late["windows"] = {key: (BASE + 10 * 3600.0, BASE + 12 * 3600.0) for key in late["windows"]}
    assert gl.outage_effects(_effect_result("OUT01"), _effect_result("REF"), late)[0][1] == gl.OUTAGE_UNCHECKED


def test_outage_quality_warns_about_an_outage_without_effect():
    payload = {"ScriptedModelQuality": []}
    results = [{"id": "OUT01", "outage_checks": [("Outage A", gl.OUTAGE_APPLIED, ""), ("Outage B", gl.OUTAGE_NO_EFFECT, "")]},
               {"id": "OUT02", "outage_checks": [("Outage C", gl.OUTAGE_EFFECT, "")]}, {"id": "REF"}]
    gl.outage_quality(payload, results)
    first, second = payload["ScriptedModelQuality"]
    assert (first["check_id"], first["status"]) == ("outages_OUT01", "WARNING")
    assert "1 APPLIED, 1 NO EFFECT" in first["message"] and "Outage B: NO EFFECT" in first["message"]
    assert (second["status"], second["message"]) == ("PASS", "1 EFFECT SEEN.")


def test_applied_text_reads_the_option_and_the_flags_back():
    records = [{"name": "Outage A", "_object": Obj("Outage A", "IntPlannedout", outserv=0)},
               {"name": "Outage B", "_object": Obj("Outage B", "IntPlannedout", outserv=1)}]
    text = gl.applied_text(Obj("QDS", "ComStatsim", iopt_maint=1), records)
    assert "[iopt_maint] = 1" in text and "applied: Outage A." in text
    assert "= unreadable" in gl.applied_text(Obj("QDS", "ComStatsim"), records[1:])


# ---------------------------------------------------------------------------
# Variable selection of the kept result object
# ---------------------------------------------------------------------------
class Folder(Obj):
    def __init__(self, name, children=()):
        super().__init__(name, "ElmRes")
        self.children = list(children)

    def GetContents(self, pattern):
        kind = pattern.split(".")[-1]
        return [child for child in self.children if child.GetClassName() == kind]



def test_monitor_text_names_class_wide_and_object_monitors():
    line = Obj("L-220 Nordring")
    result = Folder("QDS AC", [Obj("Lines", "IntMon", obj_id=line, vars=["c:loading"]),
                               Obj("Nodes", "IntMon", obj_id=None, classnm="ElmTerm", vars=["m:u"])])
    assert gl.monitor_text(result) == ("2 variable set(s) (IntMon): L-220 Nordring (ElmLne): c:loading; "
                                       "ElmTerm: m:u")
    assert gl.monitor_text(Folder("empty")) == "no variable selection (no IntMon inside)"


def test_recorded_text_lists_the_assessed_variables_first():
    assert gl.recorded_text({"b:noconv": 1, "b:number": 1}) == "2 column(s): b:noconv x1, b:number x1"
    assert gl.recorded_text({"b:noconv": 1, "m:u": 3}) == "4 column(s): m:u x3, b:noconv x1"
    assert gl.recorded_text(None).startswith("not readable")


# ---------------------------------------------------------------------------
# Does an outage stay in effect after its window?
# ---------------------------------------------------------------------------
def test_an_outage_that_stays_switched_off_after_its_window_is_found():
    plan = _effect_plan([LINE_KEY])  # window: rows 1 and 2
    reference = _effect_result("REF")
    lasting = _effect_result("OUT01", {"L-220 Nordring": [76, 0, 0, 0, 0, 84]})
    [(name, stretch, total, until, back)] = gl.outage_persistence(lasting, reference, plan)
    assert (name, stretch, total, until, back) == ("Outage A", 2.0, 2.0, LABELS[4], LABELS[5])
    forever = _effect_result("OUT01", {"L-220 Nordring": [76, 0, 0, 0, 0, 0]})
    assert gl.outage_persistence(forever, reference, plan)[0][1:] == (3.0, 3.0, LABELS[5], "")
    back = _effect_result("OUT01", {"L-220 Nordring": [76, 0, 0, 82, 88, 84]})
    assert gl.outage_persistence(back, reference, plan)[0][1:] == (0, 0, "", LABELS[3])
    assert gl.outage_persistence(back, None, plan) == []


def test_persistence_quality_names_the_hours_after_the_window():
    payload = {"ScriptedModelQuality": []}
    gl.persistence_quality(payload, [{"id": "OUT01", "outage_persistence": [("Outage A", 3.0, 3.0, "x", "")]},
                                     {"id": "OUT02", "outage_persistence": [("Outage B", 0, 0, "", "y")]}])
    [row] = payload["ScriptedModelQuality"]
    assert (row["check_id"], row["status"]) == ("outages_after_OUT01", "WARNING")
    assert row["message"].startswith("Outage A: 3 h after its window end, until the end of the period.")


def test_switch_changes_name_each_switch_that_differs():
    before = {"a": ("CB1", 1.0), "b": ("IS.1", 1.0), "c": ("CB5", 0.0)}
    after = {"a": ("CB1", 0.0), "b": ("IS.1", 1.0), "c": ("CB5", 0.0)}
    assert gl.switch_changes_text(before, after) == ["CB1 closed -> open"]
    assert gl.switch_changes_text(before, before) == []


def test_data_attributes_text_shows_values_objects_and_times():
    line = Obj("L-220 Nordring")
    outage = Obj("Outage A", "IntPlannedout", outserv=0, components=[line], starttime=BASE, priority=2)
    text = gl.data_attributes_text(outage)
    assert "components=[L-220 Nordring]" in text and "outserv=0" in text and "priority=2" in text
    assert "starttime=" + gl._format_pf_time(BASE) in text


# ---------------------------------------------------------------------------
# What each result object holds, in the log
# ---------------------------------------------------------------------------
def test_outage_component_lines_count_steps_without_load_inside_and_outside_the_window():
    plan = _effect_plan([LINE_KEY])  # window: rows 1 and 2
    case = _effect_result("OUT01", {"L-220 Nordring": [76, 0, 0, 0, 0, 84]})
    [line] = gl.outage_component_lines(case, _effect_result("REF"), plan)
    assert line == ("Outage 'Outage A', component 'L-220 Nordring' (ElmLne, x): without load in 2 of 2 step(s) "
                    "inside its window and in 2 of 4 outside it; REF: without load in 0 of 6 step(s).")
    [missing] = gl.outage_component_lines(case, None, _effect_plan(["Project\\ElmCoup\\CB1.ElmCoup"]))
    assert missing == "Outage 'Outage A': none of its 1 component(s) is recorded as loading in the result object."


def test_result_object_text_names_steps_period_classes_and_variables():
    counters = {"columns": 4, "columns_by_class": {"ElmTerm": 2, "ElmLne": 1, "ElmTr2": 1},
                "columns_by_variable": {"m:u": 2, "c:loading": 2}}
    text = gl.result_object_text(Obj("GridLens_x_REF", "ElmRes"), counters, LABELS, TIMES)
    assert text == ("Result object 'GridLens_x_REF': 6 time step(s) from {} to {} (step 1 h, span 5 h); 4 column(s) "
                    "by class: ElmTerm 2, ElmLne 1, ElmTr2 1; by variable: c:loading 2, m:u 2.".format(LABELS[0], LABELS[-1]))


def test_failed_cases_stay_in_every_contract_seven_table_with_their_reason():
    # An error-only run: the QDS of every case failed and so did n-1. Nothing may disappear or read as OK.
    records = [_record(index, "Outage {}".format(index + 1)) for index in range(2)]
    request = _request(records)
    reference = _result("REF", "Reference")
    results = [reference] + [gl.failed_case({"id": plan["id"], "name": plan["name"], "plan": plan}, "did not converge")
                             for plan in request["cases"]]
    for case in results[1:]:
        case["n1"] = {"status": "NOT EVALUATED", "times": 0, "reason": "no result object"}
    gl.apply_reference(results)
    payload = gl.build_cases_payload(Obj("Europe", "IntCase"), results, "BDS", "Result", request, "operator", "RUN")
    gl.validate_payload(payload)

    rows = [(row["case_name"], row["level"], row["assessment"], row["completeness_text"], row["violation"])
            for row in payload["ScriptedCaseStatistics"] if row["case_name"] != "Reference"]
    assert rows == [("Outage 1", "n-0", "NOT EVALUATED", "did not converge", 2), ("Outage 2", "n-0", "NOT EVALUATED", "did not converge", 2),
                    ("Outage 1", "n-1", "NOT EVALUATED", "no result object", 2), ("Outage 2", "n-1", "NOT EVALUATED", "no result object", 2)]
    coverage = [(row["case_name"], row["level"], row["coverage_text"]) for row in payload["ScriptedCoverage"] if row["case_name"] != "Reference"]
    assert ("Outage 1", "n-0", "not evaluated: did not converge") in coverage and ("Outage 2", "n-1", "not evaluated: no result object") in coverage
    quality = {(row["case_name"], row["level"], row["status"]) for row in payload["ScriptedQualityRegister"]}
    assert quality == {("Outage 1", "n-1", "NOT-EVALUATED"), ("Outage 2", "n-1", "NOT-EVALUATED"),
                       ("Outage 1", "n-0", "FAILED"), ("Outage 2", "n-0", "FAILED")}
    text = payload["ScriptedReportMeta"][0]["overall_text"]
    assert "The QDS of 2 case(s) could not be evaluated" in text and "was requested but could not be evaluated" in text
    assert "no n-1 result to rely on" in text


def test_without_n1_the_time_criticality_shows_the_qds_steps_of_reference_and_every_case():
    # n-0 with planned outages only: the Time page draws Reference against every case per QDS time step and lists
    # the steps where a case has other critical elements than Reference.
    payload, results, _request = _payload()
    reference = gl.find_reference(results)
    steps = gl.critical_steps(reference)

    chart = payload["ScriptedTimeCriticality"]
    assert [row["time_label"] for row in chart] == LABELS
    assert [row["series_ref_name"] for row in chart][:1] == ["Reference (n-0)"] and chart[0]["series_a_name"] == "all cases (n-0)"
    assert [row["value_ref"] for row in chart] == [float(len(steps.get(row, ()))) for row in range(len(LABELS))]
    matrix = payload["ScriptedTimeMatrix"]
    assert matrix and all(row["element_name"] in LABELS for row in matrix)
    # Outage 2 overloads L-220 West 1 from 04:00 (+30 pp on 84 %): that step lists it as caused (red).
    four = next(row for row in matrix if row["element_name"] == "2026-10-15 04:00")
    assert four["violation"] == 1 and four["case_b_text"].startswith("E ")
    # The same numbers after the value arrays were released (as in a PowerFactory run).
    for result in results:
        gl.release_values(result)
    again = gl.empty_payload()
    gl._time_criticality(again, results, {})
    assert again["ScriptedTimeCriticality"] == chart and again["ScriptedTimeMatrix"] == matrix
