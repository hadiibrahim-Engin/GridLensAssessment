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


def test_shows_every_command_and_the_one_outage_assessment_reads():
    app = model()
    probe.main(app)
    text = "\n".join(app.lines)
    assert "ComStatsim in the active study case: 2; elsewhere in the project: 1" in text
    assert "ComStatsim #1: ACTIVE_STUDY_CASE, READ BY OUTAGE ASSESSMENT" in text
    assert "startTime..endTime alone (read so before 29 Oct 2026): YEAR 2002 .. YEAR 2003" in text
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


def test_reads_the_period_by_its_kind_like_outage_assessment():
    """calcPeriod 0: `date` plus stepNumber steps; the old startTime/endTime would have put every outage outside."""
    project = Obj("SECRET-project", "IntPrj")
    case = Obj("SECRET-case", "IntCase", project, iStudyTime=int(Y2028))
    qds = Obj("SECRET-qds", "ComStatsim", case, calcPeriod=0, date=20280301, stepNumber=24, stepSize=1, stepUnit=2,
              startTime=int(Y2002), endTime=int(Y2002 + 365 * 86400))
    Obj("SECRET-in", "IntPlannedout", project, starttime=int(Y2028 + 3600), endtime=int(Y2028 + 7200))
    Obj("SECRET-out", "IntPlannedout", project, starttime=int(Y2028 + 40 * 86400), endtime=int(Y2028 + 41 * 86400))
    app = App(project, case, qds)
    probe.main(app)
    text = "\n".join(app.lines)
    assert "period as Outage Assessment reads it [date + stepNumber x stepSize/stepUnit (calcPeriod 0)]: 2028-03 .. 2028-03, 24 h" in text
    assert "1 inside, 1 outside, 0 not comparable" in text
    assert "if every planned outage not Ignored were in a case: 2028-03 .. 2028-04, " in text and text.endswith("h, calcPeriod 4")
    assert probe.outage_assessment_period(qds)[:2] == (Y2028, Y2028 + 86400)
    qds.calcPeriod = 2
    assert probe.outage_assessment_period(qds)[:2] == (None, None)


def test_its_outage_span_is_the_one_of_outage_assessment():
    """The probe carries a copy of outage_span; both must agree."""
    from _paths import delivered
    spec = importlib.util.spec_from_file_location("outage_assessment_for_probe", delivered("main.py"))
    gl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gl)
    for windows, step in (([(Y2028 + 600, Y2028 + 7800)], 3600), ([(Y2028, Y2028 + 86400), (Y2028 + 5e5, Y2028 + 6e5)], 900),
                          ([(Y2028, None)], 3600), ([], 3600)):
        assert probe.outage_span(windows, step) == gl.outage_span(windows, step)
