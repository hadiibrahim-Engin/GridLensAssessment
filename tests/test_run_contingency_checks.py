"""The contingency test run tool, against an artificial contingency analysis (no PowerFactory)."""

from __future__ import annotations

import ast
import importlib.util

import pytest

from _paths import tool

TOOL = tool("run_contingency_checks.py")
if TOOL is None:
    pytest.skip("development tool not in this checkout", allow_module_level=True)

SECRET = "SECRET"
H = 3600.0
START = 1462449600.0


def _load():
    spec = importlib.util.spec_from_file_location("test_contingency_tool_run", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Obj:
    def __init__(self, kind, name, children=(), **attributes):
        self._kind, self.loc_name, self._children = kind, SECRET + "_" + name, list(children)
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self._kind

    def GetContents(self, pattern="*", recursive=0):
        found = []
        for child in self._children:
            if pattern in ("*", "*." + child._kind):
                found.append(child)
            if recursive:
                found += child.GetContents(pattern, 1)
        return found

    def GetAttribute(self, name):
        return getattr(self, name)

    def GetFullName(self):
        return "\\" + self.loc_name + "." + self._kind


class Wrapper:
    """A second Python object for the same PowerFactory object, as PowerFactory may return."""

    def __init__(self, target):
        self._target = target

    def __getattr__(self, name):
        return getattr(self._target, name)


class SubResult(Obj):
    def __init__(self, moment, rows, line, planned):
        super().__init__("ElmRes", "sub", cnttime=moment)
        self._rows, self._line, self._planned = rows, line, planned

    def Load(self):
        return None

    def Release(self):
        return None

    def GetNumberOfRows(self):
        return len(self._rows)

    def GetNumberOfColumns(self):
        return 2

    def GetVariable(self, column):
        return ["c:loading", "c:maxCntcy"][column]

    def GetObject(self, column):
        return self._line

    def GetObjectValue(self, row):
        return (0, Wrapper(self._rows[row]))

    def GetValue(self, row, column=None):
        if column == 0:
            return (3, 0.0) if row == 0 else (0, 91.5 + (5.0 if self._planned else 0.0))
        return (0, float(row + 1))  # like the observed c:maxCntcy: not the ComOutage number


DAY = [START + step * H for step in range(24)]


class Command(Obj):
    """A contingency analysis whose time sweep covers a whole day (studyTime), not startTime..endTime."""

    def __init__(self, outages, line, planned, fail=False):
        super().__init__("ComSimoutage", "CA", children=list(outages), isPlannedOutages=1, startTime=START + 14 * H,
                         endTime=START + 17 * H, stepSize=1, stepUnit=2, iEnableTS=1, studyTime=list(DAY),
                         bIgnoreTime=[0.0] * 24)
        self.p_rescnt = Obj("ElmRes", "AC")
        self._line, self._fail, self._planned, self.runs = line, fail, planned, []
        self.ignore_not_analysed = False
        # Variants PowerFactory might show: the times come from startTime..endTime instead of the vector;
        # a planned outage that touches the sweep is applied once for every study time.
        self.times_from_period, self.apply_once = False, False

    def times(self):
        if self.times_from_period:
            step = self.stepSize * {1: 60, 2: H}[self.stepUnit]
            return [self.startTime + index * step for index in range(int((self.endTime - self.startTime) / step) + 1)]
        return [moment for moment, skip in zip(self.studyTime, self.bIgnoreTime) if not skip]

    def Execute(self):
        self.runs.append(self.isPlannedOutages)
        if self._fail:
            return 1
        subs, times = [], self.times()
        for moment in times:
            switched_off = set()
            active = (lambda when: self._planned.starttime <= when < self._planned.endtime)
            if self.isPlannedOutages and self._planned.outserv == 0 and (
                    any(active(when) for when in times) if self.apply_once else active(moment)):
                switched_off = {item.GetFullName() for item in self._planned.components}
            # PowerFactory ignores a contingency whose equipment is already out of service.
            rows = [outage for outage in self._children if outage._kind == "ComOutage"
                    and (outage.outserv == 0 or self.ignore_not_analysed)
                    and outage.element.GetFullName() not in switched_off]
            subs.append(SubResult(moment, rows, self._line, self.isPlannedOutages))
        self.p_rescnt._children = subs
        return 0


class StudyCase(Obj):
    def CreateObject(self, kind, name):
        store = {}

        class Map(Obj):
            def Insert(self, key, value):
                store[key] = value

            def GetValue(self, key):
                return [store.get(key), 0 if key in store else 1]

            def Delete(inner):
                self._children.remove(inner)
        created = Map(kind, "map")
        created.loc_name = name
        self._children.append(created)
        return created


def _project(fail=False, planned_outage=True):
    line = Obj("ElmLne", "line")
    lines = [Obj("ElmLne", "L{}".format(number)) for number in (1, 2, 3)]
    outages = [Obj("ComOutage", "C{}".format(number), number=number + 10, outserv=0, element=element)
               for number, element in zip((1, 2, 3), lines)]
    for outage in outages:
        outage.GetObject = (lambda line_index, element=outage.element: element if line_index == 0 else None)
    fs = Obj("IntPlannedout", "fs", starttime=START + 9 * H, endtime=START + 12 * H, outserv=0 if planned_outage else 1,
             components=[Wrapper(lines[1])])
    command = Command(outages, line, fs, fail=fail)
    statsim = Obj("ComStatsim", "QDS", startTime=START, endTime=START + 23 * H, stepSize=1, stepUnit=2)
    clock = Obj("SetTime", "time", cDate="20160505", cTime="140000")
    study = StudyCase("IntCase", "study", children=[command, statsim, clock])
    project = Obj("IntPrj", "copy of the project", children=[Obj("IntPrjfolder", "lib", children=[fs])])

    class App:
        def __init__(self):
            self.printed = []

        def GetActiveProject(self):
            return project

        def GetActiveStudyCase(self):
            return study

        def PrintPlain(self, line):
            self.printed.append(line)
    return App(), command, outages, study


@pytest.fixture
def tool_run(monkeypatch):
    run = _load()
    monkeypatch.setattr(run, "ENABLED", True)
    monkeypatch.setattr(run, "PROJECT_COPY_NAME", SECRET + "_copy of the project")
    monkeypatch.setattr(run, "confirm", lambda question: True)
    return run


def _values(out):
    return dict(line.split(": ", 1) for line in out.lines if ": " in line)


def test_the_complete_contingency_analysis_runs_and_every_check_is_reported(tool_run):
    app, command, outages, study = _project()

    out = tool_run.run(app, app.printed.append)

    lines = _values(out)
    assert lines["T1 Execute"] == "SUCCESS" and lines["T1 Sub-results created"] == "TRUE"
    assert lines["T1 Study times match the time-sweep definition"] == "TRUE"
    assert lines["T1 Study times match the studyTime vector"] == "TRUE", "the day of the sweep, as observed"
    assert lines["T1 Study times match startTime/endTime/step"] == "FALSE"
    assert lines["T1 Time sweep equals the QDS time steps"] == "TRUE"
    assert lines["T1 Study times lie on the QDS time grid"] == "TRUE"
    assert lines["T1 Rows are contingencies"] == "TRUE" and lines["T1 Columns are equipment"] == "TRUE"
    assert lines["T1 Sparse values present"] == "TRUE"
    assert lines["T1 c:maxCntcy holds contingency numbers"] == "FALSE"
    assert lines["T1 c:maxCntcy holds row numbers"] == "TRUE"
    assert lines["T1 One row per analysed contingency"] == "TRUE" and lines["T1 Result"] == "PASS"
    assert lines["T1 calcPeriod setting"] == "NOT_VERIFIED", "the artificial command has no calcPeriod"
    assert lines["T2 Planned outage inside the sweep period"] == "TRUE"
    assert lines["T2 Results differ with planned outages"] == "TRUE" and lines["T2 Result"] == "PASS"
    assert lines["T2 Contingencies missing with planned outages"] == "TRUE"
    assert lines["T2 Missing contingency switches a planned-outage element"] == "TRUE"
    assert lines["T2 One row per analysed contingency without planned outages"] == "TRUE"
    assert lines["T2 Planned outage active at every study time"] == "FALSE"
    assert lines["T2 Contingencies missing only inside the planned-outage window"] == "TRUE"
    assert lines["T3 Not analysed excludes the contingency"] == "TRUE" and lines["T3 Result"] == "PASS"
    assert lines["T4 Key/value read back unchanged"] == "TRUE" and lines["T4 Test object deleted"] == "TRUE"
    assert lines["T4 Result"] == "PASS" and lines["T5 Result"] == "NOT_DOCUMENTED"
    assert lines["T6 Planned outage with a matching contingency"] == "TRUE"
    assert lines["T6 Study times follow the studyTime vector"] == "TRUE"
    assert "T6 Execute with written startTime/endTime/step" not in lines, "the vector worked, no second variant"
    assert lines["T6 Missing inside the planned-outage window"] == "TRUE"
    assert lines["T6 Present outside the planned-outage window"] == "TRUE"
    assert lines["T6 Present at the window end"] == "TRUE" and lines["T6 Result"] == "PASS"
    assert lines["Final run with the original settings"] == "SUCCESS"


def test_every_written_attribute_is_restored_and_verified(tool_run):
    app, command, outages, study = _project()

    out = tool_run.run(app, app.printed.append)

    assert command.isPlannedOutages == 1 and all(outage.outserv == 0 for outage in outages)
    assert command.studyTime == DAY and command.bIgnoreTime == [0.0] * 24
    assert (command.startTime, command.endTime, command.stepSize, command.stepUnit) == (START + 14 * H, START + 17 * H, 1, 2)
    assert "Restored isPlannedOutages: TRUE" in out.lines and "Restored outserv: TRUE" in out.lines
    assert "Restored studyTime: TRUE" in out.lines and "Restored bIgnoreTime: TRUE" in out.lines
    assert command.runs[-1] == 1, "the last calculation uses the original settings"
    assert not study.GetContents("*.IntDplmap"), "the test object is deleted"


def test_no_name_value_or_time_reaches_the_output(tool_run):
    app, *_ = _project()

    out = tool_run.run(app, app.printed.append)

    text = "\n".join(app.printed)
    assert SECRET not in text and "1462449600" not in text and "91.5" not in text and "20160505" not in text
    for line in out.lines:
        if ": " in line:
            label, token = line.split(": ", 1)
            assert label in tool_run.LABELS and token in tool_run.TOKENS, line
        else:
            assert line.startswith("Nothing was done: "), line


def test_nothing_runs_without_release_copy_name_or_confirmation(monkeypatch):
    run = _load()
    app, command, _, _ = _project()
    assert run.preconditions(app) == "disabled"
    out = run.run(app, app.printed.append)
    assert command.runs == [] and "Nothing was done: ENABLED is False" in out.lines[-1]

    monkeypatch.setattr(run, "ENABLED", True)
    monkeypatch.setattr(run, "PROJECT_COPY_NAME", SECRET + "_production")
    assert run.preconditions(app) == "name", "the copy marker is required"
    monkeypatch.setattr(run, "PROJECT_COPY_NAME", SECRET + "_other copy")
    assert run.preconditions(app) == "project"
    assert SECRET not in run.PRECONDITION_TEXTS["project"]

    monkeypatch.setattr(run, "PROJECT_COPY_NAME", SECRET + "_copy of the project")
    monkeypatch.setattr(run, "confirm", lambda question: False)
    out = run.run(app, app.printed.append)
    assert command.runs == [] and "T1 Confirmed: NOT_CONFIRMED" in out.lines
    assert "Final run with the original settings: SUCCESS" not in out.lines


def test_a_failing_calculation_is_reported_and_settings_are_still_restored(tool_run):
    app, command, outages, _ = _project(fail=True)

    out = tool_run.run(app, app.printed.append)

    lines = _values(out)
    assert lines["T1 Execute"] == "ERROR" and lines["T1 Result"] == "FAIL"
    assert command.isPlannedOutages == 1 and all(outage.outserv == 0 for outage in outages)


def test_without_a_planned_outage_in_the_period_t2_proves_nothing(tool_run):
    app, *_ = _project(planned_outage=False)

    lines = _values(tool_run.run(app, app.printed.append))

    assert lines["T2 Planned outage inside the sweep period"] == "FALSE" and lines["T2 Result"] == "NOT_VERIFIED"


def test_static_output_only_through_the_allowlist():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    printers = {function.name for function in ast.walk(tree) if isinstance(function, ast.FunctionDef)
                and any(isinstance(node, ast.Attribute) and node.attr in ("PrintPlain", "printer") for node in ast.walk(function))}
    assert printers <= {"_print", "run", "__init__"}, printers
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not {"print", "open", "eval", "exec"} & names


def test_t3_does_not_claim_an_exclusion_that_did_not_happen(tool_run):
    app, command, *_ = _project()
    command.ignore_not_analysed = True  # PowerFactory would keep the contingency despite "Not analysed"

    lines = _values(tool_run.run(app, app.printed.append))

    assert lines["T3 Not analysed excludes the contingency"] == "FALSE" and lines["T3 Result"] == "FAIL"


def test_t6_chooses_qds_steps_around_the_window():
    run = _load()
    grid = (START, START + 23 * H, H)

    assert run.window_times((START + 9 * H, START + 12 * H), grid) == [START + step * H for step in (8, 9, 10, 11, 12)]
    assert run.window_times((START + 9.5 * H, START + 10.5 * H), grid) == [START + step * H for step in (9, 10, 11)]
    assert run.window_times((START - 5 * H, START + 1 * H), grid) == [START, START + H]
    assert run.window_times((START + 30 * H, START + 40 * H), grid) is None, "outside the QDS period"


def test_t6_falls_back_to_start_and_end_when_the_vector_is_not_used(tool_run):
    app, command, outages, _ = _project()
    command.times_from_period = True

    lines = _values(tool_run.run(app, app.printed.append))

    assert lines["T6 Study times follow the studyTime vector"] == "FALSE"
    assert lines["T6 Study times follow startTime/endTime/step"] == "TRUE"
    assert lines["T6 Missing inside the planned-outage window"] == "TRUE" and lines["T6 Result"] == "PASS"
    assert (command.startTime, command.endTime) == (START + 14 * H, START + 17 * H)


def test_t6_reveals_a_planned_outage_applied_to_the_whole_sweep(tool_run):
    app, command, *_ = _project()
    command.apply_once = True

    lines = _values(tool_run.run(app, app.printed.append))

    assert lines["T6 Missing inside the planned-outage window"] == "TRUE"
    assert lines["T6 Present outside the planned-outage window"] == "FALSE" and lines["T6 Result"] == "FAIL"
    assert lines["T2 Contingencies missing only inside the planned-outage window"] == "FALSE"
