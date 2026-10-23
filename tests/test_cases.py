"""State guard, planning cases and the case-based report tables."""

from __future__ import annotations

import importlib.util

import pytest


from _paths import delivered  # noqa: E402
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
    assert first["h6_name"] == "Outage 6" and last["h1_name"] == "Outage 7"
    assert last["c3_text"] == "" and last["h3_name"] == ""
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
    assert rows and all(row["col_count"] == 0 and row["h1_name"] == "" for row in rows)


def test_out_of_service_elements_read_n_a():
    _, results, request = _payload()
    results[1] = _result("OUT01", "Outage 1", {"L-380 Rhein": 18}, request["cases"][0], results[0], drop=("L-110 Hafen",))
    gl.apply_reference(results)

    payload = gl.build_cases_payload(Obj("Europe", "IntCase"), results, "BDS", "Result", request, "operator", "RUN")

    hafen = [row for row in payload["ScriptedAppendixLine"] if row["element_name"] == "L-110 Hafen"][0]
    assert hafen["c1_text"] == "n/a"


def test_switched_equipment_is_reported_out_of_service_not_resolved():
    hafen = "Project\\ElmLne\\L-110 Hafen.ElmLne"
    records = [_record(0, "Outage 1", (0, 3), component_keys=[hafen])]
    request = _request(records)
    reference = _result("REF", "Reference")
    case = _result("OUT01", "Outage 1", {"L-110 Hafen": -60}, request["cases"][0], reference)

    statuses = {record["item"]["element_name"]: record["status"] for record in case["comparison"]["line"]}
    assert statuses["L-110 Hafen"] == gl.STATUS_OUT_OF_SERVICE


def test_trend_charts_carry_reference_and_every_case_in_fixed_slots():
    payload, *_ = _payload()

    row = payload["ScriptedTrendMostLoaded"][0]
    assert [row["s{}_name".format(slot)] for slot in range(4)] == ["Reference", "Outage 1", "Outage 2", "Outage 3"]
    assert row["s4_name"] == " " and row["v4"] is None
    assert row["v0"] is not None and row["v3"] is not None
    assert payload["ScriptedReportMeta"][0]["chart_cases"] == "4"
    delta = payload["ScriptedTrendLargestDelta"]
    assert delta and "Largest coincident delta" in delta[0]["chart_title"]


def test_charts_show_at_most_six_cases_and_say_so():
    payload, *_ = _payload(cases=8)

    meta = payload["ScriptedReportMeta"][0]
    assert meta["chart_cases"] == "7"
    assert "first 6 of 8" in meta["radar_note"]
    assert len(payload["ScriptedCaseCounts"]) == 9, "tables still list every case"


def test_reference_disclaimer_tables():
    payload, *_ = _payload()

    classes = {row["class_label"]: row["element_count"] for row in payload["ScriptedPieLines"]}
    assert classes == {"up to 80 %": 2, "80 to 100 %": 2, "above 100 %": 0}
    exceeded = payload["ScriptedReferenceExceeded"]
    assert [(row["type_label"], row["element_name"], row["max_text"]) for row in exceeded] == [("Transformer", "TR-West T1", "104.0 %")]


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
    assert first["c2_text"].startswith("L-220 West 1")


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
    assert rows["New overloads"]["c2_text"] == "2" and rows["New overloads"]["violation"] == 1
    assert rows["Assessment"]["ref_text"] == "BASELINE"
    assert rows["Outage time covered by results"]["c1_text"] == "100 %"


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
