"""The PowerFactory GUI test tool: a separate script with its own copy of the case manager; read-only, calculates nothing."""

from __future__ import annotations

import builtins
import importlib.util
import json
from pathlib import Path

import pytest

from _paths import tool as _tool

TOOL, SYNC = _tool("preview_case_manager.py"), _tool("sync_case_manager_copy.py")
if TOOL is None or SYNC is None:
    pytest.skip("development tools not in this checkout", allow_module_level=True)
SPEC = importlib.util.spec_from_file_location("case_manager_gui_test_tool", TOOL)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
SYNC_SPEC = importlib.util.spec_from_file_location("sync_case_manager_copy", SYNC)
sync = importlib.util.module_from_spec(SYNC_SPEC)
SYNC_SPEC.loader.exec_module(sync)

PERIOD = (1467324000, 1470002400)


class Obj:
    def __init__(self, name, kind, **attributes):
        self.loc_name, self.kind = name, kind
        self.__dict__.update(attributes)
        self.writes = []

    def GetClassName(self):
        return self.kind

    def GetFullName(self):
        return "\\User\\Grid.IntPrj\\{}.{}".format(self.loc_name, self.kind)

    def GetContents(self, *_args):
        return []

    def __setattr__(self, name, value):
        if "writes" in self.__dict__:
            self.writes.append(name)
        super().__setattr__(name, value)


class App:
    def __init__(self, outages):
        self.outages = outages
        self.qds = Obj("QDS", "ComStatsim", startTime=PERIOD[0], endTime=PERIOD[1], iopt_maint=0)
        self.folder = Obj("Outages", "IntPrjfolder")
        self.project = Obj("Grid", "IntPrj")
        self.folder.GetContents = self.project.GetContents = lambda pattern, *_: [o for o in outages if pattern.endswith(o.kind)]
        self.study = Obj("Study", "IntCase")
        self.study.GetContents = lambda pattern, *_: [self.qds] if pattern == "*.ComStatsim" else []
        self.lines = []
        self.executed = []
        self.qds.Execute = lambda: self.executed.append("QDS")
        for item in outages + [self.qds, self.folder, self.project]:
            item.__dict__["writes"] = []  # only what the tool writes counts

    def PrintPlain(self, message):
        self.lines.append(message)

    def GetProjectFolder(self, key):
        return self.folder if key == "outage" else None

    def GetActiveProject(self):
        return self.project

    def GetActiveStudyCase(self):
        return self.study

    def GetFromStudyCase(self, name):
        raise AssertionError("GetFromStudyCase creates a missing command; the read-only tool must not use it")


def outage(name, day):
    return Obj(name, "IntPlannedout", outserv=0, priority=1, starttime=PERIOD[0] + day * 86400, endtime=PERIOD[0] + (day + 5) * 86400,
               components=[Obj("L_" + name, "ElmLne")])


@pytest.fixture
def opened(monkeypatch, tmp_path):
    """Replace the window by a callable that records what it was given and answers like a click on a button."""
    gl = tool  # the tool carries its own case manager; nothing is loaded from main.py
    monkeypatch.setattr(gl, "CASE_CONFIG_DIR", str(tmp_path / "real_config"))
    seen = {}

    def answer(result):
        def run_case_manager(records, config, period, config_path, user="", qds_text="", qds_info=None, grids=None,
                             contingencies=None):
            seen.update(records=records, config=config, period=period, config_path=config_path, qds_text=qds_text,
                        qds_info=qds_info, grids=grids, contingencies=contingencies)
            return result(records, config) if callable(result) else result
        monkeypatch.setattr(gl, "run_case_manager", run_case_manager)
    return gl, seen, answer


def test_the_tool_opens_its_case_manager_with_the_project_outages(opened):
    gl, seen, answer = opened
    app = App([outage("FS Bedarf 1", 10), outage("FS Bedarf 2", 7)])
    answer(lambda records, config: dict(config, cases=[{"id": "A", "name": "A", "outages": [records[0]["key"]]}]))

    assert tool.run(app) is True

    assert [record["id"] for record in seen["records"]] == ["FS Bedarf 1", "FS Bedarf 2"]
    assert seen["period"] == PERIOD and seen["qds_text"] == gl.qds_period_text(PERIOD)
    assert dict(seen["qds_info"])["QDS start"] == gl._format_pf_time(PERIOD[0])
    text = "\n".join(app.lines)
    assert "Cases selected" in text and "PASS" in text and '"assessments": [' in text
    assert app.executed == [], "no QDS is started"
    assert all(item.writes == [] for item in app.outages + [app.qds]), "no PowerFactory attribute is written"


def test_save_and_load_in_the_window_use_a_temporary_copy_of_the_saved_configuration(opened, tmp_path):
    gl, seen, answer = opened
    app = App([outage("FS1", 1)])
    real = gl.case_config_path(gl.object_key(app.project))
    saved = gl.empty_case_config()
    saved["cases"] = [{"id": "S", "name": "Saved", "outages": []}]
    gl.save_case_config(real, saved, "operator")
    before = Path(real).read_text()
    answer(None)

    assert tool.run(app) is True

    assert seen["config"]["cases"][0]["id"] == "S"
    assert seen["config_path"] != real and not Path(seen["config_path"]).exists(), "the copy is removed afterwards"
    assert Path(real).read_text() == before
    assert any("Cancel" in line for line in app.lines)


def test_a_damaged_saved_configuration_does_not_stop_the_gui_test(opened):
    gl, seen, answer = opened
    app = App([outage("FS1", 1)])
    real = Path(gl.case_config_path(gl.object_key(app.project)))
    real.parent.mkdir(parents=True)
    real.write_text("{ damaged", encoding="utf-8")
    answer(None)

    assert tool.run(app) is True

    assert seen["config"]["cases"] == []
    assert any("empty configuration (The saved case configuration" in line for line in app.lines)
    assert real.read_text(encoding="utf-8") == "{ damaged", "the real file is left as it is"


def test_without_powerfactory_the_window_shows_marked_demo_data(opened, capsys):
    _, seen, answer = opened
    answer(None)

    assert tool.run(None) is True

    assert all(record["id"].startswith("DEMO") for record in seen["records"])
    assert "DEMO DATA" in capsys.readouterr().out


def test_a_missing_tkinter_is_reported_as_failure(monkeypatch, capsys):
    real_import = builtins.__import__

    def no_tk(name, *args, **kwargs):
        if name == "tkinter":
            raise ImportError("no _tkinter")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_tk)

    assert tool.run(None) is False
    assert "FAIL: tkinter cannot be imported" in capsys.readouterr().out


def test_the_tool_is_a_separate_script_that_never_loads_gridlens_report(monkeypatch, tmp_path, capsys):
    source = TOOL.read_text(encoding="utf-8")
    assert "importlib" not in source and "GRIDLENS_SCRIPT" not in source
    copied = tmp_path / "preview_case_manager.py"
    copied.write_text(source, encoding="utf-8")  # alone in a folder without main.py
    spec = importlib.util.spec_from_file_location("lonely_tool", copied)
    lonely = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lonely)
    monkeypatch.setattr(lonely, "run_case_manager", lambda *args, **kwargs: None)

    assert lonely.run(None) is True
    assert "standalone" in capsys.readouterr().out


def test_the_copied_case_manager_matches_gridlens_report():
    assert sync.current_block() == sync.copied_block(), \
        "the case manager in main.py changed: run python3 ui/sync_case_manager_copy.py"
    for name in ("CaseManagerDialog", "CaseEditor", "FilterTable", "Tooltip", "HELP_TEXTS", "resolve_request"):
        assert hasattr(tool, name), name
    header = TOOL.read_text(encoding="utf-8").split(sync.BEGIN)[0]
    for module in ("json", "os", "time", "shutil", "tempfile"):
        assert "import {}\n".format(module) in header, "the tool's own code imports {} itself".format(module)
    assert "import os\n" not in sync.current_block() and "import json\n" not in sync.current_block()


@pytest.mark.gui
def test_with_real_tk_the_tool_opens_the_new_window_and_cancel_ends_it(monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        tk.Tk().destroy()
    except Exception:
        pytest.skip("Tk cannot open a window here")
    seen = {}

    def mainloop(self):
        dialog = self.report_callback_exception.__self__
        seen["title"] = self.title()
        seen["panes"] = [dialog.case_tree.winfo_exists(), dialog.member_tree.winfo_exists(), dialog.available_tree.winfo_exists()]
        dialog.cancel()
    monkeypatch.setattr(tk.Tk, "mainloop", mainloop)

    assert tool.run(None) is True
    assert seen["title"].endswith("Case Manager") and seen["panes"] == [1, 1, 1]


def test_the_tool_needs_nothing_but_the_standard_library_and_powerfactory():
    source = TOOL.read_text(encoding="utf-8")
    imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "datetime", "hashlib", "json", "math", "os", "re", "shutil", "sys", "tempfile", "time",
                       "traceback"}
    assert json.loads(json.dumps({"ok": True}))
