"""Verify probe conclusions and isolation; these mocks cannot verify a PF button action."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / "powerfactory_tests" / "test_elmres_default_variables.py"
    spec = importlib.util.spec_from_file_location("elmres_default_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, app, monitors=()):
        self.app = app
        self.monitors = list(monitors)
        self.values = {"butdefault": 0, "calTp": 31}
        self.writes = []

    def GetClassName(self):
        return "ElmRes"

    def GetContents(self, pattern, recursive):
        assert (pattern, recursive) == ("*.IntMon", 0)
        return self.monitors[:]

    def GetAttribute(self, name):
        return self.values[name]

    def HasAttribute(self, name):
        return name in self.values

    def GetAttributeType(self, name):
        return "INTEGER"

    def GetAttributeDescription(self, name):
        return "Add default variables"

    def CopyData(self, source):
        assert self is not source
        self.values = source.values.copy()
        return self.app.copy_code

    def SetAttribute(self, name, value):
        assert self is self.app.temporary, "the source result must never be written"
        self.writes.append((name, value))
        self.values[name] = value
        self.app.action(self)


class Monitor:
    def __init__(self, kind, variable, target=None):
        self.values = {"classnm": kind, "vars": [variable], "obj_id": target}

    def GetAttribute(self, name):
        return self.values[name]


class App:
    def __init__(self):
        self.messages = []
        self.action = lambda result: None
        self.copy_code = 0
        self.delete_code = 0
        self.folder_created = False
        self.deleted = False
        self.source = Result(self, [Monitor("ElmTerm", "m:P")])
        self.temporary = None
        self.qds = SimpleNamespace(GetAttribute=lambda name: self.source)

    def PrintPlain(self, message):
        self.messages.append(message)

    def GetActiveStudyCase(self):
        return self

    def GetContents(self, pattern, recursive):
        assert (pattern, recursive) == ("*.ComStatsim", 0)
        return [self.qds]

    def GetFromStudyCase(self, name):
        assert name == "ComStatsim"
        return self.qds

    def CreateObject(self, kind, name):
        if kind == "IntFolder":
            self.folder_created = True
            return self
        assert kind == "ElmRes" and self.folder_created
        self.temporary = Result(self)
        return self.temporary

    def Delete(self):
        self.deleted = True
        return self.delete_code


@pytest.mark.parametrize("effect, expected", [
    ("none", "NO_SELECTION_CHANGE"),
    ("unrelated", "PARTIAL_SELECTION_CHANGE"),
    ("partial", "PARTIAL_SELECTION_CHANGE"),
    ("per_object", "PARTIAL_SELECTION_CHANGE"),
    ("complete", "DEFAULT_VARIABLES_ADDED"),
    ("write_error", "BUTTON_WRITE_FAILED"),
])
def test_only_complete_class_wide_selection_is_success(probe, effect, expected):
    app = App()
    original = probe.selection(app.source)

    def action(result):
        assert result.values["calTp"] == 31
        if effect == "write_error":
            raise RuntimeError("button is not writable")
        if effect == "none":
            return
        if effect == "unrelated":
            result.monitors = [Monitor("ElmTerm", "m:P")]
        else:
            pairs = probe.REQUIRED[:1] if effect == "partial" else probe.REQUIRED
            for kind, variable in pairs:
                target = SimpleNamespace(GetClassName=lambda kind=kind: kind) if effect == "per_object" else None
                result.monitors.append(Monitor(kind, variable, target))

    app.action = action
    assert probe.run(app) is (effect == "complete")
    assert app.temporary.writes == [("butdefault", 1)]
    assert app.deleted and app.source.writes == []
    assert probe.selection(app.source) == original
    output = "\n".join(app.messages)
    assert "END status=" + expected in output
    assert "RECORDING: NOT_TESTED" in output
    assert "VERIFY original result binding and variable selection: UNCHANGED" in output


def test_inspection_only_does_not_create_or_write(probe, monkeypatch):
    monkeypatch.setattr(probe, "TEST_BUTTON", False)
    app = App()
    assert probe.run(app) is True
    assert not app.folder_created and not app.source.writes
    assert "END status=INSPECTED" in app.messages[-1]


def test_failed_configuration_copy_stops_before_button_write(probe):
    app = App()
    app.copy_code = 1
    with pytest.raises(RuntimeError, match="CopyData failed"):
        probe.run(app)
    assert app.temporary.writes == [] and app.deleted


def test_failed_cleanup_is_not_reported_as_success(probe):
    app = App()
    app.delete_code = 1
    with pytest.raises(RuntimeError, match="cleanup failed"):
        probe.run(app)
    assert "END status=CLEANUP_OR_SOURCE_CHECK_FAILED" in app.messages[-1]


def test_source_change_is_detected_even_if_button_returns_normally(probe):
    app = App()
    app.action = lambda result: app.source.monitors.append(Monitor("ElmLne", "c:loading"))
    with pytest.raises(RuntimeError, match="Original variable selection changed"):
        probe.run(app)
    assert app.deleted
