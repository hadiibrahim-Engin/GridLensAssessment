"""The QDS recording probe, with artificial PowerFactory objects that carry secret-looking names and values."""

from __future__ import annotations

import importlib.util

import pytest

from _paths import tool

PROBE = tool("check_qds_recording.py")
if PROBE is None:
    pytest.skip("development tool not in this checkout", allow_module_level=True)

SPEC = importlib.util.spec_from_file_location("probe_qds_recording", PROBE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

H = 3600.0
START = 1451606400.0  # epoch seconds; never printed


class Obj:
    def __init__(self, name, kind, parent=None, **attributes):
        self.loc_name, self.kind, self.parent, self.children = name, kind, parent, []
        self.__dict__.update(attributes)
        if parent is not None:
            parent.children.append(self)

    def GetClassName(self):
        return self.kind

    def GetFullName(self):
        prefix = self.parent.GetFullName() + "\\" if self.parent is not None else "\\SECRET-user"
        return "{}{}.{}".format(prefix, self.loc_name, self.kind)

    def GetParent(self):
        return self.parent

    def GetContents(self, pattern, recursive=0):
        found = []
        for child in self.children:
            if pattern == "*" or child.kind == pattern.split(".")[-1]:
                found.append(child)
            if recursive:
                found.extend(child.GetContents(pattern, 1))
        return found

    def Delete(self):
        self.parent.children.remove(self)
        self.deleted = True


class ElmRes(Obj):
    def __init__(self, name, parent, columns=()):
        super().__init__(name, "ElmRes", parent, desc=["SECRET comment"], calTp=31)
        self.columns = list(columns)  # (variable, values)

    def Load(self):
        return 0

    def GetNumberOfRows(self):
        return len(self.columns[0][1]) if self.columns else 0

    def GetNumberOfColumns(self):
        return len(self.columns)

    def GetVariable(self, column):
        return self.columns[column][0]

    def GetValue(self, row, column):
        return [0, self.columns[column][1][row]]


class App:
    def __init__(self, times_calculated):
        self.messages, self.calls = [], []
        user = Obj("SECRET-user", "IntUser")
        tmp = Obj("RecB", "IntFolder", Obj("Tmp", "IntFolder", Obj("Set", "IntFolder", user)))
        self.project = Obj("SECRET project", "IntPrj", user)
        self.case = Obj("SECRET case", "IntCase", self.project)
        self.time = Obj("SECRET time", "SetTime", self.case, cDate=20161231, cTime=82800)
        self.temp = ElmRes("SECRET temp", tmp)
        app = self

        class Statsim(Obj):
            def Execute(self):
                app.calls.append("qds")
                app.time.cDate = 1
                app.temp.columns = [("b:noconv", [0.0] * 4), ("c:loading", [41.5, 42.5, 43.5, 44.5]),
                                    ("m:u", [1.01, 1.02, 1.0, 0.99])]
                return 0

        self.qds = Statsim("SECRET qds", "ComStatsim", self.case, results=self.temp, iopt_maint=0,
                           startTime=START, endTime=START + 24 * H, stepSize=1, stepUnit=2)

        class Simoutage(Obj):
            def Execute(self):
                app.calls.append("n1")
                result = ElmRes("SECRET n1", app.case)
                for offset in times_calculated:
                    sub = ElmRes("SECRET sub", result)
                    sub.cnttime = START + (12 + offset) * H
                self.p_rescnt = result
                return 0

        self.n1 = Simoutage("SECRET ca", "ComSimoutage", self.case, iEnableTS=1, calcPeriod=0,
                            studyTime=[START + 3 * H], bIgnoreTime=[0.0], startTime=START, endTime=START + H)

    def GetActiveStudyCase(self):
        return self.case

    def GetActiveProject(self):
        return self.project

    def GetFromStudyCase(self, kind):
        return {"ComStatsim": self.qds, "SetTime": self.time}[kind]

    def PrintPlain(self, line):
        self.messages.append(line)


def _add_copy(app):
    def add_copy(obj):
        copy = ElmRes(obj.loc_name, app.case, [(name, list(values)) for name, values in obj.columns])
        app.calls.append("copy")
        app.copy = copy
        return [copy]
    app.case.AddCopy = add_copy


def _line(lines, label):
    return next(line.split(": ", 1)[1] for line in lines if line.startswith("[probe]   " + label + ":"))


def test_without_enabled_the_probe_only_reads_and_prints_nothing_secret(monkeypatch):
    monkeypatch.setattr(probe, "ENABLED", False)
    app = App([0, 1])
    lines = probe.main(app)
    assert app.calls == []
    assert _line(lines, "configured result object location") == "USER_TMP"
    assert _line(lines, "IntMon in the study case") == "0"
    assert not any("SECRET" in line or "1451" in line or "20161231" in line for line in lines)


def test_enabled_probe_answers_recording_copy_and_study_times(monkeypatch):
    monkeypatch.setattr(probe, "ENABLED", True)
    app = App([-1, 0, 1, 2])  # PowerFactory calculates other times than the two written
    _add_copy(app)
    lines = probe.main(app)

    assert app.calls == ["qds", "copy", "qds", "n1"]
    assert _line(lines, "result object after the run records loading or voltage") == "TRUE"
    assert _line(lines, "result object after the run variables") == "b:noconv x1, c:loading x1, m:u x1"
    assert _line(lines, "copy has the same values (sampled)") == "EQUAL"
    assert _line(lines, "copy unchanged after the second run") == "EQUAL"
    assert _line(lines, "probe copy deleted") == "TRUE" and app.copy.deleted
    assert _line(lines, "written study times, in QDS steps") == "0, 1"
    assert _line(lines, "calculated study times (cnttime of the sub-results), in QDS steps") == "-1, 0, 1, 2"
    assert _line(lines, "restored studyTime") == "TRUE" and app.n1.studyTime == [START + 3 * H]
    assert all(line.endswith("TRUE") for line in lines if "Study Case time restored" in line)
    assert (app.time.cDate, app.time.cTime) == (20161231, 82800)
    assert not any("SECRET" in line or "1451" in line or "20161231" in line for line in lines)
