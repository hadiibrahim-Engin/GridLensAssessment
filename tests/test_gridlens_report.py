from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "powerfactory" / "gridlens_report.py"
SPEC = importlib.util.spec_from_file_location("gridlens_report", SCRIPT)
gl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gl)


@pytest.fixture(autouse=True)
def _assess_every_element(monkeypatch, tmp_path):
    """Fake elements belong to no grid; only the scope tests use D7. No dialog opens."""
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "")
    monkeypatch.setattr(gl, "CASE_SOURCE", "per_outage")
    monkeypatch.setattr(gl, "CASE_CONFIG_DIR", str(tmp_path / "cases"))


class PFObject:
    def __init__(self, name, kind, **attributes):
        self.loc_name = name
        self.kind = kind
        self.desc = attributes.pop("desc", "")
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self.kind

    def GetFullName(self):
        return "Project\\{}\\{}.{}".format(self.kind, self.loc_name, self.kind)

    def GetContents(self, *_args):
        return []


# The acceptance project's first outage: 2014-01-01 00:00:00 to 23:59:59 local.
OUTAGE_START = 1388530800
OUTAGE_END = 1388617199
# ComStatsim declares 2014-01-01 00:00 to 2014-01-05 00:00 for that project.
PERIOD_START = 1388530800
PERIOD_END = 1388876400


class PlannedOutage(PFObject):
    """IntPlannedout as PowerFactory 2026 exposes it: data, no Apply method."""

    def __init__(self, name, *, disabled=False, equipment=None,
                 starttime=OUTAGE_START, endtime=OUTAGE_END):
        super().__init__(name, "IntPlannedout", outserv=1 if disabled else 0)
        self.starttime = starttime
        self.endtime = endtime
        self.priority = 1
        self.components = list(equipment or ())


class ElmRes(PFObject):
    def __init__(self, name="Configured QDS Result"):
        super().__init__(name, "ElmRes")
        self.deleted = False
        self.time = PFObject("Time", "SetTime")
        self.line = PFObject("Line A", "ElmLne", outserv=0, uknom=110)
        self.term = PFObject("Bus A", "ElmTerm", outserv=0, uknom=110)
        self.variables = ("b:tnow", "c:loading", "m:u", "m:phiu")
        self.objects = (self.time, self.line, self.term, self.term)
        self.units = ("h", "%", "p.u.", "deg")
        self.columns = ([0.0, 1.0], [90.0, 110.0], [0.96, 0.94], [0.0, 2.0])

    def clone(self):
        return ElmRes(self.loc_name)

    def Load(self):
        return None

    def Release(self):
        return None

    def Delete(self):
        self.deleted = True
        return None

    def GetNumberOfRows(self):
        return 2

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

    def FindColumn(self, variable):
        return self.variables.index(variable)


class ImplicitTimeElmRes(ElmRes):
    """QDS result whose time scale is addressed through column -1."""

    def __init__(self):
        super().__init__()
        self.variables = ("c:loading", "m:u", "m:phiu")
        self.objects = (self.line, self.term, self.term)
        self.units = ("%", "p.u.", "deg")
        self.columns = ([90.0, 110.0], [0.96, 0.94], [0.0, 2.0])
        self.scale = [0.0, 1.0]

    def GetValue(self, row, column):
        if column == -1:
            return self.scale[row]
        return self.columns[column][row]

    def GetUnit(self, column):
        if column == -1:
            return "h"
        return super().GetUnit(column)

    def GetColumnValues(self, *_args):
        raise TypeError("PowerFactory requires an IntVec argument")

    def FindColumn(self, *_args):
        return -1


class StudyCase(PFObject):
    def __init__(self):
        super().__init__("Study", "IntCase")
        self.copies = []

    def AddCopy(self, result):
        copy = result.clone()
        self.copies.append(copy)
        return copy


class StudyTime(PFObject):
    def __init__(self):
        super().__init__("Study Time", "SetTime", cDate=20140501, cTime=0)


class QDS(PFObject):
    def __init__(self, result, study_time, failure=None):
        super().__init__(
            "Configured QDS", "ComStatsim", results=result,
            calcPeriod=2, stepSize=1, stepUnit=2,
            iopt_net=0, iopt_at=1, iopt_maint=0,
            startTime=PERIOD_START, endTime=PERIOD_END,
        )
        self.study_time = study_time
        self.failure = failure
        self.execute_calls = 0
        self.start_times = []
        self.outage_options = []
        self.outages = []
        self.active_outages = []

    def Execute(self):
        self.execute_calls += 1
        self.active_outages.append(
            [item.loc_name for item in self.outages if item.outserv == 0])
        self.start_times.append((self.study_time.cDate, self.study_time.cTime))
        self.outage_options.append(self.iopt_maint)
        self.study_time.cDate = 20140531
        self.study_time.cTime = 23000000
        if self.failure:
            raise self.failure
        return 0


class Report(PFObject):
    def __init__(self):
        super().__init__("GridLens", "IntReport")
        self.reset_calls = 0
        self.tables = {}

    def Reset(self):
        self.reset_calls += 1
        self.tables = {}

    def CreateTable(self, name):
        self.tables[name] = {"fields": {}, "values": {}}

    def CreateField(self, table, field, field_type):
        self.tables[table]["fields"][field] = field_type

    def SetValue(self, table, field, row, value):
        self.tables[table]["values"][row, field] = value


class Script(PFObject):
    def __init__(self, parent):
        super().__init__("Run GridLens", "ComPython")
        self.parent = parent

    def GetParent(self):
        return self.parent


class App:
    def __init__(self, outages=(), qds_failure=None):
        self.study = StudyCase()
        self.report = Report()
        self.script = Script(self.report)
        self.original_result = ElmRes()
        self.study_time = StudyTime()
        self.qds = QDS(self.original_result, self.study_time, qds_failure)
        self.project = PFObject("Model", "IntPrj")
        self.outage_folder = PFObject("Outages", "IntPrjfolder")
        self.outages = list(outages)
        self.qds.outages = self.outages
        self.messages = []
        self.outage_folder.GetContents = self._outage_contents
        self.project.GetContents = self._outage_contents

    def _outage_contents(self, pattern, *_args):
        return [item for item in self.outages if pattern.endswith(item.kind)]

    def PrintPlain(self, message):
        self.messages.append(message)

    def GetCurrentScript(self):
        return self.script

    def GetActiveStudyCase(self):
        return self.study

    def GetActiveProject(self):
        return self.project

    def GetProjectFolder(self, key):
        return self.outage_folder if key == "outage" else None

    def GetFromStudyCase(self, name):
        if name == "ComStatsim":
            return self.qds
        if name == "SetTime":
            return self.study_time
        return None

    def GetCalcRelevantObjects(self, _pattern, *_args):
        return []


def test_table_contract_is_single_versioned_19_table_contract():
    assert gl.PUBLISHER_VERSION == "8.0.0"
    assert gl.TEMPLATE_VERSION == "6.0.0"
    assert gl.DATA_CONTRACT_VERSION == "6.0"
    assert len(gl.TABLES) == 19
    tables = dict(gl.TABLES)
    for name in ("ScriptedCases", "ScriptedCaseComparison", "ScriptedCalculationRuns",
                 "ScriptedCaseCounts", "ScriptedAppendixLine", "ScriptedTopLinesByCase"):
        assert name in tables
    # The two-case outputs of earlier contracts and the LODF ranking are gone.
    for removed in ("ScriptedPlannedOutages", "ScriptedLoadingRanking",
                    "ScriptedOverview", "ScriptedVoltageViolations",
                    "ScriptedTrendLineLoading", "ScriptedLodfRanking"):
        assert removed not in tables
    assert "lodf_text" not in dict(tables["ScriptedReportMeta"])
    assert "coverage_statement" in dict(tables["ScriptedReportMeta"])
    assert "generated_by" in dict(tables["ScriptedReportMeta"])
    assert "run_mode" in dict(tables["ScriptedReportMeta"])


def test_reference_runs_without_and_every_outage_runs_as_its_own_case(monkeypatch):
    outages = (PlannedOutage("Outage A"), PlannedOutage("Outage B"),
               PlannedOutage("Outage C", disabled=True))
    app = App(outages)
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)
    monkeypatch.setattr(gl.getpass, "getuser", lambda: "operator")

    counts = gl.execute_gridlens(app)

    assert app.qds.execute_calls == 3
    # REF is free of planned outages; each outage case has the option on.
    assert app.qds.outage_options == [0, 1, 1]
    # PowerFactory sees exactly one outage as active per outage case.
    assert app.qds.active_outages[1:] == [["Outage A"], ["Outage B"]]
    assert app.qds.iopt_maint == 0, "the original option value must come back"
    assert [item.outserv for item in outages] == [0, 0, 1], \
        "every 'Ignored' flag must come back"
    assert app.qds.start_times == [(20140501, 0)] * 3
    assert app.qds.results is app.original_result
    # Every case keeps its own result object in the study case.
    assert not any(copy.deleted for copy in app.study.copies)
    names = [copy.loc_name for copy in app.study.copies]
    assert len(names) == 3 and len(set(names)) == 3
    assert [name.rsplit("_", 1)[-1] for name in names] == ["REF", "OUT01", "OUT02"]
    assert all(name.startswith("GridLens_") and len(name) <= 40 for name in names)
    runs = app.report.tables["CalculationRuns"]["values"]
    assert [runs[index, "result_object"] for index in range(3)] == names
    assert (app.study_time.cDate, app.study_time.cTime) == (20140501, 0)
    assert app.report.reset_calls == 1
    assert counts["ScriptedCases"] == 4  # REF, two outage cases, one skipped
    values = app.report.tables["ReportMeta"]["values"]
    assert values[0, "generated_by"] == "operator"
    assert values[0, "run_mode"] == "REFERENCE + PLANNING CASES"
    assert any("blocking API call may take several minutes" in line
               for line in app.messages)
    assert any("Time period [calcPeriod] = 2" in line for line in app.messages)
    assert any("Step size [stepSize] = 1" in line for line in app.messages)
    assert any("Step unit [stepUnit] = 2" in line for line in app.messages)
    assert any("Calculation options: iopt_at=1, iopt_maint=0, iopt_net=0" in line
               for line in app.messages)
    assert any("Planned outages [iopt_maint] = 0" in line for line in app.messages)
    assert any("Simulated period [startTime..endTime] = 2014-01-01" in line
               for line in app.messages)
    assert any("Initial Study Case time: 2014-05-01 00:00:00" in line
               for line in app.messages)
    cases = app.report.tables["Cases"]["values"]
    assert [cases[index, "case_name"] for index in range(4)] == [
        "Reference", "Outage A", "Outage B", "Outage C"]
    assert cases[3, "assessment"] == gl.ASSESSMENT_SKIPPED


def test_direct_mode_with_no_outage_in_scope_does_not_calculate(monkeypatch):
    app = App((PlannedOutage("Disabled", disabled=True),))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", False)

    counts = gl.execute_gridlens(app)

    assert app.qds.execute_calls == 0
    assert app.qds.results is app.original_result
    assert app.qds.iopt_maint == 0
    assert counts["ScriptedCases"] == 1  # only the skipped outage is listed
    values = app.report.tables["ReportMeta"]["values"]
    assert values[0, "run_mode"] == (
        "NO CALCULATION - NO PLANNING CASE TO CALCULATE")


def test_reference_failure_still_restores_option_and_result_binding(monkeypatch):
    outage = PlannedOutage("Outage")
    app = App((outage,), qds_failure=RuntimeError("solver stopped"))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    with pytest.raises(gl.GridLensError, match="solver stopped"):
        gl.execute_gridlens(app)

    assert app.qds.iopt_maint == 0
    assert outage.outserv == 0
    assert app.qds.results is app.original_result
    assert (app.study_time.cDate, app.study_time.cTime) == (20140501, 0)


def test_failed_outage_case_is_reported_and_state_is_restored(monkeypatch):
    outages = (PlannedOutage("Outage A"), PlannedOutage("Outage B"))
    app = App(outages)
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)
    real_execute = app.qds.Execute

    def execute():
        if app.qds.execute_calls == 1:  # the first outage case
            app.qds.execute_calls += 1
            app.qds.active_outages.append([])
            raise RuntimeError("solver stopped")
        return real_execute()
    app.qds.Execute = execute

    gl.execute_gridlens(app)

    assert [item.outserv for item in outages] == [0, 0]
    assert app.qds.iopt_maint == 0
    assert app.qds.results is app.original_result
    cases = app.report.tables["Cases"]["values"]
    assert cases[1, "assessment"] == gl.ASSESSMENT_NOT_EVALUATED
    assert "solver stopped" in cases[1, "assessment_detail"]
    quality = app.report.tables["ModelQuality"]["values"]
    assert any(value == "FAIL" for (index, field), value in quality.items() if field == "status")


def test_ignored_flag_that_cannot_be_restored_stops_the_run(monkeypatch):
    class Stubborn(PlannedOutage):
        def __setattr__(self, name, value):
            if name == "outserv" and self.__dict__.get("locked"):
                return
            super().__setattr__(name, value)

    stubborn = Stubborn("Outage B")
    other = PlannedOutage("Outage A")
    app = App((other, stubborn))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", False)
    original = app.qds.Execute

    def execute():
        stubborn.locked = True  # PowerFactory refuses to write the flag back
        return original()
    app.qds.Execute = execute

    with pytest.raises(gl.StateRestoreError, match="expected 0, read back 1"):
        gl.execute_gridlens(app)


def test_production_script_has_no_obsolete_runtime_dependencies():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "gridlens_pf", "IntScenario", "IntScheme", "GetActiveScenario",
        "SCAN_VARIATIONS", ".Activate(", ".Deactivate(", "traceback",
    )
    assert not [value for value in forbidden if value in text]


def test_user_facing_runtime_text_is_english():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "Zeitachse", "Auslastung", "Spannung", "Referenzfall",
        "Grenzwert", "Nicht konvergiert", "Freischaltung", "Ergebnisreihe",
    )
    assert not [value for value in forbidden if value in text]


def test_qds_result_reads_implicit_time_scale_from_column_minus_one():
    series, labels, plot_times, time_unit, absolute, _ = gl.collect_series(
        ImplicitTimeElmRes())

    assert absolute is False
    assert labels == ["00:00", "01:00"]
    assert plot_times == [0.0, 1.0]
    assert time_unit == "h"
    # Voltage angles are no longer read.
    assert {item["category"] for item in series} == {"line", "voltage"}


def test_friendly_exception_respects_suppressed_context():
    try:
        try:
            raise RuntimeError("low-level failure")
        except RuntimeError:
            raise gl.GridLensError("Readable operator message") from None
    except gl.GridLensError as exc:
        message = gl._friendly_exception(exc)

    assert message == "GridLensError: Readable operator message"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None), (True, None), (False, None), (float("nan"), None),
        (float("inf"), None), ("", None), ("1,25", 1.25), ("2.5", 2.5),
        (7, 7.0), ((0, 5), None),
    ],
)
def test_finite_number_rejects_special_and_ambiguous_values(value, expected):
    assert gl.finite_number(value) == expected


@pytest.mark.parametrize(
    ("returned", "expected"),
    [(None, 0.0), (0, 0.0), ((0, "detail"), 0.0), (3, 3.0), ([], None)],
)
def test_powerfactory_return_code_normalization(returned, expected):
    assert gl.return_code(returned) == expected


def _series(category, key, values):
    kind = {"line": "ElmLne", "transformer": "ElmTr2",
            "voltage": "ElmTerm", "voltage_angle": "ElmTerm"}[category]
    obj = PFObject(key, kind, uknom=110)
    variable = {"line": "c:loading", "transformer": "c:loading",
                "voltage": "m:u", "voltage_angle": "m:phiu"}[category]
    unit = "%" if category in ("line", "transformer") else (
        "p.u." if category == "voltage" else "deg")
    return {
        "category": category, "object": obj, "key": obj.GetFullName(),
        "element_id": key, "element_name": key, "voltage_level": "110 kV",
        "variable_id": variable, "variable": variable, "unit": unit,
        "points": [("00:00", 0.0, values[0]), ("01:00", 1.0, values[1])],
    }


def test_thresholds_are_strict_at_exact_limits():
    line = _series("line", "Line", [99.0, 100.0])
    voltage = _series("voltage", "Bus", [0.95, 1.05])
    assert gl.is_critical(line, gl.statistics(line)) is False
    assert gl.is_critical(voltage, gl.statistics(voltage)) is False
    line["points"][1] = ("01:00", 1.0, 100.0001)
    voltage["points"][0] = ("00:00", 0.0, 0.9499)
    assert gl.is_critical(line, gl.statistics(line)) is True
    assert gl.is_critical(voltage, gl.statistics(voltage)) is True


def test_reference_delta_requires_same_internal_object_key():
    reference_item = _series("line", "Shared name", [80.0, 90.0])
    outage_item = _series("line", "Shared name", [90.0, 110.0])
    outage_item["key"] = "Project\\Other\\Shared name.ElmLne"
    reference = gl.case_result(
        {"id": "REF", "name": "Reference", "out_of_service": []},
        [reference_item], ["00:00", "01:00"], [0.0, 1.0], "h")
    outage = gl.case_result(
        {"id": "OUTAGE", "name": "Outage", "out_of_service": []},
        [outage_item], ["00:00", "01:00"], [0.0, 1.0], "h")

    gl.apply_reference([reference, outage])

    stats = outage["by_category"]["line"][0][1]
    assert stats["ref_max"] is None
    assert stats["delta_max"] is None


def test_outages_are_classified_against_the_simulated_period():
    inside = PlannedOutage("Inside")
    before = PlannedOutage("Before", starttime=PERIOD_START - 172800,
                           endtime=PERIOD_START - 3600)
    after = PlannedOutage("After", starttime=PERIOD_END + 3600,
                          endtime=PERIOD_END + 172800)
    disabled = PlannedOutage("Disabled", disabled=True)
    app = App((inside, before, after, disabled))

    records, candidates = gl.classify_planned_outages(
        app, gl.RunLogger(app), (PERIOD_START, PERIOD_END))

    assert [record["name"] for record in candidates] == ["Inside"]
    statuses = {record["name"]: (record["status"], record["skip_reason"])
                for record in records}
    assert statuses["Inside"] == (gl.OUTAGE_CONSIDERED, "")
    assert "disabled" in statuses["Disabled"][1]
    assert "outside the simulated period" in statuses["Before"][1]
    assert "outside the simulated period" in statuses["After"][1]


def test_outage_touching_the_period_boundary_stays_in_scope():
    touching = PlannedOutage("Touching", starttime=PERIOD_END,
                             endtime=PERIOD_END + 86400)
    app = App((touching,))

    _, candidates = gl.classify_planned_outages(
        app, gl.RunLogger(app), (PERIOD_START, PERIOD_END))

    assert [record["name"] for record in candidates] == ["Touching"]


def test_unknown_period_keeps_every_enabled_outage_in_scope():
    app = App((PlannedOutage("Enabled"), PlannedOutage("Disabled", disabled=True)))

    records, candidates = gl.classify_planned_outages(app, gl.RunLogger(app))

    assert [record["name"] for record in candidates] == ["Enabled"]
    statuses = {record["name"]: record["status"] for record in records}
    assert statuses == {"Enabled": gl.OUTAGE_CONSIDERED,
                        "Disabled": gl.OUTAGE_SKIPPED}


def test_outage_without_a_readable_window_is_reported_with_its_surface():
    unreadable = PlannedOutage("Unreadable")
    del unreadable.starttime
    del unreadable.endtime
    app = App((unreadable,))

    records, candidates = gl.classify_planned_outages(
        app, gl.RunLogger(app), (PERIOD_START, PERIOD_END))

    assert [record["name"] for record in candidates] == ["Unreadable"]
    assert "could not be compared" in records[0]["skip_reason"]
    diagnostics = [line for line in app.messages if "DIAGNOSTIC" in line]
    assert len(diagnostics) == 1
    assert "class=IntPlannedout" in diagnostics[0]


def test_outage_in_scope_produces_no_diagnostic_noise():
    app = App((PlannedOutage("Inside"),))

    gl.classify_planned_outages(app, gl.RunLogger(app), (PERIOD_START, PERIOD_END))

    assert [line for line in app.messages if "DIAGNOSTIC" in line] == []


def test_duplicate_outage_names_receive_distinct_short_ids():
    first = PlannedOutage("Duplicate")
    second = PlannedOutage("Duplicate")
    second.GetFullName = lambda: "Project\\Other\\Duplicate.IntPlannedout"
    app = App((first, second))

    records, _ = gl.classify_planned_outages(app, gl.RunLogger(app))

    assert len({record["id"] for record in records}) == 2
    assert all(record["id"].startswith("Duplicate (") for record in records)


def test_only_planned_outages_are_read_not_demand_transfers():
    outage = PlannedOutage("FS Line A")
    transfer = PFObject("Demand transfer Load 1 -> Load 2", "IntOutage", outserv=0)
    transfer.starttime, transfer.endtime = OUTAGE_START, OUTAGE_END
    app = App((outage, transfer))
    asked = []
    contents = app._outage_contents
    app.outage_folder.GetContents = app.project.GetContents = lambda pattern, *args: asked.append(pattern) or contents(pattern, *args)

    records, _ = gl.classify_planned_outages(app, gl.RunLogger(app), (PERIOD_START, PERIOD_END))

    assert [record["name"] for record in records] == ["FS Line A"]
    assert gl.OUTAGE_CLASSES == ("IntPlannedout",) and set(asked) == {"*.IntPlannedout"}


def test_complete_outage_discovery_failure_is_not_reported_as_empty():
    app = App(())
    app.outage_folder.GetContents = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("folder unavailable"))
    app.project.GetContents = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("project unavailable"))

    with pytest.raises(gl.GridLensError, match="discovery could not query"):
        gl.classify_planned_outages(app, gl.RunLogger(app))


def test_equipment_is_read_from_the_components_attribute():
    line = PFObject("Line 09 - 39", "ElmLne", outserv=0)
    outage = PlannedOutage("Line 04 - 14", equipment=[line])

    equipment, kinds, _, start, end = gl._outage_details(outage)

    assert equipment == "Line 09 - 39"
    assert kinds == "ElmLne"
    assert start.startswith("2014-01-01")
    assert end.startswith("2014-01-01")


def test_qds_period_is_read_from_the_command():
    app = App(())

    assert gl.qds_period(app.qds) == (float(PERIOD_START), float(PERIOD_END))

    del app.qds.startTime
    assert gl.qds_period(app.qds) == (None, None)


def test_payload_validation_rejects_unknown_fields_and_booleans():
    payload = {name: [] for name, _ in gl.TABLES}
    payload["ScriptedReportMeta"] = [{
        "study_id": "S", "study_name": "S", "model_name": "M",
        "model_version": "PowerFactory 2026", "generation_date": "now",
        "generated_by": "user", "run_mode": "test",
        "template_name": gl.TEMPLATE_NAME,
        "template_version": gl.TEMPLATE_VERSION,
        "data_contract_version": gl.DATA_CONTRACT_VERSION,
        "result_name": "R", "assessment_scope": "test",
        "assessment_status": "test", "voltage_limits": "x",
        "has_cases": "0", "chart_cases": "1", "case_source_text": "x",
        "reference_text": "x", "qds_mode_text": "x", "coverage_statement": "x",
        "unknown": "bad",
    }]
    with pytest.raises(ValueError, match="unknown fields"):
        gl.validate_payload(payload)
    payload["ScriptedReportMeta"][0].pop("unknown")
    payload["ScriptedCases"] = [{
        "case_order": 0, "case_id": "REF", "case_name": "Reference",
        "is_reference": True, "simulation_status": "CONVERGED",
        "assessment": "BASELINE", "violation": 0,
    }]
    with pytest.raises(ValueError, match="boolean"):
        gl.validate_payload(payload)


class HostileObject(PFObject):
    """Outage whose attribute access fails the way a broken proxy would."""

    def __init__(self):
        super().__init__("Hostile", "IntPlannedout", outserv=0)

    def __getattr__(self, name):
        raise RuntimeError("attribute access exploded: " + name)


def test_api_description_separates_methods_from_parameters():
    description = gl.describe_object_api(PlannedOutage("Probe"))

    assert "class=IntPlannedout" in description
    methods, parameters = description.split("parameters:")
    assert "GetClassName" in methods
    assert "starttime" in parameters
    assert "endtime" in parameters
    assert "priority" in parameters
    assert "outserv" in parameters


def test_api_description_omits_methods_powerfactory_does_not_expose():
    # PowerFactory 2026 offers no Apply, Reset or Check on IntPlannedout.
    methods = gl.describe_object_api(
        PlannedOutage("Probe")).split("parameters:")[0]

    assert "Apply" not in methods
    assert "Reset" not in methods
    assert "IsInStudyTime" not in methods


def test_api_description_survives_objects_that_raise_on_access():
    description = gl.describe_object_api(HostileObject())

    assert isinstance(description, str)
    assert description


def test_api_description_reports_powerfactory_declared_attributes():
    outage = PlannedOutage("Probe")
    outage.GetAttributeNames = lambda: ["tEnd", "outserv"]
    outage.tEnd = 20140102

    description = gl.describe_object_api(outage)

    assert "declared attributes: outserv=0, tEnd=20140102" in description


def test_api_description_is_bounded_for_the_output_window():
    outage = PlannedOutage("Probe")
    for index in range(400):
        setattr(outage, "parameter_with_a_long_name_{}".format(index), index)

    assert len(gl.describe_object_api(outage)) <= gl.MAX_DIAGNOSTIC_LENGTH


def test_extraction_logs_the_time_axis_span(monkeypatch):
    app = App((PlannedOutage("Applicable"),))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    gl.execute_gridlens(app)

    spans = [line for line in app.messages if "Time axis" in line]
    assert spans
    assert "unit 'h'" in spans[0]
    assert "first 00:00" in spans[0]
    assert "last 01:00" in spans[0]


EPOCH_2014_06_15_12_UTC = 1402833600.0


class EpochTimeElmRes(ElmRes):
    """QDS result whose implicit time scale holds absolute epoch seconds.

    This is what PowerFactory 2026 returns for a quasi-dynamic run: the unit
    reads 's', but the values are not elapsed time since the simulation start.
    """

    def __init__(self, points=48):
        super().__init__()
        self.points = points
        self.variables = ("c:loading", "m:u", "m:phiu")
        self.objects = (self.line, self.term, self.term)
        self.units = ("%", "p.u.", "deg")
        self.scale = [EPOCH_2014_06_15_12_UTC + 3600.0 * index
                      for index in range(points)]
        self.columns = (
            [90.0 + index for index in range(points)],
            [0.96 for _ in range(points)],
            [0.0 for _ in range(points)],
        )

    def clone(self):
        return EpochTimeElmRes(self.points)

    def GetNumberOfRows(self):
        return self.points

    def GetValue(self, row, column):
        if column == -1:
            return self.scale[row]
        return self.columns[column][row]

    def GetUnit(self, column):
        return "s" if column == -1 else super().GetUnit(column)

    def GetColumnValues(self, *_args):
        raise TypeError("PowerFactory requires an IntVec argument")

    def FindColumn(self, *_args):
        return -1


def test_absolute_epoch_axis_is_detected():
    assert gl.is_absolute_time_axis([385703.0, 385704.0]) is True
    assert gl.is_absolute_time_axis([0.0, 1.0, 47.0]) is False
    assert gl.is_absolute_time_axis([]) is False


def test_epoch_axis_is_labelled_as_a_calendar_time():
    _, labels, _, _, absolute, _ = gl.collect_series(EpochTimeElmRes())

    assert absolute is True
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", labels[0])
    assert labels[0].startswith("2014-06-")
    assert "d " not in labels[0]


def test_epoch_axis_plot_times_are_relative_to_the_first_sample():
    _, _, plot_times, _, _, origin = gl.collect_series(EpochTimeElmRes())

    assert plot_times[0] == 0.0
    assert plot_times[-1] == pytest.approx(47.0)
    assert origin == pytest.approx(EPOCH_2014_06_15_12_UTC / 3600.0)


def test_relative_axis_keeps_elapsed_clock_labels():
    _, labels, plot_times, _, absolute, origin = gl.collect_series(ElmRes())

    assert absolute is False
    assert origin is None
    assert labels == ["00:00", "01:00"]
    assert plot_times == [0.0, 1.0]


def test_epoch_axis_span_is_reported_in_hours(monkeypatch):
    app = App((PlannedOutage("Applicable"),))
    app.original_result = EpochTimeElmRes()
    app.qds.startTime = EPOCH_2014_06_15_12_UTC
    app.qds.endTime = EPOCH_2014_06_15_12_UTC + 47 * 3600
    app.qds.results = app.original_result
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    gl.execute_gridlens(app)

    spans = [line for line in app.messages if "Time axis" in line]
    assert spans
    assert "span 47 h" in spans[0]
    assert "absolute" in spans[0]


def test_api_description_reads_attributes_through_getattributes():
    outage = PlannedOutage("Probe")
    outage.GetAttributes = lambda: ["tStart", "outserv"]
    outage.tStart = 20140101

    description = gl.describe_object_api(outage)

    assert "tStart=20140101" in description
    assert "outserv=0" in description


def test_study_time_renders_powerfactory_six_digit_clock():
    # PowerFactory stores SetTime.cTime as HHMMSS, so 230000 is 23:00:00.
    assert gl._format_study_time(20140102, 230000) == "2014-01-02 23:00:00"
    assert gl._format_study_time(20140102, 93000) == "2014-01-02 09:30:00"
    assert gl._format_study_time(20140102, 0) == "2014-01-02 00:00:00"
    assert gl._format_study_time("20140102", "230000") == "2014-01-02 23:00:00"


def test_study_time_rendering_survives_unreadable_values():
    assert "date=" in gl._format_study_time(None, 230000)


def test_outage_times_are_rendered_compactly_for_the_report():
    # The report cell is 3.1 cm wide; ISO with a timezone offset does not fit,
    # and the time-axis labels already read this way.
    assert gl._format_pf_time(OUTAGE_START) == "2014-01-01 00:00"
    assert gl._format_pf_time(OUTAGE_END) == "2014-01-01 23:59"


def test_outage_time_rendering_leaves_other_values_alone():
    assert gl._format_pf_time("2014-01-01") == "2014-01-01"
    assert gl._format_pf_time(None) == ""
    assert gl._format_pf_time(42) == "42"


WINDOW_HOURS = [392000.0, 392001.0]
WINDOW_LABELS = ["2014-01-01 07:00", "2014-01-01 08:00"]


def _window_result(case_id, series):
    """A converged case on a two-step absolute axis; series are (category, name, values)."""
    items = []
    for category, name, values in series:
        item = {"category": category, "key": name, "element_id": name, "element_name": name, "voltage_level": "345 kV",
                "unit": "p.u." if category == "voltage" else "%", "variable": "Loading",
                "limits": (0.95, 1.05) if category == "voltage" else None,
                "points": [(WINDOW_LABELS[i], float(i), value) for i, value in enumerate(values)]}
        item["statistics"] = gl.statistics(item)
        item["values"] = gl.value_array(values)
        items.append(item)
    return gl.case_result({"id": case_id, "name": case_id, "hours": WINDOW_HOURS, "absolute": True},
                          items, WINDOW_LABELS, [0.0, 1.0], "h")


def _judge(reference_series, case_series, window=(WINDOW_HOURS[0] * 3600.0, (WINDOW_HOURS[1] + 1) * 3600.0)):
    reference = _window_result("REF", reference_series) if reference_series is not None else None
    case = _window_result("OUT01", case_series)
    gl.compare_case(case, reference, [window])
    results = ([reference] if reference else []) + [case]
    return gl.assess_case(results, case)


def test_overload_inside_the_window_is_reported_with_its_element():
    judged = _judge([("line", "Line A", [50.0, 96.1])], [("line", "Line A", [60.0, 112.4])])

    assert judged['assessment'] == gl.ASSESSMENT_LOADING
    assert judged['violation'] == 1
    assert judged['max_loading'] == 112.4
    assert judged['max_loading_element'] == 'Line A'
    assert judged['reference_max_loading'] == 96.1
    detail = gl.assessment_detail(judged)
    assert detail.startswith("Loading max 112.4 % on Line A at 2014-01-01 08:00 (REF 96.1 %)")
    assert "largest coincident increase +16.3 pp" in detail
    assert "1 overload: 1 new" in detail


def test_voltage_band_violation_is_reported_separately():
    judged = _judge([("line", "Line A", [50.0, 80.0]), ("voltage", "Bus 7", [1.0, 1.0])],
                    [("line", "Line A", [50.0, 80.0]), ("voltage", "Bus 7", [0.931, 1.01])])

    assert judged['assessment'] == gl.ASSESSMENT_VOLTAGE
    assert judged['violation'] == 1
    assert judged['min_voltage'] == 0.931
    detail = gl.assessment_detail(judged)
    # Loading comes first, voltage second.
    assert detail.index("Loading") < detail.index("Voltage 0.931 to 1.010 p.u.")
    assert "1 node outside the band" in detail


def test_both_kinds_of_violation_are_named_together():
    judged = _judge([("line", "Line A", [50.0, 80.0]), ("voltage", "Bus 7", [1.0, 1.0])],
                    [("line", "Line A", [50.0, 130.0]), ("voltage", "Bus 7", [0.90, 1.09])])

    assert judged['assessment'] == gl.ASSESSMENT_BOTH


def test_clean_window_is_reported_as_no_limit_exceeded():
    judged = _judge([("line", "Line A", [50.0, 90.0]), ("voltage", "Bus 7", [1.0, 1.0])],
                    [("line", "Line A", [50.0, 100.0]), ("voltage", "Bus 7", [0.95, 1.05])])

    # Values exactly on the limit are not violations.
    assert judged['assessment'] == gl.ASSESSMENT_OK
    assert judged['violation'] == 0


def test_pre_existing_violation_is_no_additional_violation():
    judged = _judge([("line", "Line A", [101.0, 103.0])], [("line", "Line A", [101.0, 103.05])])

    assert judged['assessment'] == gl.ASSESSMENT_PREEXISTING
    assert judged['violation'] == 2


def test_window_with_no_result_rows_is_not_assessed():
    window = ((WINDOW_HOURS[1] + 5) * 3600.0, (WINDOW_HOURS[1] + 6) * 3600.0)

    assert _judge([("line", "Line A", [50.0, 50.0])], [("line", "Line A", [50.0, 50.0])], window) is None


def test_report_row_carries_the_verdict_for_each_outage(monkeypatch):
    app = App((PlannedOutage("Outage A"),))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    gl.execute_gridlens(app)

    values = app.report.tables["Cases"]["values"]
    assert values[0, "case_name"] == "Reference"
    assert values[0, "assessment"] == "BASELINE"
    assert values[1, "case_name"] == "Outage A"
    assert values[1, "priority"] == 1
    assert values[1, "assessment"] in (
        gl.ASSESSMENT_OK, gl.ASSESSMENT_LOADING, gl.ASSESSMENT_VOLTAGE,
        gl.ASSESSMENT_BOTH, gl.ASSESSMENT_NO_DATA, gl.ASSESSMENT_PREEXISTING)
    assert (1, "assessment_detail") in values


def test_skipped_outage_shows_its_reason_as_the_detail(monkeypatch):
    app = App((PlannedOutage("Disabled", disabled=True),))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    gl.execute_gridlens(app)

    values = app.report.tables["Cases"]["values"]
    assert values[1, "assessment"] == gl.ASSESSMENT_SKIPPED
    assert values[1, "violation"] == 0
    assert "disabled" in values[1, "assessment_detail"]


def _publication_payload():
    payload = gl.build_cases_payload(
        PFObject("Study", "IntCase"), [], "Model", "Result", [],
        "operator", "TEST")
    payload["ScriptedCases"] = [
        {"case_order": index, "case_id": "C{}".format(index),
         "case_name": "Case", "is_reference": 0,
         "simulation_status": "CONVERGED", "assessment": "BASELINE",
         "violation": 0}
        for index in range(10)
    ]
    return payload


def test_publication_heartbeat_reports_progress_without_changing_data(monkeypatch):
    payload = _publication_payload()
    expected = Report()
    gl.publish_report(expected, payload)
    clock = [0.0]
    monkeypatch.setattr(gl.time, "monotonic", lambda: clock[0])
    messages = []

    class SlowReport(Report):
        def CreateField(self, *args):
            clock[0] += 1.0
            return super().CreateField(*args)

        def SetValue(self, *args):
            clock[0] += 1.0
            return super().SetValue(*args)

    report = SlowReport()
    counts = gl.publish_report(
        report, payload,
        log=lambda message: messages.append((clock[0], message)))

    assert report.tables == expected.tables
    assert report.reset_calls == 1
    assert counts["ScriptedCases"] == 10
    heartbeats = [(stamp, message) for stamp, message in messages
                  if "Publication heartbeat:" in message]
    assert any("CREATE FIELDS" in message for _, message in heartbeats)
    assert any("WRITE CELLS" in message and "Cases" in message
               and "rows complete" in message for _, message in heartbeats)
    assert all(right[0] - left[0] >= 5.0
               for left, right in zip(heartbeats, heartbeats[1:]))
    for previous, current in zip(messages, messages[1:]):
        assert current[0] - previous[0] <= 5.0
    assert any("cells/s" in message for _, message in messages)
    assert "Publication finished:" in messages[-1][1]


def test_publication_times_reset_and_announces_it_before_blocking(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(gl.time, "monotonic", lambda: clock[0])
    messages = []

    class SlowResetReport(Report):
        def Reset(self):
            assert messages[-1] == "Resetting report database."
            clock[0] += 12.0
            return super().Reset()

    report = SlowResetReport()
    gl.publish_report(report, _publication_payload(), log=messages.append)

    assert "Report database reset completed in 12.0s." in messages
    assert report.reset_calls == 1


def test_publication_validation_failure_does_not_reset_or_claim_validated():
    report = Report()
    messages = []
    payload = _publication_payload()
    payload["ScriptedCases"][0]["is_reference"] = True

    with pytest.raises(ValueError, match="boolean"):
        gl.publish_report(report, payload, log=messages.append)

    assert report.reset_calls == 0
    assert messages == ["Validating report tables before publication."]


def test_publication_write_failure_keeps_cell_context_and_clears_partial_data():
    class FailingReport(Report):
        def SetValue(self, table, field, row, value):
            if table == "Cases" and row == 2:
                return 7
            return super().SetValue(table, field, row, value)

    report = FailingReport()
    messages = []
    with pytest.raises(RuntimeError, match=r"SetValue\(Cases.case_order, row 2\)"):
        gl.publish_report(report, _publication_payload(), log=messages.append)

    assert report.reset_calls == 2
    assert report.tables == {}
    assert not any("Publication finished:" in message for message in messages)


def _check_emitted_report_against_mrt(report):
    """Replay recorded IntReport writes into SQLite, not the TABLES constant.

    The host's single Scripted prefix and field type mapping are modeled here;
    this does not exercise PowerFactory's export/merge or Stimulsoft compiler.
    """
    root = ET.parse(ROOT / "powerfactory" / "MASTER_GRIDLENS.mrt").getroot()
    sources = list(root.find("./Dictionary/DataSources"))
    emitted = {"Scripted" + name: table
               for name, table in report.tables.items()}
    assert set(emitted) == {source.findtext("Name") for source in sources}
    sql_types = {0: "TEXT", 1: "INTEGER", 2: "REAL"}
    mrt_types = {"System.String": "TEXT", "System.Int32": "INTEGER",
                 "System.Double": "REAL"}

    def quote(identifier):
        return '"' + identifier.replace('"', '""') + '"'

    db = sqlite3.connect(":memory:")
    try:
        for name, table in emitted.items():
            fields = table["fields"]
            definition = ", ".join(
                "{} {}".format(quote(field), sql_types[kind])
                for field, kind in fields.items())
            db.execute("CREATE TABLE {} ({})".format(quote(name), definition))
            row_indices = sorted({index for index, _ in table["values"]})
            for index in row_indices:
                values = [table["values"].get((index, field)) for field in fields]
                db.execute("INSERT INTO {} VALUES ({})".format(
                    quote(name), ", ".join("?" for _ in fields)), values)

        for source in sources:
            name = source.findtext("Name")
            expected = []
            for column in source.findall("./Columns/value"):
                field, kind = column.text.split(",", 1)
                expected.append((field, mrt_types[kind]))
            actual = [(row[1], row[2]) for row in
                      db.execute("PRAGMA table_info({})".format(quote(name)))]
            assert actual == expected, "Emitted fields do not match MRT: " + name
            cursor = db.execute(source.findtext("SqlCommand"))
            assert [column[0] for column in cursor.description] == [
                field for field, _ in expected]
            cursor.fetchall()

        # Includes group conditions, chart expressions, encoded filters and
        # highlighting rules, not just visible Text components.
        for element in root.iter():
            decoded = re.sub(
                r"_x([0-9A-Fa-f]{4})_",
                lambda match: chr(int(match[1], 16)), element.text or "")
            for table, field in re.findall(r"\b(Scripted\w+)\.(\w+)\b", decoded):
                assert table in emitted, "Unknown expression table: " + table
                assert field in emitted[table]["fields"], (
                    "Unknown expression field: {}.{}".format(table, field))
            if element.tag == "DataSourceName" and decoded:
                assert decoded in emitted, "Unknown data band source: " + decoded

        sources_by_ref = {source.attrib["Ref"]: source.findtext("Name")
                          for source in sources}
        for relation in root.findall("./Dictionary/Relations/*"):
            for side in ("Parent", "Child"):
                reference = relation.find(side + "Source").attrib["isRef"]
                fields = emitted[sources_by_ref[reference]]["fields"]
                for column in relation.findall("./" + side + "Columns/value"):
                    assert column.text in fields
    finally:
        db.close()


@pytest.mark.parametrize("reference,enabled", [
    (True, True), (False, True), (True, False), (False, False),
])
def test_executed_publisher_output_matches_mrt_and_all_sql_queries(
        monkeypatch, reference, enabled):
    app = App((PlannedOutage("Outage A", disabled=not enabled),))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", reference)
    gl.execute_gridlens(app)

    _check_emitted_report_against_mrt(app.report)

    # Empty tables must still expose the full schema during rendering.
    if not reference and not enabled:
        assert app.report.tables["CaseComparison"]["values"] == {}
        assert app.report.tables["CaseComparison"]["fields"]["block"] == 1
    outage = app.report.tables["Cases"]
    assert outage["fields"]["priority"] == 1
    assert outage["fields"]["violation"] == 1
    assert outage["fields"]["assessment"] == 0
    assert outage["fields"]["assessment_detail"] == 0
    for field in ("priority", "violation", "assessment", "assessment_detail"):
        assert (0, field) in outage["values"]


@pytest.mark.parametrize("table,field", [
    ("Cases", "priority"),
    ("Cases", "violation"),
    ("Cases", "assessment"),
    ("Cases", "assessment_detail"),
    ("Cases", None),
    ("CaseComparison", None),
    ("CalculationRuns", "result_object"),
    ("AppendixVoltage", None),
])
def test_emitted_schema_check_catches_missing_tables_and_fields_from_export_log(
        monkeypatch, table, field):
    app = App((PlannedOutage("Outage A"),))
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)
    gl.execute_gridlens(app)
    if field is None:
        del app.report.tables[table]
    else:
        del app.report.tables[table]["fields"][field]

    with pytest.raises(AssertionError):
        _check_emitted_report_against_mrt(app.report)






def test_leftover_gridlens_result_is_used_as_configured_with_a_warning(monkeypatch):
    # A run aborted mid-calculation can leave ComStatsim.results bound to one
    # of its own result objects. That object is a full copy of the variable
    # selection, and every run calculates into a fresh copy, so GridLens
    # calculates with the stored settings instead of refusing to run.
    app = App((PlannedOutage("Outage"),))
    leftover = app.original_result
    leftover.loc_name = "GridLens_260928-145610_REF"
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    counts = gl.execute_gridlens(app)

    assert app.qds.execute_calls == 2
    assert counts["ScriptedCases"] == 2
    assert app.qds.results is leftover, "the stored binding must come back"
    assert leftover.deleted is False, "GridLens deletes no result object"
    warnings = [line for line in app.messages
                if "WARNING" in line and "GridLens_260928-145610_REF" in line]
    assert len(warnings) == 1
    assert "not changed" in warnings[0]



D7_GRID = PFObject("D7 Westnetz", "ElmNet")
FOREIGN_GRID = PFObject("NL TenneT", "ElmNet")


class ScopedElmRes(ElmRes):
    """One D7 line, one foreign line and one D7 bus; counts value reads.

    The names deliberately do not contain D7: the scope is decided by the
    element's grid (PowerFactory attribute cpGrid), not by its name.
    """

    def __init__(self):
        super().__init__()
        self.own = PFObject("Ltg Bollenacker", "ElmLne", outserv=0, uknom=110, cpGrid=D7_GRID)
        self.foreign = PFObject("Line 380", "ElmLne", outserv=0, uknom=380, cpGrid=FOREIGN_GRID)
        self.bus = PFObject("Sammelschiene 3", "ElmTerm", outserv=0, uknom=110, cpGrid=D7_GRID)
        self.variables = ("b:tnow", "c:loading", "c:loading", "m:u")
        self.objects = (self.time, self.own, self.foreign, self.bus)
        self.units = ("h", "%", "%", "p.u.")
        self.columns = ([0.0, 1.0], [90.0, 95.0], [383.4, 383.4], [0.99, 1.0])
        self.reads = []

    def clone(self):
        return ScopedElmRes()

    def GetColumnValues(self, column):
        self.reads.append(column)
        return super().GetColumnValues(column)


def test_scope_is_decided_by_the_grid_not_the_name(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "D7")

    assert gl.element_in_scope(PFObject("Ltg Bollenacker", "ElmLne", cpGrid=D7_GRID))
    assert not gl.element_in_scope(PFObject("D7_L12", "ElmLne", cpGrid=FOREIGN_GRID))
    assert gl.element_grid_name(PFObject("x", "ElmLne", cpGrid=D7_GRID)) == "D7 Westnetz"


def test_grid_falls_back_to_the_elmnet_in_the_element_path(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "D7")
    element = PFObject("Ltg 5", "ElmLne")
    element.GetFullName = lambda: ("\\User\\Model.IntPrj\\Network Model.IntPrjfolder\\"
                                   "Network Data.IntPrjfolder\\D7 Westnetz.ElmNet\\Ltg 5.ElmLne")

    assert gl.element_grid_name(element) == "D7 Westnetz"
    assert gl.element_in_scope(element)


def test_element_without_any_grid_is_out_of_scope(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "D7")

    assert gl.element_grid_name(PFObject("D7 orphan", "ElmLne")) == ""
    assert not gl.element_in_scope(PFObject("D7 orphan", "ElmLne"))


def test_empty_grid_filter_assesses_every_element(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "")

    assert gl.element_in_scope(PFObject("Line 380", "ElmLne", cpGrid=FOREIGN_GRID))


def test_foreign_elements_are_neither_assessed_nor_read(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "D7")
    result = ScopedElmRes()
    counters = {}

    series = gl.collect_series(result, counters=counters)[0]

    assert sorted(item["element_name"] for item in series) == [
        "Ltg Bollenacker", "Sammelschiene 3"]
    assert 2 not in result.reads, "the foreign line's values must not be read"
    assert counters["out_of_scope"] == 1


def test_no_element_in_scope_names_the_filter(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "D9")

    with pytest.raises(RuntimeError, match="GRID_NAME_FILTER") as failure:
        gl.collect_series(ScopedElmRes())
    # The message says which grids the result file does hold.
    assert "Grids in the result:" in str(failure.value)


def test_report_states_which_elements_were_assessed(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "D7")
    app = App(())
    app.original_result = ScopedElmRes()
    app.qds.results = app.original_result
    app.study.AddCopy = lambda result: ScopedElmRes()
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    gl.execute_gridlens(app)

    scope = app.report.tables["ReportMeta"]["values"][0, "assessment_scope"]
    assert "grids named *D7*" in scope
    assert any("Grid scope 'D7': 2 series assessed, 1 out of scope" in line
               for line in app.messages)





























# --- Loading first, statuses against REF, names only ---------------------









def test_long_text_is_shortened_with_an_ellipsis_not_a_hash():
    assert gl.clip_text('x' * 90, 80) == 'x' * 79 + '…'
    # A list of switched equipment keeps every name readable.
    assert gl.text_limit('equipment_name') == gl.MAX_TEXT_LENGTH




def test_voltage_band_follows_the_nominal_voltage():
    lower, upper = gl.voltage_band(380.0)
    assert (lower * 380.0, upper * 380.0) == pytest.approx((360.0, 420.0))
    # 1.094 p.u. at 380 kV is 415.7 kV and inside the band.
    item = {'category': 'voltage', 'limits': gl.voltage_band(380.0)}
    assert not gl.is_critical(item, {'min': 1.0, 'max': 1.094})
    assert gl.is_critical(item, {'min': 1.0, 'max': 1.121})
    # 1.127 p.u. at 110 kV is 124 kV, above 123 kV.
    item = {'category': 'voltage', 'limits': gl.voltage_band(110.0)}
    assert gl.is_critical(item, {'min': 1.0, 'max': 1.127})
    # Unknown levels keep the p.u. band.
    assert gl.voltage_band(None) == (gl.VOLTAGE_MIN, gl.VOLTAGE_MAX)
    assert gl.voltage_band(20.0) == (gl.VOLTAGE_MIN, gl.VOLTAGE_MAX)


class VoltageElmRes(ElmRes):
    """An AC bus that is de-energised for one step, a dead bus, a DC bus."""

    def __init__(self):
        super().__init__()
        self.ac = PFObject("Bus AC", "ElmTerm", uknom=110, systype=0)
        self.dead = PFObject("Bus dead", "ElmTerm", uknom=110, systype=0)
        self.dc = PFObject("Bus DC", "ElmTerm", uknom=320, systype=1)
        self.variables = ("b:tnow", "m:u", "m:u", "m:u")
        self.objects = (self.time, self.ac, self.dead, self.dc)
        self.units = ("h", "p.u.", "p.u.", "p.u.")
        self.columns = ([0.0, 1.0], [1.01, 0.0], [0.0, 0.0], [-1.01, -1.0])


def test_zero_and_dc_voltages_are_not_counted_as_violations():
    counters = {}

    series = gl.collect_series(VoltageElmRes(), counters=counters)[0]

    (bus,) = series
    assert bus['element_name'] == 'Bus AC'
    assert (bus['statistics']['min'], bus['statistics']['max']) == (1.01, 1.01)
    assert counters['dc_nodes'] == 1
    assert counters['deenergized_nodes'] == 1
    assert counters['deenergized_steps'] == 3


def test_run_output_is_structured_in_steps_cases_and_tables(monkeypatch):
    outages = (PlannedOutage("Outage A", equipment=[PFObject("Line A", "ElmLne")]),
               PlannedOutage("Outage B", disabled=True))
    app = App(outages)
    monkeypatch.setattr(gl, "RUN_REFERENCE_CASE", True)

    gl.execute_gridlens(app)

    text = "\n".join(app.messages)
    for step in ("STEP 1/7 \u00b7 Startup and context", "STEP 2/7 \u00b7 ComStatsim settings",
                 "STEP 3/7 \u00b7 Planned outages and planning cases", "STEP 4/7 \u00b7 Calculation and extraction",
                 "STEP 6/7 \u00b7 Restore and clean-up",
                 "STEP 7/7 \u00b7 Results and report publication"):
        assert step in text
    assert text.index("STEP 3/7") < text.index("STEP 4/7") < text.index("STEP 6/7") < text.index("STEP 7/7")
    assert ".. Case REF \u00b7 Reference" in text
    assert ".. Case OUT01 \u00b7 Outage A" in text
    assert "Outages: Outage A (" in text
    assert "Planning cases from: one case per planned outage in the simulated period" in text
    # Tables: outages, series per case, results per case, published tables.
    for heading in ("Planned outage  Status", "Result series  Count", "Case   Name", "Table  Rows"):
        assert heading.split("  ")[0] in text
    assert "Grids in the result file" in text
    assert "SKIPPED" in text and "CONSIDERED" in text
    assert not any("LODF" in line for line in app.messages)
    assert "Kept result object 'GridLens_" in text


class NanVoltageElmRes(VoltageElmRes):
    """An outage cuts the bus off: PowerFactory writes NaN instead of 0."""

    def __init__(self):
        super().__init__()
        self.columns = ([0.0, 1.0], [1.01, float("nan")], [0.0, 0.0], [-1.01, -1.0])


def test_nan_voltage_is_a_de_energised_node_and_does_not_stop_the_case():
    counters = {}

    (bus,) = gl.collect_series(NanVoltageElmRes(), counters=counters)[0]

    assert bus['element_name'] == 'Bus AC'
    assert (bus['statistics']['min'], bus['statistics']['max']) == (1.01, 1.01)
    assert counters['deenergized_steps'] == 3


def test_nan_loading_still_stops_the_extraction():
    result = ElmRes()
    result.columns = ([0.0, 1.0], [90.0, float("nan")], [0.96, 0.94], [0.0, 2.0])

    with pytest.raises(RuntimeError, match="Invalid result value"):
        gl.collect_series(result)


def test_a_result_object_without_loading_or_voltage_says_what_is_missing_and_what_to_do():
    result = ElmRes()
    load = PFObject("Load 1", "ElmLod", outserv=0)
    result.variables = ("b:tnow", "m:P:bus1", "m:Q:bus1", "m:phiu")
    result.objects = (result.time, load, load, result.term)
    result.units = ("h", "MW", "Mvar", "deg")
    result.columns = ([0.0, 1.0], [5.0, 6.0], [1.0, 1.0], [0.0, 2.0])

    with pytest.raises(RuntimeError) as raised:
        gl.collect_series(result)

    message = str(raised.value)
    assert "records none of the results GridLens assesses" in message
    assert "c:loading" in message and "m:u" in message, "names what is needed"
    assert "ElmLod m:P:bus1 (1 column)" in message and "ElmTerm m:phiu (1 column)" in message, "names what is there"
    assert "b:tnow" not in message, "the time column is no result"
    assert "Result Variables" in message, "says what to do"


def test_a_run_without_publication_says_that_the_report_cannot_be_generated(monkeypatch):
    import sys
    import types
    app = App((PlannedOutage("FS1"),))

    def angles_only():
        copy = ElmRes(app.original_result.loc_name)
        copy.variables, copy.objects = ("b:tnow", "m:phiu"), (copy.time, copy.term)
        copy.units, copy.columns = ("h", "deg"), ([0.0, 1.0], [0.0, 2.0])
        return copy
    app.original_result.clone = angles_only
    monkeypatch.setitem(sys.modules, "powerfactory", types.SimpleNamespace(GetApplication=lambda: app))

    assert gl.main() is False

    failed = [line for line in app.messages if "FAILED" in line]
    assert failed and "No report tables were published" in failed[-1] and "ReportsNet.log" in failed[-1]
    assert app.report.tables == {}, "nothing was published"


def test_cancel_or_a_failure_ends_the_script_with_an_error_code_so_no_report_is_rendered(monkeypatch):
    import runpy
    import sys
    import types
    monkeypatch.setitem(sys.modules, "powerfactory", types.SimpleNamespace(GetApplication=lambda: None))

    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert stopped.value.code == gl.NO_REPORT_EXIT_CODE == 1
    assert gl.exit_code(True) == 0 and gl.exit_code(False) == 1


def test_cancel_says_that_the_report_is_not_generated(monkeypatch):
    import sys
    import types
    app = App((PlannedOutage("FS1"),))
    monkeypatch.setitem(sys.modules, "powerfactory", types.SimpleNamespace(GetApplication=lambda: app))

    def cancelled(_app):
        raise gl.GridLensCancelled("Cancelled in the case manager. Nothing was calculated and nothing was changed.")
    monkeypatch.setattr(gl, "execute_gridlens", cancelled)

    # The cancellation reaches PowerFactory as an error, so an IntReport stops before it renders.
    with pytest.raises(gl.GridLensCancelled):
        gl.main()
    line = [message for message in app.messages if "CANCELLED" in message][-1]
    assert "Report generation cancelled" in line
    assert app.report.tables == {}


def test_a_successful_run_names_the_report_to_generate():
    app = App((PlannedOutage("FS1"),))

    gl.execute_gridlens(app)

    assert any("Generate the report now from the IntReport '{}'".format(app.report.loc_name) in line
               for line in app.messages)


def test_a_result_object_with_only_dead_terminals_says_so():
    result = ElmRes()
    result.variables = ("b:tnow", "m:u")
    result.objects = (result.time, result.term)
    result.units = ("h", "p.u.")
    result.columns = ([0.0, 1.0], [0.0, float("nan")])

    with pytest.raises(RuntimeError, match="all 1 recorded terminal voltages are 0 or not a number"):
        gl.collect_series(result)


def test_an_unusable_result_object_is_named_in_the_run_error():
    app = App((PlannedOutage("FS1"),))

    def angles_only():
        copy = ElmRes(app.original_result.loc_name)
        copy.variables, copy.objects = ("b:tnow", "m:phiu"), (copy.time, copy.term)
        copy.units, copy.columns = ("h", "deg"), ([0.0, 1.0], [0.0, 2.0])
        return copy
    app.original_result.clone = angles_only

    with pytest.raises(gl.GridLensError) as raised:
        gl.execute_gridlens(app)

    assert "was calculated, but GridLens cannot use its result object GridLens_" in str(raised.value)
    assert "records none of the results GridLens assesses" in str(raised.value)


# ---------------------------------------------------------------------------
# Planning cases through the complete run
# ---------------------------------------------------------------------------
def _key(outage):
    return outage.GetFullName()


def _save_cases(cases, **extra):
    config = gl.empty_case_config()
    config["cases"] = cases
    config.update(extra)
    gl.save_case_config(gl.case_config_path(_key(App().project)), config, "operator")


def test_a_case_with_two_outages_runs_them_together(monkeypatch):
    outages = (PlannedOutage("FS1"), PlannedOutage("FS2"), PlannedOutage("FS3"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    _save_cases([{"id": "A", "name": "Case A", "outages": [_key(outages[0]), _key(outages[1])]}])

    gl.execute_gridlens(app)

    assert app.qds.outage_options == [0, 1]
    assert app.qds.active_outages[1] == ["FS1", "FS2"], "FS3 is not part of the case"
    assert [item.outserv for item in outages] == [0, 0, 0]
    cases = app.report.tables["Cases"]["values"]
    assert cases[1, "case_name"] == "Case A"
    assert cases[1, "outage_names"] == "FS1, FS2"


def test_saved_legacy_relations_become_independent_case_runs(monkeypatch):
    import json

    outages = (PlannedOutage("FS1"), PlannedOutage("FS2"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    data = gl.empty_case_config()
    data.update(schema_version=1, exclusive_groups=[["A", "B"]], cases=[
        {"id": "A", "name": "North", "outages": [_key(outages[0])]},
        {"id": "B", "name": "South", "outages": [_key(outages[1])], "requires": ["A"]},
        {"id": "AB", "name": "Both", "outages": [], "includes": ["A", "B"]},
    ])
    path = gl.case_config_path(_key(app.project))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(data)
    Path(path).write_text(original)

    gl.execute_gridlens(app)

    assert app.qds.active_outages == [["FS1", "FS2"], ["FS1"], ["FS2"], ["FS1", "FS2"]]
    assert app.qds.outage_options == [0, 1, 1, 1]
    assert Path(path).read_text() == original
    assert any("Cases are now independent" in line for line in app.messages)
    assert app.report.tables["Cases"]["values"][3, "case_name"] == "Both"


def test_identical_cases_are_calculated_once_and_say_so(monkeypatch):
    outages = (PlannedOutage("FS1"), PlannedOutage("FS2"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    keys = [_key(item) for item in outages]
    _save_cases([{"id": "A", "name": "A", "outages": keys}, {"id": "B", "name": "B", "outages": keys[::-1]}])

    gl.execute_gridlens(app)

    assert app.qds.execute_calls == 2  # REF and A; B reuses A
    runs = app.report.tables["CalculationRuns"]["values"]
    assert runs[2, "run_kind"] == "CASE (reused)"
    assert runs[2, "provenance_text"].startswith("REUSED from A")


def test_fixed_outages_stay_active_in_the_reference_and_every_case(monkeypatch):
    outages = (PlannedOutage("FS0"), PlannedOutage("FS1"), PlannedOutage("FS2"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    _save_cases([{"id": "N", "name": "New FS1", "outages": [_key(outages[1])]}], background=[_key(outages[0])])

    gl.execute_gridlens(app)

    assert app.qds.outage_options == [1, 1]
    assert app.qds.active_outages == [["FS0"], ["FS0", "FS1"]]
    assert app.qds.iopt_maint == 0 and [item.outserv for item in outages] == [0, 0, 0]
    meta = app.report.tables["ReportMeta"]["values"]
    assert meta[0, "reference_text"] == "Rfix: fixed outages FS0"


def test_v30_cancel_in_the_case_manager_changes_and_calculates_nothing(monkeypatch):
    app = App((PlannedOutage("FS1"),))
    monkeypatch.setattr(gl, "CASE_SOURCE", "gui")
    monkeypatch.setattr(gl, "run_case_manager", lambda *args, **kwargs: None)

    with pytest.raises(gl.GridLensCancelled):
        gl.execute_gridlens(app)

    assert app.qds.execute_calls == 0
    assert app.study.copies == []
    assert app.report.reset_calls == 0


@pytest.mark.parametrize("previous_report", [False, True])
def test_cancel_reaches_the_report_caller_instead_of_returning_success(monkeypatch, previous_report):
    import sys
    import types
    from copy import deepcopy

    app = App((PlannedOutage("FS1"),))
    if previous_report:
        gl.execute_gridlens(app)
    tables = deepcopy(app.report.tables)
    reset_calls = app.report.reset_calls
    execute_calls = app.qds.execute_calls
    copies = list(app.study.copies)
    original_clock = (app.study_time.cDate, app.study_time.cTime)
    monkeypatch.setitem(sys.modules, "powerfactory", types.SimpleNamespace(GetApplication=lambda: app))
    monkeypatch.setattr(gl, "CASE_SOURCE", "gui")
    monkeypatch.setattr(gl, "run_case_manager", lambda *args, **kwargs: None)

    with pytest.raises(gl.GridLensCancelled):
        gl.main()

    assert app.qds.execute_calls == execute_calls
    assert app.study.copies == copies
    assert app.report.reset_calls == reset_calls
    assert app.report.tables == tables, "Cancel must neither publish nor overwrite an earlier report"
    assert app.qds.results is app.original_result
    assert app.qds.iopt_maint == 0 and app.outages[0].outserv == 0
    assert (app.study_time.cDate, app.study_time.cTime) == original_clock
    assert "CANCELLED" in app.messages[-1] and "Report generation cancelled" in app.messages[-1]
    assert "ReportsNet.log" not in app.messages[-1]
    assert not any("FAILED" in line for line in app.messages)


def test_main_still_returns_success_after_publishing_a_report(monkeypatch):
    import sys
    import types

    app = App((PlannedOutage("FS1"),))
    monkeypatch.setitem(sys.modules, "powerfactory", types.SimpleNamespace(GetApplication=lambda: app))

    assert gl.main() is True
    assert app.report.reset_calls == 1
    assert app.report.tables


def test_v31_without_tkinter_the_saved_configuration_is_used(monkeypatch):
    outages = (PlannedOutage("FS1"), PlannedOutage("FS2"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "gui")
    _save_cases([{"id": "A", "name": "A", "outages": [_key(outages[1])]}])

    def unavailable(*_args, **_kwargs):
        raise gl.CaseManagerUnavailable("no display")
    monkeypatch.setattr(gl, "run_case_manager", unavailable)

    gl.execute_gridlens(app)

    assert app.qds.active_outages[1] == ["FS2"]
    assert any("Using the saved configuration revision 1" in line for line in app.messages)


def test_v31_without_tkinter_and_without_configuration_falls_back_to_one_case_per_outage(monkeypatch):
    app = App((PlannedOutage("FS1"), PlannedOutage("FS2")))
    monkeypatch.setattr(gl, "CASE_SOURCE", "gui")

    def unavailable(*_args, **_kwargs):
        raise gl.CaseManagerUnavailable("no display")
    monkeypatch.setattr(gl, "run_case_manager", unavailable)

    gl.execute_gridlens(app)

    assert app.qds.active_outages[1:] == [["FS1"], ["FS2"]]
    meta = app.report.tables["ReportMeta"]["values"]
    assert "case manager unavailable" in meta[0, "case_source_text"]


def test_case_with_a_rule_conflict_is_reported_and_not_calculated(monkeypatch):
    outages = (PlannedOutage("FS1"), PlannedOutage("FS2"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    keys = [_key(item) for item in outages]
    _save_cases([{"id": "A", "name": "A", "outages": keys}],
                rules=[{"kind": "not_overlap", "first": keys[0], "second": keys[1]}])

    gl.execute_gridlens(app)

    assert app.qds.execute_calls == 1  # the reference only
    cases = app.report.tables["Cases"]["values"]
    assert cases[1, "assessment"] == gl.ASSESSMENT_NOT_EVALUATED
    assert "must not overlap" in cases[1, "assessment_detail"]


def test_a_failing_comparison_fails_only_its_own_case(monkeypatch):
    outages = (PlannedOutage("FS1"), PlannedOutage("FS2"))
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    _save_cases([{"id": "A", "name": "A", "outages": [_key(outages[0])]},
                 {"id": "B", "name": "B", "outages": [_key(outages[1])]}])
    real = gl.compare_case

    def compare(result, *args, **kwargs):
        if result["id"] == "A":
            raise KeyError("broken element")
        return real(result, *args, **kwargs)
    monkeypatch.setattr(gl, "compare_case", compare)

    gl.execute_gridlens(app)

    assert app.qds.execute_calls == 3, "B still runs after A failed"
    cases = app.report.tables["Cases"]["values"]
    assert cases[1, "assessment"] == gl.ASSESSMENT_NOT_EVALUATED
    assert "comparison with the reference failed" in cases[1, "assessment_detail"]
    assert cases[2, "assessment"] != gl.ASSESSMENT_NOT_EVALUATED
    runs = app.report.tables["CalculationRuns"]["values"]
    assert runs[1, "result_object"].endswith("_A"), "the ElmRes of the failed comparison is kept"
    assert [item.outserv for item in outages] == [0, 0] and app.qds.iopt_maint == 0


def test_memory_budget_stops_before_the_next_run_and_restores(monkeypatch):
    app = App((PlannedOutage("FS1"), PlannedOutage("FS2")))
    monkeypatch.setattr(gl, "MAX_RUN_CELLS", 1)

    with pytest.raises(gl.GridLensError, match="MAX_RUN_CELLS"):
        gl.execute_gridlens(app)

    assert app.qds.execute_calls == 1, "no case starts once the reference exceeds the budget"
    assert app.qds.iopt_maint == 0 and app.qds.results is app.original_result
    assert (app.study_time.cDate, app.study_time.cTime) == (20140501, 0)


def test_reused_case_names_the_result_object_it_shares(monkeypatch):
    outages = (PlannedOutage("FS1"),)
    app = App(outages)
    monkeypatch.setattr(gl, "CASE_SOURCE", "saved")
    _save_cases([{"id": "A", "name": "A", "outages": [_key(outages[0])]},
                 {"id": "B", "name": "B", "outages": [_key(outages[0])]}])

    gl.execute_gridlens(app)

    runs = app.report.tables["CalculationRuns"]["values"]
    assert runs[2, "result_object"].endswith("_A (shared with A)")


def test_every_case_is_judged_once_and_all_pages_show_that_verdict(monkeypatch):
    app = App((PlannedOutage("FS1"), PlannedOutage("FS2")))
    calls = []
    real = gl.assess_case
    monkeypatch.setattr(gl, "assess_case", lambda results, case: calls.append(case["id"]) or real(results, case))

    gl.execute_gridlens(app)

    assert sorted(calls) == ["OUT01", "OUT02"]
    cases = app.report.tables["Cases"]["values"]
    comparison = app.report.tables["CaseComparison"]["values"]
    last = max(row for row, field in comparison if field == "element_name")
    assert comparison[last, "element_name"] == "Assessment"
    assert [comparison[last, "c1_text"], comparison[last, "c2_text"]] == [cases[1, "assessment"], cases[2, "assessment"]]


def test_windows_off_the_time_axis_are_compared_in_full_and_said_so(monkeypatch):
    app = App((PlannedOutage("FS1", starttime=None, endtime=None),))

    gl.execute_gridlens(app)

    assert any("cannot be placed on the time axis" in line for line in app.messages)
