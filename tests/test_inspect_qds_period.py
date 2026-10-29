"""The QDS period probe, with artificial PowerFactory objects that carry secret-looking names."""

from __future__ import annotations

import importlib.util
from datetime import datetime

import pytest

from _paths import tool

PROBE = tool("inspect_qds_period.py")
if PROBE is None:
    pytest.skip("development tool not in this checkout", allow_module_level=True)

SPEC = importlib.util.spec_from_file_location("probe_qds_period", PROBE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

Y2002 = datetime(2002, 1, 1).timestamp()
Y2028 = datetime(2028, 3, 1).timestamp()


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

    def GetContents(self, pattern, recursive=0):
        kind = pattern.split(".")[-1]
        found = []
        for child in self.children:
            if child.kind == kind:
                found.append(child)
            if recursive:
                found.extend(child.GetContents(pattern, recursive))
        return found

    def GetAttributes(self):
        return [name for name in vars(self) if name not in ("loc_name", "kind", "parent", "children")]


class App:
    def __init__(self, project, case, default):
        self.project, self.case, self.default, self.lines, self.created = project, case, default, [], False

    def GetActiveProject(self):
        return self.project

    def GetActiveStudyCase(self):
        return self.case

    def GetFromStudyCase(self, kind):
        if self.default is None:
            self.created = True
        return self.default

    def PrintPlain(self, line):
        self.lines.append(line)


def model(stale_first=True):
    project = Obj("SECRET-project", "IntPrj")
    case = Obj("SECRET-case", "IntCase", project, iStudyTime=int(Y2028))
    Obj("SECRET-clock", "SetTime", case, cDate=20280301, cTime=0)
    stale = Obj("SECRET-old", "ComStatsim", case, calcPeriod=4, startTime=int(Y2002), endTime=int(Y2002 + 365 * 86400))
    used = Obj("SECRET-qds", "ComStatsim", case, calcPeriod=4, startTime=int(Y2028), endTime=int(Y2028 + 86400))
    Obj("SECRET-other", "ComStatsim", Obj("SECRET-case2", "IntCase", project), calcPeriod=0, startTime=int(Y2028))
    Obj("SECRET-outage", "IntPlannedout", project, starttime=int(Y2028 + 3600), endtime=int(Y2028 + 7200))
    return App(project, case, stale if stale_first else used)


def test_shows_every_command_and_the_one_gridlens_reads():
    app = model()
    probe.main(app)
    text = "\n".join(app.lines)
    assert "ComStatsim in the active study case: 2; elsewhere in the project: 1" in text
    assert "ComStatsim #1: ACTIVE_STUDY_CASE, READ BY GRIDLENS" in text
    assert "period as GridLens reads it (startTime..endTime): YEAR 2002 .. YEAR 2003" in text
    assert "ComStatsim #2: ACTIVE_STUDY_CASE\n" in text + "\n"
    assert "ComStatsim #3: OTHER_PLACE_IN_PROJECT" in text
    assert "SetTime.cDate year: 2028" in text
    assert "planned outages by start year: YEAR 2028 x1" in text
    assert "endTime: YEAR 2028, +24 h" in text


def test_prints_no_names_and_creates_nothing():
    app = model()
    probe.main(app)
    assert not any("SECRET" in line for line in app.lines)
    assert not app.created


def test_study_case_without_qds_creates_none():
    project = Obj("SECRET-project", "IntPrj")
    case = Obj("SECRET-case", "IntCase", project)
    app = App(project, case, None)
    probe.main(app)
    assert not app.created
    assert any("holds no ComStatsim" in line for line in app.lines)
