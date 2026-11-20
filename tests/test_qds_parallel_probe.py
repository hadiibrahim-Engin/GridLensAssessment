"""Discovery must work with PF class metadata, without guessing dynamic fields."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / "powerfactory_tests" / "test_qds_parallel.py"
    spec = importlib.util.spec_from_file_location("qds_parallel_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Object:
    def __init__(self, values=None, descriptions=None):
        self.values = dict(values or {})
        self.descriptions = descriptions or {}
        self.writes = []

    def GetAttribute(self, key):
        return self.values[key.removeprefix("e:")]

    def GetAttributeDescription(self, key):
        return self.descriptions.get(key.removeprefix("e:"), "")

    def SetAttribute(self, key, value):
        self.writes.append((key, value))
        self.values[key.removeprefix("e:")] = value

    def GetAttributes(self):
        pytest.fail("GetAttributes returns transfer values, not the attribute catalogue")


class Manager(Object):
    def __init__(self):
        super().__init__()
        self.workers = 4
        self.worker_writes = []

    def GetNumSlave(self):
        return self.workers

    def SetNumSlave(self, value):
        self.worker_writes.append(value)
        self.workers = value
        return 0


class App:
    def __init__(self, code=0):
        # minimumCases/taskBlockSize are artificial metadata names, not claimed
        # PowerFactory API mappings. Only iEnableParl comes from the user.
        self.descriptions = {
            "iEnableParl": "Enable parallel computing",
            "minimumCases": "Minimum number of cases",
            "taskBlockSize": "Block size",
            "startTime": "Start time",
            "loc_name": "Name",
        }
        self.qds = Object({"iEnableParl": 0, "minimumCases": 24, "taskBlockSize": 8,
                           "startTime": 1794913200, "loc_name": "PRIVATE_NAME"}, self.descriptions)
        self.clock = Object({"cDate": 20261117, "cTime": 3600})
        self.manager = Manager()
        self.messages, self.calls = [], []

        def execute():
            self.calls.append((self.qds.GetAttribute("iEnableParl"), self.manager.GetNumSlave()))
            self.clock.SetAttribute("cTime", 7200)
            if isinstance(code, BaseException):
                raise code
            return code

        self.qds.Execute = execute

    def PrintPlain(self, message):
        self.messages.append(message)

    def GetInterfaceVersion(self):
        return 2

    def GetAvailableAttributesAsJson(self, label, calculation, balanced, namespace, properties):
        assert (calculation, balanced, namespace, properties) == ("", 1, "e", "description,data_type,unit")
        return json.dumps({"class": label, "attributes": [
            {"namespace": "e", "name": key,
             "instances": [{"description": meaning, "data_type": "int"}]}
            for key, meaning in self.descriptions.items()
        ] if label == "ComStatsim" else []})

    def GetAvailableAttributes(self, *args):
        return ""

    def GetActiveStudyCase(self):
        return self

    def GetContents(self, pattern, recursive):
        if pattern == "*.ComStatsim":
            return [self.qds]
        if pattern == "*.SetTime":
            return [self.clock]
        assert pattern == "*.SetParalman"
        return [self.manager] if self.manager else []

    def GetFromStudyCase(self, name):
        return {"ComStatsim": self.qds, "SetTime": self.clock}[name]

    def GetUserManager(self):
        return self

    def GetParent(self):
        return self

    def GetUserSettings(self):
        return self

    def GetNumProcesses(self):
        return self.manager.GetNumSlave()


def test_default_discovers_enable_threshold_and_block_without_writing(probe):
    app = App()
    assert probe.INSPECT_ONLY and not probe.EXECUTE_QDS
    assert probe.PARALLEL_ATTRIBUTE == "iEnableParl"
    assert probe.run(app)
    log = "\n".join(app.messages)
    assert "VALUE ComStatsim.e:iEnableParl: 0" in log
    assert "VALUE ComStatsim.e:minimumCases: 24" in log
    assert "VALUE ComStatsim.e:taskBlockSize: 8" in log
    assert "PRIVATE_NAME" not in log and "1794913200" not in log
    assert not app.qds.writes and not app.clock.writes
    assert not app.manager.worker_writes and not app.calls
    assert "END status=INSPECTED | restoration=NOT_NEEDED" in log


def test_text_catalogue_fallback_skips_result_attributes(probe):
    app = App()
    app.GetAvailableAttributesAsJson = lambda *args: "invalid JSON"
    app.GetAvailableAttributes = lambda *args: "e:iEnableParl\nminimumCases\ne:taskBlockSize\nc:fakeResult\n"
    assert probe.run(app)
    log = "\n".join(app.messages)
    assert "VALUE ComStatsim.e:minimumCases: 24" in log
    assert "VALUE ComStatsim.e:taskBlockSize: 8" in log
    assert "fakeResult" not in log
    assert "failed (JSONDecodeError)" in log


def test_discovery_survives_missing_candidate_and_missing_manager(probe):
    app = App()
    del app.qds.values["iEnableParl"]
    app.descriptions["actualOption"] = "Parallel computing"
    app.qds.values["actualOption"] = 1
    app.manager = None
    assert probe.run(app)
    log = "\n".join(app.messages)
    assert "VALUE ComStatsim.e:actualOption: 1" in log
    assert "VALUE ComStatsim.e:iEnableParl: read failed" in log
    assert "status=INSPECTED" in log
    assert not app.qds.writes and not app.calls


def test_direct_user_candidate_when_class_catalogue_api_is_missing(probe):
    app = App()
    app.GetAvailableAttributesAsJson = None
    app.GetAvailableAttributes = None
    assert probe.run(app)
    log = "\n".join(app.messages)
    assert "METHOD Application.GetAvailableAttributesAsJson: ABSENT" in log
    assert "VALUE ComStatsim.e:iEnableParl: 0" in log
    assert not app.qds.writes


@pytest.mark.parametrize("code", [0, 1, None, RuntimeError("execution failed"), KeyboardInterrupt()])
def test_explicit_execution_restores_options_workers_and_clock(probe, monkeypatch, code):
    monkeypatch.setattr(probe, "INSPECT_ONLY", False)
    app = App(code)
    if code == 0:
        assert probe.run(app, execute=True)
    else:
        with pytest.raises((RuntimeError, KeyboardInterrupt)):
            probe.run(app, execute=True)
    assert app.calls == [(1, 2)]
    assert app.qds.GetAttribute("iEnableParl") == 0
    assert app.qds.GetAttribute("minimumCases") == 24
    assert app.qds.GetAttribute("taskBlockSize") == 8
    assert app.manager.workers == 4
    assert app.clock.values == {"cDate": 20261117, "cTime": 3600}


def test_configuration_mode_does_not_run_qds(probe, monkeypatch):
    monkeypatch.setattr(probe, "INSPECT_ONLY", False)
    app = App()
    assert probe.run(app)
    assert not app.calls
    assert app.qds.writes == [("iEnableParl", 1), ("iEnableParl", 0)]
    assert app.manager.worker_writes == [2, 4]


def test_missing_qds_is_not_created(probe):
    app = App()
    app.GetContents = lambda *args: []
    app.GetFromStudyCase = lambda *args: pytest.fail("Would create a missing QDS")
    with pytest.raises(RuntimeError, match="No existing ComStatsim"):
        probe.run(app)


def test_restoration_failure_does_not_skip_other_restoration(probe, monkeypatch):
    monkeypatch.setattr(probe, "INSPECT_ONLY", False)
    app = App()
    set_attribute = app.qds.SetAttribute

    def reject_restore(key, value):
        if value == 0:
            raise RuntimeError("cannot restore option")
        return set_attribute(key, value)

    app.qds.SetAttribute = reject_restore
    with pytest.raises(RuntimeError, match="Restoration failed: iEnableParl"):
        probe.run(app, execute=True)
    assert app.manager.workers == 4
    assert app.clock.GetAttribute("cTime") == 3600
