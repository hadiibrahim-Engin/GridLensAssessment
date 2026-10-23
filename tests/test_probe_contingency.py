"""The contingency probe only reads, and the prepared test run cannot write by accident."""

from __future__ import annotations

import ast
import importlib.util

import pytest

from _paths import tool

PROBE = tool("probe_contingency.py")
TEST_RUN = tool("test_contingency.py")
if PROBE is None:
    pytest.skip("development tool not in this checkout", allow_module_level=True)

# Calls that change a PowerFactory project or start a calculation.
WRITING_CALLS = {"Execute", "CreateObject", "SetAttribute", "Delete", "AddCopy", "PasteCopy", "Activate", "Deactivate",
                 "Write", "WriteDraw", "AddVariable", "Init", "InitialiseWriting", "Clear", "Flush", "SetAsDefault",
                 "Close", "Move", "GetFromStudyCase", "SetObj", "SetSubElmResKey", "ResetCalculation", "Rename"}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load("probe_contingency", PROBE)


def test_probe_never_calls_a_writing_method_or_assigns_an_attribute():
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    named = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assigned = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AugAssign))
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Attribute) and not (isinstance(target.value, ast.Name) and target.value.id == "self")]

    assert not called & WRITING_CALLS, called & WRITING_CALLS
    assert not assigned
    assert "setattr" not in {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    # Names of writing ElmRes methods may appear only in the list the probe reports on, never as a call target.
    assert set(probe.WRITE_METHODS) <= named
    assert not set(probe.WRITE_METHODS) & set(probe.READ_METHODS)
    assert "RUN_EXPERIMENT" not in PROBE.read_text(encoding="utf-8")


class Obj:
    """A PowerFactory object stand-in that records every method call."""

    calls = []

    def __init__(self, kind, name, children=(), **attributes):
        self._kind, self.loc_name, self._children = kind, name, list(children)
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self._kind

    def GetFullName(self):
        return "Project\\" + self.loc_name + "." + self._kind

    def GetContents(self, pattern="*", recursive=0):
        Obj.calls.append(("GetContents", self.loc_name))
        found = []
        for child in self._children:
            if pattern in ("*", "*." + child._kind):
                found.append(child)
            if recursive:
                found += [item for item in child.GetContents(pattern, 1)]
        return found

    def GetAttributeDescription(self, name):
        return {"iopt_tsweep": "Time sweep", "p_res": "Results"}.get(name, "")

    def Execute(self):  # must never be reached
        raise AssertionError("the probe executed a command")

    def CreateObject(self, *args):  # must never be reached
        raise AssertionError("the probe created an object")


class Results(Obj):
    def Load(self):
        return 0

    def Release(self):
        return 0

    def GetNumberOfRows(self):
        return 3

    def GetNumberOfColumns(self):
        return 2

    def GetVariable(self, column):
        return ["b:ifcase", "c:loading"][column]

    def GetObject(self, column):
        return LINE

    def GetValue(self, row, column):
        return (0, None if column == 1 and row == 2 else float(row))

    def Write(self):  # must never be reached
        raise AssertionError("the probe wrote into an ElmRes")


LINE = Obj("ElmLne", "L1")


class App:
    def __init__(self):
        self.lines = []
        result = Results("ElmRes", "Contingency results")
        contingency = Obj("ComOutage", "Outage L3", children=[Obj("EvtOutage", "trip", p_target=LINE)])
        command = Obj("ComSimoutage", "Contingency Analysis", children=[contingency], iopt_tsweep=1, p_res=result)
        qds = Obj("ComStatsim", "QDS", startTime=1467331200, endTime=1467417600, calcPeriod=0, stepSize=2, stepUnit=1,
                  results=result)
        self.study = Obj("IntCase", "Study", children=[command, qds, result, Obj("SetTime", "Time", cDate="20160701")])
        self.project = Obj("IntPrj", "Project", children=[self.study])

    def PrintPlain(self, message):
        self.lines.append(message)

    def GetActiveProject(self):
        return self.project

    def GetActiveStudyCase(self):
        return self.study

    def GetProjectFolder(self, key):
        return Obj("IntFolder", "Study Cases") if key == "study" else None

    def GetCalcRelevantObjects(self, pattern):
        return []

    def GetFromStudyCase(self, name):  # would create the command in PowerFactory
        raise AssertionError("the probe used GetFromStudyCase")


def test_probe_reports_every_section_and_classifies_its_findings():
    app = App()
    findings = probe.probe(app)

    kinds = {kind for kind, _, _ in findings.items}
    text = "\n".join(app.lines)
    assert kinds <= set(probe.KINDS) and probe.VERIFIED in kinds and probe.OPEN in kinds
    assert "SUMMARY - GridLens contingency probe" in text
    for heading in ("1. ComSimoutage", "2. ComStatsim", "3. Contingency definitions", "4. Contingency result objects",
                    "5. ElmRes interface", "6. Places for persistent results"):
        assert heading in text
    assert any(topic == "time sweep" and kind == probe.UNTESTED for kind, topic, _ in findings.items)
    assert any(topic == "ElmRes write Write" and kind == probe.UNTESTED for kind, topic, _ in findings.items)
    assert any(topic == "contingency class ComOutage" and kind == probe.VERIFIED for kind, topic, _ in findings.items)
    assert any(topic == "part 3" for _, topic, _ in findings.items)
    assert "1 of 6 sampled cells without a number" in text


def test_probe_without_contingency_command_says_so_and_creates_nothing():
    app = App()
    app.study._children = [child for child in app.study._children if child.GetClassName() != "ComSimoutage"]

    findings = probe.probe(app)

    assert any(kind == probe.MISSING and topic == "ComSimoutage" and "does not create one" in text
               for kind, topic, text in findings.items)


@pytest.mark.skipif(TEST_RUN is None, reason="development tool not in this checkout")
def test_prepared_test_run_is_disabled_and_guarded():
    run = _load("test_contingency_tool", TEST_RUN)

    assert run.ENABLED is False and run.SWEEP_SETTINGS == {} and run.ELMRES_WRITE == ()

    class Project:
        loc_name = "Transmission System"

    class Live:
        def GetActiveProject(self):
            return Project()

        def GetActiveStudyCase(self):
            return object()

    assert "ENABLED is False" in run.preconditions(Live())
    run.ENABLED, run.PROJECT_COPY_NAME = True, "Transmission System"
    assert "contain 'copy'" in run.preconditions(Live())
    run.PROJECT_COPY_NAME = "Transmission System copy"
    assert "not the configured copy" in run.preconditions(Live())
    source = TEST_RUN.read_text(encoding="utf-8")
    assert source.count("confirm(") >= 2, "the writing test asks before it writes"
    assert "restore()" in source
