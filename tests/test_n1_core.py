"""The n-1 core: study times on the QDS grid, reading the contingency results and classifying (n-1)' against n-1."""

from __future__ import annotations

import importlib.util

import pytest

from _paths import delivered

SPEC = importlib.util.spec_from_file_location("gridlens_n1", delivered("main.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)

H = 3600.0
START = 1462060800.0
GRID = (START, START + 23 * H, H)


@pytest.fixture(autouse=True)
def defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


class Obj:
    def __init__(self, name, kind, **attributes):
        self.loc_name, self._kind = name, kind
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self._kind

    def GetFullName(self):
        return "\\Grid\\" + self.loc_name + "." + self._kind


class Sub(Obj):
    """One sub-result: rows are contingencies, columns (element, variable); cells {(row, column): (code, value)}."""

    def __init__(self, moment, outages, columns, cells):
        super().__init__("sub", "ElmRes", cnttime=moment)
        self._outages, self._columns, self._cells = outages, columns, cells

    def Load(self):
        return None

    def Release(self):
        return None

    def GetNumberOfRows(self):
        return len(self._outages)

    def GetNumberOfColumns(self):
        return len(self._columns)

    def GetObject(self, column):
        return self._columns[column][0]

    def GetVariable(self, column):
        return self._columns[column][1]

    def GetObjectValue(self, row):
        return [0, self._outages[row]]

    def GetValue(self, row, column):
        return list(self._cells.get((row, column), (1, 0.0)))


class Folder(Obj):
    def __init__(self, subs):
        super().__init__("results", "ElmRes")
        self._subs = subs

    def GetContents(self, pattern="*"):
        return list(self._subs)


LINE_A, LINE_B = Obj("Line A", "ElmLne"), Obj("Line B", "ElmLne")
BUS = Obj("Bus 1", "ElmTerm", uknom=380.0)
C1, C2 = Obj("C1", "ComOutage"), Obj("C2", "ComOutage")
COLUMNS = [(LINE_A, "c:loading"), (LINE_B, "c:loading"), (BUS, "m:u"), (LINE_A, "c:maxCntcy")]


def command(cells_by_time, outages=(C1, C2), loadmax=80.0):
    subs = [Sub(moment, list(outages), COLUMNS, cells) for moment, cells in cells_by_time.items()]
    return Obj("CA", "ComSimoutage", p_rescnt=Folder(subs), loadmax=loadmax, vlmin=0.95, vlmax=1.05)


def test_study_times_are_the_qds_steps_inside_the_windows():
    windows = [(START + 2.5 * H, START + 5 * H), (START + 4 * H, START + 6 * H), (START + 22 * H, START + 30 * H)]
    assert gl.n1_study_times(windows, GRID) == [START + step * H for step in (3, 4, 5, 22, 23)]
    assert gl.n1_study_times([(START + 2.2 * H, START + 2.8 * H)], GRID) == [], "no QDS step inside the window"
    assert len(gl.n1_study_times([(None, None)], GRID)) == 24, "an unknown window covers the QDS period"
    with pytest.raises(gl.GridLensError, match="more than 5 study times"):
        gl.n1_study_times([(START, START + 10 * H)], GRID, limit=5)


def test_qds_grid_reads_period_and_step():
    qds = Obj("QDS", "ComStatsim", startTime=START, endTime=START + 23 * H, stepSize=15, stepUnit=1)
    assert gl.qds_grid(qds) == (START, START + 23 * H, 900.0)
    assert gl.qds_grid(Obj("QDS", "ComStatsim", startTime=START, endTime=START + H, stepSize=1, stepUnit=5)) is None


def test_results_are_read_per_study_time_with_code_3_kept_apart():
    cells = {(0, 0): (0, 95.0), (0, 1): (3, 0.0), (0, 2): (0, 0.99), (0, 3): (0, 7.0), (1, 0): (0, 60.0)}
    found = gl.read_n1_results(command({START: cells}))

    values = found["times"][START]
    a, b, bus, c1, c2 = (gl.object_key(obj) for obj in (LINE_A, LINE_B, BUS, C1, C2))
    assert values[(c1, a, "loading")] == 95.0 and values[(c1, b, "loading")] is None
    assert values[(c1, bus, "voltage")] == 0.99 and values[(c2, a, "loading")] == 60.0
    assert (c2, b, "loading") not in values, "neither written nor code 3: left out, never zero"
    assert all(key[2] in ("loading", "voltage") for key in values), "c:maxCntcy is not read"
    assert found["categories"][bus] == "voltage" and found["nominal_kv"][bus] == 380.0
    assert found["contingencies"][c1] == "C1" and found["recording_limits"]["loading"] == (80.0,)


def test_the_monitoring_grid_filter_applies_to_n1_results():
    found = gl.read_n1_results(command({START: {(0, 0): (0, 95.0), (0, 1): (0, 50.0)}}),
                               in_scope=lambda obj: obj is not LINE_B)
    assert gl.object_key(LINE_B) not in found["elements"]


def _read(cells, outages=(C1, C2), loadmax=80.0):
    return gl.read_n1_results(command({START: cells}, outages, loadmax))


def test_a_new_overload_in_the_scenario_is_new_and_unchanged_values_are_ok():
    reference = _read({(0, 0): (0, 90.0), (1, 0): (0, 85.0)})
    scenario = _read({(0, 0): (0, 112.0), (1, 0): (0, 85.0)})

    comparison = gl.compare_n1(reference, scenario)

    worst = comparison["elements"][(gl.object_key(LINE_A), "loading")]["worst"]
    assert worst["status"] == "NEW" and worst["contingency_name"] == "C1" and worst["delta"] == pytest.approx(22.0)
    # Four other native cells return read errors; they must remain visible.
    assert comparison["counts"] == {"NEW": 1, "OK": 1, "NOT_EVALUATED": 4}
    assert gl.n1_summary(comparison) == "NEW 1, NOT_EVALUATED 4, OK 1"


def test_a_contingency_the_case_already_switches_off_is_not_applicable_others_failed():
    reference = _read({(0, 0): (0, 90.0), (1, 0): (0, 85.0)})
    scenario = _read({(0, 0): (0, 95.0)}, outages=(C1,))
    line_b = gl.object_key(LINE_B)
    c2 = gl.object_key(C2)

    applicable = gl.compare_n1(reference, scenario, switched_off={line_b}, contingency_elements={c2: {line_b}})
    assert applicable["counts"] == {"OK": 1, "NOT_APPLICABLE": 2, "NOT_EVALUATED": 1}

    other = gl.compare_n1(reference, scenario, switched_off={line_b}, contingency_elements={c2: {"elsewhere"}})
    assert other["counts"] == {"OK": 1, "FAILED": 2, "NOT_EVALUATED": 1}, "a missing contingency without a reason is never OK"


def test_elements_the_case_switches_off_are_not_assessed():
    reference = _read({(0, 0): (0, 90.0), (0, 1): (0, 70.0)})
    scenario = _read({(0, 0): (0, 90.0)})
    comparison = gl.compare_n1(reference, scenario, switched_off={gl.object_key(LINE_B)})
    assert (gl.object_key(LINE_B), "loading") not in comparison["elements"]


def test_values_inside_the_recording_limit_count_only_when_the_limit_proves_them():
    reference = _read({(0, 0): (3, 0.0)})
    scenario = _read({(0, 0): (0, 110.0)})
    worst = gl.compare_n1(reference, scenario)["elements"][(gl.object_key(LINE_A), "loading")]["worst"]
    assert worst["status"] == "NEW" and worst["delta"] is None

    both = gl.compare_n1(reference, _read({(0, 0): (3, 0.0)}))
    assert both["counts"] == {"OK": 1, "NOT_EVALUATED": 5}

    unproven = gl.compare_n1(_read({(0, 0): (3, 0.0)}, loadmax=120.0), _read({(0, 0): (0, 110.0)}, loadmax=120.0))
    assert unproven["counts"] == {"NOT_EVALUATED": 6}, "a recording limit above 100 % proves nothing"


def test_voltage_uses_the_p_u_band():
    reference = _read({(0, 2): (0, 1.0)})
    scenario = _read({(0, 2): (0, 0.93)})
    worst = gl.compare_n1(reference, scenario)["elements"][(gl.object_key(BUS), "voltage")]["worst"]
    assert worst["status"] == "NEW" and worst["limit"]["min"] == pytest.approx(gl.VOLTAGE_MIN)


def test_a_study_time_missing_in_the_scenario_is_failed():
    reference = gl.read_n1_results(command({START: {(0, 0): (0, 90.0)}, START + H: {(0, 0): (0, 90.0)}}))
    scenario = gl.read_n1_results(command({START: {(0, 0): (0, 90.0)}}))
    assert gl.compare_n1(reference, scenario)["counts"] == {"OK": 1, "FAILED": 6, "NOT_EVALUATED": 5}


# --- the run against an artificial contingency analysis -------------------------------------------
class Analysis(Obj):
    """A ComSimoutage that calculates like PowerFactory 2026 (probe of 24 October 2026): with calcPeriod 4 the
    period startTime..endTime (exclusive) decides the study times and studyTime is ignored; every planned outage
    not Ignored applies inside its window; a contingency on switched-off equipment has no row."""

    def __init__(self, outages, planned, lines, fail=False):
        # As found in the project: a period elsewhere, and a studyTime list the sweep does not follow.
        super().__init__("CA", "ComSimoutage", isPlannedOutages=1, studyTime=[START], bIgnoreTime=[0.0], loadmax=80.0,
                         vlmin=0.95, vlmax=1.05, calcPeriod=4, startTime=int(START + 10 * H),
                         endTime=int(START + 14 * H), stepSize=1, stepUnit=2, stepNumber=4)
        self._outages, self._planned, self._lines, self._fail, self.runs = outages, planned, lines, fail, []
        self.p_rescnt = Folder([])

    def GetContents(self, pattern="*"):
        return list(self._outages) if pattern in ("*", "*.ComOutage") else []

    def study_times(self):
        if self.calcPeriod != 4:
            return [moment for moment, skip in zip(self.studyTime, self.bIgnoreTime) if not skip]
        step = self.stepSize * {0: 1, 1: 60, 2: 3600, 3: 86400}[self.stepUnit]
        return [float(moment) for moment in range(int(self.startTime), int(self.endTime), int(step))]

    def Execute(self):
        times = self.study_times()
        self.runs.append((self.isPlannedOutages, tuple(times)))
        if self._fail:
            return 1
        subs = []
        for moment in times:
            active = [fs for fs in self._planned if self.isPlannedOutages and fs.outserv == 0
                      and fs.starttime <= moment < fs.endtime]
            off = {gl.object_key(item) for fs in active for item in fs.components}
            rows = [outage for outage in self._outages if outage.outserv == 0 and gl.object_key(outage.element) not in off]
            columns = [(line, "c:loading") for line in self._lines if gl.object_key(line) not in off]
            cells = {(row, column): (0, 90.0 + (20.0 if active else 0.0)) for row in range(len(rows))
                     for column in range(len(columns))}
            subs.append(Sub(moment, rows, columns, cells))
        self.p_rescnt = Folder(subs)
        return 0


class Study(Obj):
    def __init__(self, children):
        super().__init__("Study", "IntCase")
        self._children = children

    def GetContents(self, pattern="*"):
        return [child for child in self._children if pattern in ("*", "*." + child.GetClassName())]


def _scenario(fail=False, grid_b=False):
    lines = [Obj("L1", "ElmLne"), Obj("L2", "ElmLne"), Obj("L3", "ElmLne", cpGrid=Obj("Grid B", "ElmNet")) if grid_b
             else Obj("L3", "ElmLne")]
    outages = [Obj("C{}".format(number), "ComOutage", outserv=0, element=line) for number, line in enumerate(lines, 1)]
    for outage in outages:
        outage.GetObject = (lambda index, element=outage.element: element if index == 0 else None)
    fs = Obj("FS", "IntPlannedout", outserv=1, starttime=START + 2 * H, endtime=START + 4 * H, components=[lines[1]])
    other = Obj("Other", "IntPlannedout", outserv=0, starttime=START, endtime=START + 23 * H, components=[lines[2]])
    analysis = Analysis(outages, [fs, other], lines, fail)
    records = [{"key": "fs", "name": "FS", "_object": fs, "component_keys": [gl.object_key(lines[1])]},
               {"key": "other", "name": "Other", "_object": other, "component_keys": [gl.object_key(lines[2])]}]
    plan = {"id": "C1", "name": "Case 1", "members": [records[0]], "windows": {"fs": (START + 2 * H, START + 4 * H)},
            "fingerprint": "f1"}
    return analysis, records, plan, outages, (fs, other)


class Logger:
    def __init__(self):
        self.lines = []

    def write(self, stage, message, step=0, level="INFO"):
        self.lines.append((level, message))

    def case(self, message):
        self.lines.append(("CASE", message))

    def detail(self, message, level="INFO"):
        self.lines.append((level, message))


def test_a_case_runs_n1_and_n1_prime_on_the_qds_steps_of_its_windows_and_restores_everything():
    analysis, records, plan, outages, (fs, other) = _scenario()
    request = {"background": [], "assessments": ["n-0", "n-1", "(n-1)'"]}
    equipment = gl.contingency_equipment(analysis)
    elements_of = {gl.object_key(o): {gl.object_key(e) for e in els} for o, els in equipment}

    entry = gl.run_n1_case(analysis, plan, request, records, GRID, [], elements_of, True, {})

    assert analysis.runs == [(0, (START + 2 * H, START + 3 * H)), (1, (START + 2 * H, START + 3 * H))]
    assert entry["status"] == "EVALUATED" and entry["kind"] == "(n-1)'" and entry["times"] == 2
    # 2 study times x contingencies C1, C3 x lines L1, L3 are NEW; C2 trips L2, which the case switches off.
    assert entry["comparison"]["counts"] == {"NEW": 8, "NOT_APPLICABLE": 4}
    assert entry["summary"] == "(n-1)' against n-1: NEW 8, NOT_APPLICABLE 4"
    # The log names what each result holds; (n-1)' lacks the contingency of the switched-off line.
    reference_text, scenario_text = entry["details"]
    assert "contingencies x equipment with a value per study time: " in reference_text
    assert scenario_text.endswith("Contingencies of n-1 missing here: C2 (their equipment is switched off by the case).")
    assert (analysis.isPlannedOutages, analysis.studyTime, analysis.bIgnoreTime) == (1, [START], [0.0])
    # The period GridLens wrote for the run is undone: the sweep settings are those found before.
    assert (analysis.calcPeriod, analysis.startTime, analysis.endTime, analysis.stepNumber) == (
        4, int(START + 10 * H), int(START + 14 * H), 4)
    assert (fs.outserv, other.outserv) == (1, 0), "only the case's outage was active, and both are restored"


def test_windows_that_lie_apart_are_calculated_as_one_period_and_only_the_windows_are_assessed():
    analysis, records, plan, *_ = _scenario()
    second = {"key": "late", "name": "Late", "_object": records[0]["_object"], "component_keys": []}
    plan = dict(plan, members=plan["members"] + [second],
                windows=dict(plan["windows"], late=(START + 7 * H, START + 8 * H)))
    entry = gl.run_n1_case(analysis, plan, {"background": []}, records, GRID, [], {}, False, {})
    # 02:00 to 07:00 calculated (6 steps), 02:00, 03:00 and 07:00 assessed.
    assert analysis.runs == [(0, tuple(START + hour * H for hour in range(2, 8)))]
    assert entry["times"] == 3


def test_a_period_longer_than_the_n1_limit_is_refused_with_the_window_times():
    with pytest.raises(gl.GridLensError, match="covers 25 QDS steps, more than 10") as raised:
        gl.sweep_period([START, START + 24 * H], H, limit=10)
    assert raised.value.details[0].startswith("Study times inside the windows: ")
    assert gl.step_setting(3600.0) == (1, 2) and gl.step_setting(900.0) == (15, 1) and gl.step_setting(86400.0) == (1, 3)


def test_cases_with_the_same_study_times_share_one_reference_sweep():
    analysis, records, plan, *_ = _scenario()
    references = {}
    request = {"background": [], "assessments": ["n-0", "n-1"]}
    first = gl.run_n1_case(analysis, plan, request, records, GRID, [], {}, False, references)
    gl.run_n1_case(analysis, dict(plan, id="C2"), request, records, GRID, [], {}, False, references)
    assert len(analysis.runs) == 1 and first["kind"] == "n-1"
    assert first["summary"] == "n-1 reference: 0 element(s) with a post-fault violation"
    assert first["details"][0].startswith("n-1 result 'read at once': 2 study time(s) assessed (2 calculated, of 23 "
                                          "QDS steps in the period; the others are not calculated)")


def test_a_failed_calculation_or_other_study_times_are_errors_and_settings_are_restored():
    analysis, records, plan, *_ = _scenario(fail=True)
    with pytest.raises(gl.GridLensError, match="error code 1"):
        gl.run_n1_case(analysis, plan, {"background": []}, records, GRID, [], {}, True, {})
    assert analysis.studyTime == [START]

    analysis, records, plan, *_ = _scenario()
    analysis.Execute = lambda: (setattr(analysis, "p_rescnt", Folder([])), 0)[1]
    with pytest.raises(gl.GridLensError, match="did not calculate 2 of the 2 study times inside the outage") as raised:
        gl.run_n1_case(analysis, plan, {"background": []}, records, GRID, [], {}, False, {})
    # The report names the wanted, missing and calculated times, the written period and the settings read back.
    wanted, missing, period, calculated, before, _ = raised.value.details
    assert wanted.startswith("Wanted (QDS steps inside the outage windows): ") and wanted.endswith("(2)")
    assert missing.endswith("(2)") and period.endswith("2 step(s)")
    assert calculated == "Calculated by PowerFactory (cnttime of the sub-results): none (0)"
    assert "calcPeriod = 4" in before and "isPlannedOutages = 0" in before
    assert analysis.startTime == int(START + 10 * H), "restored after the error"


def test_contingencies_outside_the_contingency_grids_are_not_analysed_for_the_run_only():
    analysis, records, plan, outages, _ = _scenario(grid_b=True)
    excluded = gl.contingencies_outside(gl.contingency_equipment(analysis), ("Grid B",))
    assert [outage.loc_name for outage in excluded] == ["C1", "C2"]
    assert gl.contingencies_outside(gl.contingency_equipment(analysis), ()) == []

    gl.run_n1_sweep(analysis, [START], H, set(), records, excluded, "test")
    assert all(outage.outserv == 0 for outage in outages), "'Not analysed' is restored"


def _run_n1(app, study, qds, request, records, ready, results, logger, clock, store=None):
    """Both n-1 phases as a run does them: calculate (keeping copies where possible), then evaluate."""
    entries = gl.calculate_n1(app, study, qds, request, records, ready, logger, clock,
                              store or gl.ResultStore("261023-120000"))
    gl.evaluate_n1(entries, request, ready, results, logger)
    return entries


def test_run_n1_marks_every_case_when_no_contingency_analysis_exists_and_reports_on_the_qa_page():
    analysis, records, plan, *_ = _scenario()
    results = [{"id": "C1"}]
    qds = Obj("QDS", "ComStatsim", startTime=START, endTime=START + 23 * H, stepSize=1, stepUnit=2)
    clock = {"object": Obj("time", "SetTime", cDate=1, cTime=2), "date": 1, "time": 2}
    request = {"background": [], "assessments": ["n-0", "n-1", "(n-1)'"]}

    _run_n1(App([]), Study([]), qds, request, records, [plan], results, Logger(), clock)
    assert results[0]["n1"]["status"] == "NOT EVALUATED" and "no contingency can be defined" in results[0]["n1"]["reason"]
    _run_n1(App([]), Study([analysis, analysis]), qds, request, records, [plan], results, Logger(), clock)
    assert "more than one contingency analysis" in results[0]["n1"]["reason"]

    logger = Logger()
    _run_n1(App([]), Study([analysis]), qds, request, records, [plan, dict(plan, id="C2")], results + [{"id": "C2"}], logger, clock)
    assert results[0]["n1"]["summary"].startswith("(n-1)' against n-1: NEW")
    assert len(analysis.runs) == 2, "C2 has the same outages and windows: evaluated once"
    read_back = [message for _, message in logger.lines if "Read back before the calculation" in message]
    assert read_back == ["n-1: Read back before the calculation: 'Planned outages' [isPlannedOutages] = 0; "
                         "planned outages applied: none, the option is off.",
                         "(n-1)': Read back before the calculation: 'Planned outages' [isPlannedOutages] = 1; "
                         "planned outages applied: FS."]

    payload = gl.empty_payload()
    gl.n1_quality(payload, results)
    row = payload["ScriptedModelQuality"][0]
    assert row["check_id"] == "n1_C1" and row["status"] == "FAIL" and "Caused: NEW L" in row["message"]



class App:
    def __init__(self, objects):
        self._objects = objects

    def GetCalcRelevantObjects(self, pattern):
        return [obj for obj in self._objects if pattern == "*." + obj.GetClassName()]


class NewOutage(Obj):
    def SetObjs(self, elements):
        self.element = elements[0]
        self.GetObject = lambda index: elements[index] if index < len(elements) else None
        return 0


class Creating(Study):
    """A study case without a contingency analysis; CreateObject makes one that can hold ComOutage objects."""

    def CreateObject(self, kind, name):
        assert kind == "ComSimoutage"
        lines = [obj for obj in self._app._objects if obj.GetClassName() == "ElmLne"]
        command = Analysis([], self._planned, lines)
        command.loc_name, command.iEnableTS = name, 0

        def create(kind, name):
            outage = NewOutage(name, kind, outserv=0)
            command._outages.append(outage)
            return outage
        command.CreateObject = create
        self._children.append(command)
        return command


def test_without_a_contingency_analysis_gridlens_defines_one_for_the_selected_grids_and_keeps_it():
    grid_a, grid_b = Obj("Grid A", "ElmNet"), Obj("Grid B", "ElmNet")
    line, branch_line = Obj("L1", "ElmLne", cpGrid=grid_a), Obj("L2", "ElmLne", cpGrid=grid_a)
    branch = Obj("Branch", "ElmBranch", cpGrid=grid_a)
    branch_line.GetParent = lambda: branch
    transformer, foreign = Obj("T1", "ElmTr2", cpGrid=grid_a), Obj("T2", "ElmTr2", cpGrid=grid_b)
    others = [Obj("G1", "ElmSym", cpGrid=grid_a), Obj("Load", "ElmLod", cpGrid=grid_a), Obj("Bus", "ElmTerm", cpGrid=grid_a)]
    app = App([line, branch_line, branch, transformer, foreign] + others)

    assert [obj.loc_name for obj in gl.contingency_candidates(app, ("Grid A",))] == ["L1", "Branch", "T1"]
    assert len(gl.contingency_candidates(app, ())) == 4, "no generators, loads, busbars; the branch replaces its line"

    _, records, plan, _, planned = _scenario()
    study = Creating([])
    study._app, study._planned = app, list(planned)
    # The n-1 grid filter selects the contingencies; the report filter alone would not.
    gl.activate_settings({"contingency_grids": ["Grid A"],
                          "contingency_elements": [gl.object_key(line), gl.object_key(branch)]})
    results = [{"id": "C1"}]
    logger = Logger()
    qds = Obj("QDS", "ComStatsim", startTime=START, endTime=START + 23 * H, stepSize=1, stepUnit=2)
    clock = {"object": Obj("time", "SetTime", cDate=1, cTime=2), "date": 1, "time": 2}
    _run_n1(app, study, qds, {"background": [], "assessments": ["n-0", "n-1"]}, records, [plan], results, logger, clock)

    created = study._children[0]
    assert created.loc_name.startswith("GridLens_") and created.loc_name.endswith("_N1") and created.iEnableTS == 1
    assert [outage.loc_name for outage in created._outages] == ["L1", "Branch"], "only the selected elements"
    assert results[0]["n1"]["status"] == "EVALUATED"
    assert any("GridLens created" in message and "2 contingencies" in message for _, message in logger.lines)



class Vector(Obj):
    def __init__(self):
        super().__init__("buffer", "IntVec")


class BulkSub(Sub):
    """A sub-result that also answers GetColumnValues; code-3 cells come back as 0, as PowerFactory might."""

    def GetColumnValues(self, vector, column):
        vector.V = [self._cells.get((row, column), (1, 0.0))[1] if self._cells.get((row, column), (1,))[0] == 0 else 0.0
                    for row in range(len(self._outages))]
        return 0


def test_n1_columns_keep_sparse_zeros_apart_from_measured_values(monkeypatch):
    monkeypatch.setattr(gl, "COLUMN_BUFFER", Vector())
    gl.RUN_STATS = gl.RunStats()
    loading = BulkSub(START, [C1, C2], COLUMNS, {(0, 0): (0, 95.0), (1, 0): (3, 0.0)})
    assert gl._n1_column(loading, 0, 2, "loading") == [95.0, None], "code 3 is not a measured 0 %"
    assert gl.RUN_STATS.counts == {"values_cellwise": 2}

    dense = BulkSub(START, [C1, C2], COLUMNS, {(0, 0): (0, 95.0), (1, 0): (0, 92.0)})
    assert gl._n1_column(dense, 0, 2, "loading") == [95.0, 92.0]
    assert gl.RUN_STATS.counts['columns_bulk'] == 1

    voltage = BulkSub(START, [C1, C2], COLUMNS, {(0, 2): (0, 0.99), (1, 2): (3, 0.0)})
    assert gl._n1_column(voltage, 2, 2, "voltage") == [0.99, None], "code 3 is read cell by cell, never a 0 p.u. value"
    assert gl.RUN_STATS.counts["values_cellwise"] == 4



class Keeping(Study):
    """A study case whose AddCopy keeps a copy of an n-1 result object, as PowerFactory should."""

    def AddCopy(self, obj):
        copy = Folder(list(obj._subs))
        self._children.append(copy)
        return copy


def test_n1_results_are_kept_as_copies_and_evaluated_from_them_also_later_without_a_calculation():
    analysis, records, plan, *_ = _scenario()
    study = Keeping([analysis])
    qds = Obj("QDS", "ComStatsim", startTime=START, endTime=START + 23 * H, stepSize=1, stepUnit=2)
    clock = {"object": Obj("time", "SetTime", cDate=1, cTime=2), "date": 1, "time": 2}
    request = {"background": [], "assessments": ["n-0", "n-1", "(n-1)'"]}
    results = [{"id": "C1"}]

    entries = _run_n1(App([]), study, qds, request, records, [plan], results, Logger(), clock)

    kept = [child for child in study._children if child.GetClassName() == "ElmRes"]
    assert [child.loc_name for child in kept] == ["GridLens_261023-120000_C1_N1", "GridLens_261023-120000_C1_N1P"]
    assert entries["C1"]["reference"]["kept"] is kept[0], "phase 2 reads the kept copy, not the contingency analysis"
    assert "recording 80,0.95,1.05" in kept[0].desc[0] and "fingerprint f1" in kept[0].desc[0]
    first = results[0]["n1"]["summary"]
    assert first.startswith("(n-1)' against n-1: NEW")

    # Later: the same kept copies are evaluated again, PowerFactory calculates nothing.
    calls = len(analysis.runs)
    gl.activate_settings({"run_reference": False})
    try:
        runs, n1 = gl.kept_runs(study, "261023-120000", request, [plan], Logger())
    finally:
        gl.reset_settings()
    again = [{"id": "C1"}]
    gl.evaluate_n1(n1, request, [plan], again, Logger())
    assert again[0]["n1"]["summary"] == first and len(analysis.runs) == calls
    assert runs[0]["failed"].startswith("the run 261023-120000 kept no result object"), "no QDS object in this study"
    assert "n-1 filter: grids every grid; outaged elements: every element" in kept[0].desc[0]

    # Re-evaluated with an element selection set afterwards: only L2 and L3 are outaged, C1 is left out.
    chosen = [gl.object_key(analysis._lines[1]), gl.object_key(analysis._lines[2])]
    gl.activate_settings({"run_reference": False, "contingency_elements": chosen})
    try:
        _, n1 = gl.kept_runs(study, "261023-120000", request, [plan], Logger())
        narrowed = [{"id": "C1"}]
        logger = Logger()
        gl.evaluate_n1(n1, request, [plan], narrowed, logger)
    finally:
        gl.reset_settings()
    assert len(analysis.runs) == calls
    notes = [message for _, message in logger.lines]
    assert any(message.startswith("Kept n-1 result calculated with the grids every grid; outaged elements: every "
                                  "element; now: the n-1 filter: grids every grid; outaged elements: L2, L3.")
               for message in notes)
    assert any("Left out of the evaluation by the current n-1 filters: 1 contingency (C1)" in message for message in notes)
    assert narrowed[0]["n1"]["summary"] != first


def test_only_contingencies_outaging_a_selected_element_are_analysed_for_the_run():
    analysis, records, plan, outages, _ = _scenario()
    qds = Obj("QDS", "ComStatsim", startTime=START, endTime=START + 23 * H, stepSize=1, stepUnit=2)
    clock = {"object": Obj("time", "SetTime", cDate=1, cTime=2), "date": 1, "time": 2}
    seen = []
    execute = analysis.Execute
    analysis.Execute = lambda: (seen.append([outage.outserv for outage in outages]), execute())[1]
    gl.activate_settings({"contingency_elements": [gl.object_key(analysis._lines[0]), gl.object_key(analysis._lines[1])]})
    try:
        logger = Logger()
        _run_n1(App([]), Study([analysis]), qds, {"background": [], "assessments": ["n-0", "n-1"]}, records, [plan],
                [{"id": "C1"}], logger, clock)
    finally:
        gl.reset_settings()
    assert seen == [[0, 0, 1]], "C3 outages L3: not analysed during the run"
    assert [outage.outserv for outage in outages] == [0, 0, 0], "restored afterwards"
    assert any("Not analysed for the run: C3 (outages no selected element)." in message for _, message in logger.lines)


def test_the_contract_seven_tables_of_one_case_come_from_the_reporting_core():
    analysis, records, plan, *_ = _scenario()
    request = {"background": [], "assessments": ["n-0", "n-1", "(n-1)'"]}
    equipment = gl.contingency_equipment(analysis)
    elements_of = {gl.object_key(o): {gl.object_key(e) for e in els} for o, els in equipment}
    entry = gl.run_n1_case(analysis, plan, request, records, GRID, [], elements_of, True, {})
    results = [{"id": "REF", "name": "Reference", "status": gl.CONVERGED},
               {"id": "C1", "name": "Case 1", "status": gl.CONVERGED, "n1": entry},
               {"id": "C2", "name": "Case 2", "status": gl.CONVERGED, "n1": {"status": "NOT EVALUATED", "reason": "no window"}}]
    payload, notes = gl.empty_payload(), {}
    view = gl._element_view(results)
    gl._critical_elements(payload, results, view, notes)
    gl._detail_matrices(payload, results, view)
    gl._classification(payload, results, view)
    gl._case_status_counts(payload, results)
    gl._contingency_register(payload, results)
    gl._contingency_events(payload, results, notes)
    gl._episodes(payload, results)
    gl._quality_register(payload, results)
    gl._time_criticality(payload, results, notes)

    # L1 and L3 become overloaded under C1 and C3 at both study times (NEW); L2 is switched off by the case.
    assert payload["ScriptedCaseStatusCounts"] == [{"case_order": 1, "case_name": "Case 1", "new_count": 8, "worsened_count": 0,
                                                    "improved_count": 0, "resolved_count": 0}]
    critical = payload["ScriptedCriticalLines"]
    assert [(row["element_name"], row["ref_text"], row["case_a_text"], row["violation"]) for row in critical] == [
        ("L1", "90.0 % (max 100 %)", "110.0 %\nN 4", 1), ("L3", "90.0 % (max 100 %)", "110.0 %\nN 4", 1)]
    assert notes["line"] == (2, 2) and "2 of 2 lines" in gl.critical_note(notes)
    detail = payload["ScriptedDetailLines"][0]
    assert detail["case_a_text"].startswith("110.0 %\n") and detail["ref_text"].startswith("90.0 %\n")
    l1 = next(key for key, name in entry["statistics"]["meta"]["elements"].items() if name == "L1")
    counts = gl.element_counters(entry["statistics"], l1, "loading")
    assert counts["NEW"] == 4 and counts["NOT_APPLICABLE"] == 2 and counts["OK"] == 0
    assert payload["ScriptedClassificationMatrix"][0]["case_a_text"] == "N 4 · Q 2"
    register = {row["contingency_name"]: row for row in payload["ScriptedContingencyRegister"]}
    assert register["C1"]["new_events"] == 4 and register["C2"]["not_applicable_times"] == 2
    assert payload["ScriptedContingencyRanking"] == [{"rank": 1, "contingency_name": "C1", "finding_count": 4},
                                                     {"rank": 2, "contingency_name": "C3", "finding_count": 4}]
    events = payload["ScriptedContingencyEvents"]
    assert len(events) == 8 and {row["status"] for row in events} == {"NEW"}
    assert sorted(row["main_rank"] for row in events) == list(range(1, 9))
    assert events[0]["reference_text"] == "90.0 %" and events[0]["scenario_text"] == "110.0 %"
    assert events[0]["change_text"] == "+20.0 pp" and events[0]["limit_text"] == "max 100 %"
    assert notes["events"] == (8, 8)
    episodes = payload["ScriptedContingencyEpisodes"]
    assert len(episodes) == 4 and {row["points"] for row in episodes} == {2}
    quality = payload["ScriptedQualityRegister"]
    assert [(row["case_name"], row["status"], row["contingency_name"]) for row in quality] == [
        ("Case 1", "NOT-APPLICABLE", "C2"), ("Case 2", "NOT-EVALUATED", "every contingency")]
    # Not applicable at both study times, for every monitored element and criterion; equals the NOT_APPLICABLE count.
    assert quality[0]["cells"] == entry["statistics"]["coverage"]["cells_quality"]["NOT_APPLICABLE"] > 0
    assert quality[0]["time_text"].endswith("(2 study times)") and quality[0]["violation"] == 0
    times = payload["ScriptedTimeCriticality"]
    assert [(row["value_ref"], row["value_a"]) for row in times] == [(0.0, 2.0), (0.0, 2.0)]
    assert [row["case_a_text"] for row in payload["ScriptedTimeMatrix"]] == ["E 2 · C 2", "E 2 · C 2"]
    flag, text = gl.n1_meta_text(results)
    assert flag == "1" and text.startswith("Contingency analysis of the study case at the QDS time steps")
    assert gl.n1_meta_text(results[:1])[0] == "0"


def test_long_registers_are_cut_fairly_between_cases_and_keep_the_most_severe(monkeypatch):
    monkeypatch.setattr(gl, "MAX_TABLE_ROWS", 5)
    payload = gl.empty_payload()
    payload["ScriptedContingencyEpisodes"] = (
        [{"case_order": 1, "row_order": n, "status": "PRE-EXISTING", "peak_text": "{} pp".format(n)} for n in range(1, 9)]
        + [{"case_order": 2, "row_order": 1, "status": "NEW", "peak_text": "1.0 pp"}])
    gl._fair_cut(payload, "ScriptedContingencyEpisodes", lambda row: row["case_order"],
                 lambda row: (gl.STATUS_RANK[row["status"].replace("-", "_")], -gl._amount(row["peak_text"]), row["row_order"]))

    kept = [(row["case_order"], row["row_order"]) for row in payload["ScriptedContingencyEpisodes"]]
    # Case 2 keeps its only row; case 1 the four largest peaks, in their original order (never cut by case order).
    assert kept == [(1, 5), (1, 6), (1, 7), (1, 8), (2, 1)]
    (note,) = payload["ScriptedModelQuality"]
    assert note["status"] == "FAIL" and "5 of 9 rows, shared between 2 group(s)" in note["message"]


def test_block_tables_keep_the_same_rows_in_every_block_when_cut(monkeypatch):
    monkeypatch.setattr(gl, "MAX_TABLE_ROWS", 4)
    payload = gl.empty_payload()
    columns = [("C{}".format(n), "Case {}".format(n)) for n in range(1, 5)]
    entries = [("E{}".format(n), "-", {}, 0) for n in range(1, 5)]
    gl._block_rows(payload, "ScriptedDetailLines", columns, entries, 3, priority=[3, 0, 2, 1])

    rows = payload["ScriptedDetailLines"]
    # Two blocks of at most two rows each: the two most severe elements (E2, E4) in both, in display order.
    assert [(row["block"], row["element_name"], row["col_count"]) for row in rows] == [
        (1, "E2", 3), (1, "E4", 3), (2, "E2", 1), (2, "E4", 1)]
    assert "2 of 4 rows in each of the 2 scenario block(s)" in payload["ScriptedModelQuality"][0]["message"]
