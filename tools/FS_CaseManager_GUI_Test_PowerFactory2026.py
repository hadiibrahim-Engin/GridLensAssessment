# -*- coding: utf-8 -*-
"""
GridLens Case Manager - GUI test for DIgSILENT PowerFactory 2026 (no calculation).

Opens exactly the case manager of the production script
powerfactory/gridlens_report.py with the planned outages of the active project,
so that the window that GridLens shows before a calculation can be tried in
PowerFactory on its own:

  1. Does tkinter with Tcl/Tk work in this PowerFactory installation?
  2. Does the case manager open from a ComPython and react to clicks?
  3. Does a click on a case show its planned outages; do add, remove, copy,
     fixed outages, relations, rules and the timeline work with real data?
  4. Does "Start calculation" hand the configuration back to Python?

Read-only: this script writes no PowerFactory attribute, starts no QDS and
switches nothing. "Save configuration" and "Load saved configuration" in the
window work on a temporary copy, so not even the GridLens case configuration in
~/GridLens/cases changes. After "Start calculation" the configuration and the
preview are printed to the output window; nothing is calculated.

Set GRIDLENS_SCRIPT to the full path of gridlens_report.py when PowerFactory
runs this file without its location (e.g. as pasted script text).
Dependencies: Python standard library and the PowerFactory module only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

# Full path of powerfactory/gridlens_report.py; '' looks next to this file.
GRIDLENS_SCRIPT = r''
# Start from the case configuration GridLens saved for this project (read only).
USE_SAVED_CONFIGURATION = True

PREFIX = "[CASE-MANAGER-TEST] "
H, D = 3600.0, 86400.0


def log(app, message):
    text = PREFIX + str(message)
    printer = getattr(app, "PrintPlain", None) if app is not None else None
    if callable(printer):
        try:
            printer(text)
            return
        except Exception:
            pass
    print(text, flush=True)


def script_path():
    """Where gridlens_report.py is: GRIDLENS_SCRIPT, else ../powerfactory next to this file."""
    if GRIDLENS_SCRIPT:
        return GRIDLENS_SCRIPT
    here = globals().get("__file__")
    if not here:
        return ""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(here))), "powerfactory", "gridlens_report.py")


def load_gridlens(path):
    """The production module, loaded without running it (it only runs under __main__)."""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(
            "gridlens_report.py was not found ({}). Set GRIDLENS_SCRIPT at the top of this file to its full path."
            .format(path or "this script's location is unknown"))
    spec = importlib.util.spec_from_file_location("gridlens_report_case_manager_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def demo_records(gl):
    """Clearly named demo outages when PowerFactory or its outages are not available."""
    start = time.mktime((2016, 7, 1, 0, 0, 0, 0, 0, -1))
    rows = (("DEMO FS 1", "DEMO line L100", 10, 35), ("DEMO FS 2", "DEMO line L200", 7, 32),
            ("DEMO FS 3", "DEMO transformer T300", 20, 27), ("DEMO FS 4", "DEMO line L400", 3, 8),
            ("DEMO FS KW10", "DEMO line L500", -116, -111), ("DEMO FS KW40", "DEMO line L500", 94, 99))
    records = []
    for name, equipment, first, last in rows:
        window = (start + first * D, start + last * D)
        records.append({"key": "DEMO\\" + name, "id": name, "name": name, "window": window,
                        "component_keys": ["DEMO\\" + equipment], "equipment_name": equipment, "equipment_type": "demo",
                        "switching_actions": "", "start_time": gl._format_pf_time(window[0]), "end_time": gl._format_pf_time(window[1]),
                        "priority": 1, "originally_ignored": False, "source_class": "demo", "status": "CONSIDERED"})
    return records, (start, start + 31 * D)


def read_project(app, gl):
    """Planned outages, simulated period and project key, read only; demo data where PowerFactory has none."""
    if app is None:
        return None, None, "DEMO", "PowerFactory is not available"
    try:
        qds = app.GetFromStudyCase("ComStatsim")
    except Exception:
        qds = None
    period = gl.qds_period(qds) if qds is not None else (None, None)
    try:
        records, _ = gl.classify_planned_outages(app, gl.RunLogger(app), period)
    except Exception as exc:
        return None, period, "DEMO", "planned outages could not be read: {}".format(gl._friendly_exception(exc))
    if not records:
        return None, period, "DEMO", "the project has no planned outage"
    gl.assign_definitions(records)
    return records, period, "PowerFactory", ""


def starting_configuration(app, gl, scratch):
    """The saved configuration of the project, copied to `scratch`; save and load in the window use the copy."""
    try:
        project_key = gl.object_key(app.GetActiveProject()) if app is not None else "demo project"
    except Exception:
        project_key = "project"
    copy = os.path.join(scratch, "cases.json")
    if USE_SAVED_CONFIGURATION and app is not None:
        real = gl.case_config_path(project_key)
        if os.path.isfile(real):
            shutil.copyfile(real, copy)
            return gl.load_case_config(copy), copy, "saved configuration " + real
    return gl.empty_case_config(project_key), copy, "empty configuration"


def run(app):
    log(app, "Python {}; this test changes nothing in PowerFactory and calculates nothing.".format(sys.version.split()[0]))
    try:
        import tkinter as tk
        log(app, "tkinter imported: Tcl {}, Tk {}.".format(tk.TclVersion, tk.TkVersion))
    except Exception as exc:
        log(app, "FAIL: tkinter cannot be imported: {!r}. This Python has no Tcl/Tk; GridLens would fall back to the saved "
                 "configuration or one case per planned outage.".format(exc))
        return False
    try:
        gl = load_gridlens(script_path())
    except Exception as exc:
        log(app, "FAIL: {}".format(exc))
        return False
    log(app, "Case manager of GridLens {} loaded from {}.".format(gl.PUBLISHER_VERSION, script_path()))
    records, period, source, reason = read_project(app, gl)
    if source == "DEMO":
        records, period = demo_records(gl)
        log(app, "DEMO DATA: {}; {} demo planned outages are shown.".format(reason, len(records)))
    else:
        log(app, "{} planned outages read from PowerFactory (read only).".format(len(records)))
    scratch = tempfile.mkdtemp(prefix="gridlens_case_manager_test_")
    try:
        config, config_copy, origin = starting_configuration(app, gl, scratch)
        log(app, "Starting from the {}; save and load in the window use the copy {}.".format(origin, config_copy))
        try:
            outcome = gl.run_case_manager(records, config, period, config_copy, "case manager test",
                                          qds_text=gl.qds_period_text(period))
        except gl.CaseManagerUnavailable as exc:
            log(app, "FAIL: {}".format(exc))
            return False
        except Exception:
            log(app, "FAIL: the case manager stopped with an error:\n" + traceback.format_exc())
            return False
        if outcome is None:
            log(app, "Cancel: no configuration handed over; GridLens would stop here without any change.")
            return True
        lines, problems = gl.CaseEditor(records, outcome, period).summary()
        log(app, "Start calculation: the configuration was handed back. GridLens would now calculate:")
        for label, value in lines:
            log(app, "  {:<26} {}".format(label, value))
        for problem in problems:
            log(app, "  problem: {}".format(problem))
        log(app, "Configuration (JSON):\n" + json.dumps(outcome, ensure_ascii=False, indent=2))
        log(app, "PASS: GUI test finished. Nothing was calculated and no PowerFactory object was changed.")
        return True
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    app = None
    try:
        import powerfactory
        app = powerfactory.GetApplication()
    except Exception as exc:
        print(PREFIX + "PowerFactory is not available ({}); demo data is used.".format(exc), flush=True)
    return run(app)


if __name__ == "__main__":
    main()
