"""The IntReport write probe, with an artificial IntReport that records every call."""

from __future__ import annotations

import importlib.util

import pytest

from _paths import tool

PROBE = tool("probe_report_write.py")
if PROBE is None:
    pytest.skip("development tool not in this checkout", allow_module_level=True)

SPEC = importlib.util.spec_from_file_location("probe_report_write", PROBE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class Report:
    def __init__(self, name):
        self.loc_name, self.calls, self.cells = name, [], {}

    def GetClassName(self):
        return "IntReport"

    def Reset(self):
        self.calls.append("Reset")
        self.cells.clear()
        return 0

    def CreateTable(self, table):
        self.calls.append("CreateTable " + table)
        return 0

    def CreateField(self, table, field, kind):
        self.calls.append("CreateField {}.{} {}".format(table, field, kind))
        return 0

    def SetValue(self, table, field, row, value):
        self.cells[table, field, row] = value
        return 0


class Script:
    def __init__(self, parent):
        self.parent = parent

    def GetParent(self):
        return self.parent


class App:
    def __init__(self, report):
        self.script, self.lines = Script(report), []

    def GetCurrentScript(self):
        return self.script

    def PrintPlain(self, text):
        self.lines.append(text)


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(probe, "STAGE_CELLS", (20, 200))
    monkeypatch.setattr(probe, "BLOCK_CELLS", 50)


def test_the_probe_never_resets_a_report_without_the_marker_or_without_enabled(monkeypatch, small):
    monkeypatch.setattr(probe, "ENABLED", True)
    gridlens = Report("GridLens report")
    lines = probe.main(App(gridlens))
    assert gridlens.calls == [] and "must contain 'probe'" in lines[-1]
    monkeypatch.setattr(probe, "ENABLED", False)
    marked = Report("GridLens write probe")
    assert probe.main(App(marked))[-1].startswith("Not run: set ENABLED = True") and marked.calls == []
    assert "directly below an IntReport" in probe.main(App(None))[-1]


def test_the_probe_writes_every_stage_into_new_rows_and_prints_rates_and_estimates(monkeypatch, small):
    monkeypatch.setattr(probe, "ENABLED", True)
    monkeypatch.setattr(probe, "CLEAN_UP", False)
    report = Report("GridLens write probe")
    lines = probe.main(App(report))

    assert report.calls[0] == "Reset"
    assert "CreateTable ProbeNumber" in report.calls and "CreateTable ProbeLong" in report.calls
    assert "CreateField ProbeString.field_a 0" in report.calls and "CreateField ProbeLong.value 2" in report.calls
    # 20 + 200 cells per type, in new rows: nothing is overwritten.
    for table in ("ProbeNumber", "ProbeInteger", "ProbeString"):
        assert sum(1 for key in report.cells if key[0] == table) == 220
    assert sum(1 for key in report.cells if key[0] == "ProbeLong") == 200
    assert not [field for call in report.calls if call.startswith("CreateField") for field in [call.split()[1]]
                if any(char.isdigit() for char in field)], "no digits in field names"
    text = "\n".join(lines)
    assert "cells/s" in text and "µs per cell" in text and "errors 0" in text
    assert "REF + 5 cases, one year hourly, 450 series: 23 716 800 cells -> " in text
    assert lines[-1] == "done"


def test_clean_up_resets_the_probe_report_again(monkeypatch, small):
    monkeypatch.setattr(probe, "ENABLED", True)
    report = Report("write PROBE")
    probe.main(App(report))
    assert report.calls[-1] == "Reset" and report.cells == {}
