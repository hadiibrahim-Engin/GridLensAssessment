"""Standalone ComPython: diagnose and test explicit QDS parallel settings.

Activate a study case with a configured QDS, then run this whole file as a
separate ComPython. Copy everything from BEGIN through END, including native
PowerFactory calculation messages. main.py/main_qt.py are not imported.

Default: INSPECT_ONLY=True discovers actual INPUT attributes using the class
catalogue (GetAvailableAttributesAsJson, falling back to GetAvailableAttributes).
It neither requires nor guesses a QDS parallel attribute. No calculation runs.
The catalogue and method availability are logged even if values cannot be read.

After the log identifies the correct attribute, set PARALLEL_ATTRIBUTE to that
name and INSPECT_ONLY=False to test configuration. Set EXECUTE_QDS=True to run
ONE complete configured QDS and write its normal results
(earlier results can be overwritten). False tests configuration without QDS.
INSPECT_ONLY=True reads settings without changing them or running QDS.
Changed options, worker count and study time are restored and read back even on
failure; calculation results are not restored.

The QDS attribute's description must identify parallel computing before we
write it. No attribute is selected automatically. SetParalman.GetNumSlave/SetNumSlave and
SetUser.GetNumProcesses are documented in the PF 2026 Python reference.
"""

import json
import re
import sys
import time

PROBE_VERSION = "3.0"
EXECUTE_QDS = False
INSPECT_ONLY = True
PARALLEL_ATTRIBUTE = "iEnableParl"  # User-supplied candidate; inspect its metadata/readback first.
PARALLEL_VALUE = 1
REQUESTED_WORKERS = 2  # Explicit count >= 2; -1 requests all available cores.

PARALLEL_PATTERN = re.compile(r"parall|multi.?core|multi.?process|mehrkern|prozessor|worker|slave", re.I)
RELATED_PATTERN = re.compile(
    r"parall|parl|multi.?core|multi.?process|mehrkern|prozessor|worker|slave|block|"
    r"min.*(?:case|calc|task)|minimum|mindest", re.I)
ATTRIBUTE_NAME = re.compile(r"^(?:e:)?[A-Za-z_][A-Za-z0-9_]*$")


def description(obj, key):
    try:
        return " ".join(str(obj.GetAttributeDescription(key) or "").split())
    except Exception:
        return ""


def input_key(name, namespace="e"):
    """Keep only scalar input attribute names from the API, never result names."""
    if not isinstance(name, str) or namespace not in ("", "e"):
        return None
    name = name.strip()
    if not ATTRIBUTE_NAME.fullmatch(name):
        return None
    return name if name.startswith("e:") else "e:" + name


def catalogue(app, label, emit):
    """Enumerate real attribute names; GetAttributes() returns values, not names."""
    records = {}
    for method_name in ("GetAvailableAttributesAsJson", "GetAvailableAttributes"):
        try:
            method = getattr(app, method_name)
            args = (label, "", 1, "e")
            if method_name.endswith("AsJson"):
                args += ("description,data_type,unit",)
            raw = method(*args)
            if method_name.endswith("AsJson"):
                data = json.loads(raw)
                for entry in data.get("attributes") or []:
                    key = input_key(entry.get("name"), entry.get("namespace", "e"))
                    if key is None:
                        continue
                    instances = entry.get("instances") or []
                    meaning = " | ".join(str(item.get("description") or "") for item in instances)
                    kind = ",".join(sorted({str(item.get("data_type") or "") for item in instances}))
                    records[key] = (" ".join(meaning.split()), kind)
            else:
                for line in raw.splitlines():
                    key = input_key(line)
                    if key is not None:
                        records[key] = ("", "")
            emit("CATALOG {}: {} -> {} input attribute(s)".format(label, method_name, len(records)))
            if records:
                return records
        except Exception as exc:
            emit("CATALOG {}: {} failed ({})".format(label, method_name, type(exc).__name__))
    return records


def inventory(app, obj, label, emit):
    records = catalogue(app, label, emit)
    # dir is only a fallback for versions/classes without an input catalogue.
    # It does not reliably expose the dynamic attributes of a PF DataObject.
    if not records and obj is not None:
        try:
            for name in dir(obj):
                if not name.startswith("_") and (RELATED_PATTERN.search(name) or name.startswith("iopt_")):
                    key = input_key(name)
                    if key is not None and not callable(getattr(obj, name, None)):
                        records[key] = ("", "")
        except Exception as exc:
            emit("CATALOG {}: dir fallback failed ({})".format(label, type(exc).__name__))
    selected_key = input_key(PARALLEL_ATTRIBUTE)
    if label == "ComStatsim" and selected_key is not None:
        records.setdefault(selected_key, ("", ""))
    matches = 0
    for key, (meaning, kind) in sorted(records.items()):
        if key is None:
            continue
        bare = key.removeprefix("e:")
        if not meaning and obj is not None:
            meaning = description(obj, key) or description(obj, bare)
        parallel = bool(RELATED_PATTERN.search(key + " " + meaning))
        selected = key == selected_key
        if label != "ComStatsim" and not (parallel or selected):
            continue
        # All QDS input NAMES/descriptions are shown, even when neither contains
        # an English/German parallel keyword. Do not dump project-valued fields.
        emit("ATTRIBUTE {}.{} | type={} | description={}".format(
            label, key, kind or "<unknown>", meaning or "<unavailable>"))
        if not (parallel or selected):
            continue
        matches += 1
        if obj is None:
            emit("VALUE {}.{}: no accessible object".format(label, key))
            continue
        for access_key in (key, bare):
            try:
                value = obj.GetAttribute(access_key)
            except Exception as exc:
                error = type(exc).__name__
                continue
            shown = repr(value) if isinstance(value, (bool, int, float)) else "<non-numeric>"
            emit("VALUE {}.{}: {} | access_key={}".format(label, key, shown, access_key))
            break
        else:
            emit("VALUE {}.{}: read failed ({})".format(label, key, error))
    emit("DISCOVERY {}: {} input attribute(s), {} parallel-related candidate(s); no automatic selection".format(
        label, len(records), matches))
    if label == "ComStatsim" and not records:
        emit("ACTION: no input catalogue exposed. Include the CATALOG errors and PowerFactory version in the log.")


def interface_info(app, emit):
    try:
        emit("INTERFACE version={!r}".format(app.GetInterfaceVersion()))
    except Exception as exc:
        emit("INTERFACE version unavailable ({})".format(type(exc).__name__))
    for name in ("GetAvailableAttributesAsJson", "GetAvailableAttributes", "GetUserManager", "GetUserSettings"):
        try:
            available = callable(getattr(app, name, None))
        except Exception:
            available = False
        emit("METHOD Application.{}: {}".format(name, "PRESENT" if available else "ABSENT"))


def find_manager(app, emit):
    """Find existing settings; never create a SetParalman in the study case."""
    try:
        code, manager = app.GetCurrentScript().GetExternalObject("parallel_manager")
    except Exception as exc:
        emit("MANAGER external object unavailable: {}".format(type(exc).__name__))
    else:
        if code == 0 and manager is not None:
            if manager.GetClassName() != "SetParalman":
                raise RuntimeError("External object 'parallel_manager' must be a SetParalman.")
            emit("MANAGER source: ComPython external object parallel_manager")
            return manager

    # GetUserManager() lives in the Configuration folder. Searching that folder
    # avoids traversing user projects and avoids guessing an object name/path.
    try:
        config = app.GetUserManager().GetParent()
        managers = list(config.GetContents("*.SetParalman", 1) or [])
    except Exception as exc:
        emit("MANAGER configuration lookup unavailable: {}".format(type(exc).__name__))
        return None
    emit("MANAGER configuration candidates: {}".format(len(managers)))
    if len(managers) == 1:
        emit("MANAGER source: Configuration (existing SetParalman)")
        return managers[0]
    return None


def process_count(app, phase, emit):
    try:
        value = app.GetUserSettings().GetNumProcesses()
        emit("PROCESSES {}: SetUser.GetNumProcesses()={!r} (reported count, not a QDS utilisation measurement)"
             .format(phase, value))
        if isinstance(value, int) and value < 2:
            emit("WARNING: PowerFactory reports fewer than two processes; inspect its native calculation messages.")
    except Exception as exc:
        emit("PROCESSES {}: unavailable ({})".format(phase, type(exc).__name__))


def run(app, execute=None):
    execute = EXECUTE_QDS if execute is None else execute

    def emit(message):
        app.PrintPlain("[QDS parallel probe] " + message)

    emit("BEGIN version={} | Python={}.{} | execute={} | inspect_only={}".format(
        PROBE_VERSION, sys.version_info.major, sys.version_info.minor, execute, INSPECT_ONLY))
    saved = []  # (label, getter, setter, original); append BEFORE attempting a write.
    status = "FAILED"
    try:
        interface_info(app, emit)
        study_case = app.GetActiveStudyCase()
        if study_case is None:
            raise RuntimeError("Activate a configured study case first.")
        # GetFromStudyCase creates missing commands. Check for an existing direct
        # child first so inspection of an unconfigured case cannot create a QDS.
        if not study_case.GetContents("*.ComStatsim", 0):
            raise RuntimeError("No existing ComStatsim in the active study case; configure QDS first.")
        qds = app.GetFromStudyCase("ComStatsim")
        if qds is None:
            raise RuntimeError("No ComStatsim is available.")
        inventory(app, qds, "ComStatsim", emit)
        manager = find_manager(app, emit)
        inventory(app, manager, "SetParalman", emit)
        workers_before = None
        if manager is not None:
            try:
                workers_before = manager.GetNumSlave()
                emit("BEFORE SetParalman.GetNumSlave()={!r}".format(workers_before))
            except Exception as exc:
                emit("BEFORE SetParalman.GetNumSlave(): unavailable ({})".format(type(exc).__name__))
        else:
            emit("MANAGER no unique accessible existing SetParalman; class catalogue shown without object values.")
        try:
            user_settings = app.GetUserSettings()
        except Exception:
            user_settings = None
        inventory(app, user_settings, "SetUser", emit)
        process_count(app, "BEFORE", emit)
        if INSPECT_ONLY:
            status = "INSPECTED"
            emit("INSPECT ONLY: no settings changed and no QDS executed.")
            return True
        if type(REQUESTED_WORKERS) is not int or (REQUESTED_WORKERS != -1 and REQUESTED_WORKERS < 2):
            raise ValueError("REQUESTED_WORKERS must be an integer >= 2 or -1 (all available cores).")
        if not ATTRIBUTE_NAME.fullmatch(PARALLEL_ATTRIBUTE) or type(PARALLEL_VALUE) is not int or PARALLEL_VALUE != 1:
            raise ValueError("Set PARALLEL_ATTRIBUTE from the diagnostic log and use PARALLEL_VALUE=1.")
        emit("REQUEST ComStatsim.{}={} | SetParalman workers={}{}".format(
            PARALLEL_ATTRIBUTE, PARALLEL_VALUE, REQUESTED_WORKERS,
            " (all available cores)" if REQUESTED_WORKERS == -1 else ""))
        try:
            original = qds.GetAttribute(PARALLEL_ATTRIBUTE)
        except Exception:
            status = "UNSUPPORTED"
            emit("UNSUPPORTED: ComStatsim.{} cannot be read; QDS was not executed.".format(PARALLEL_ATTRIBUTE))
            return False
        if type(original) not in (bool, int) or original not in (0, 1):
            status = "UNSUPPORTED"
            emit("UNSUPPORTED: selected QDS option is not a 0/1 integer; QDS was not executed.")
            return False
        meaning = description(qds, PARALLEL_ATTRIBUTE)
        if not PARALLEL_PATTERN.search(meaning):
            status = "UNSUPPORTED"
            emit("UNSUPPORTED: attribute description does not identify parallel computing; no settings changed. "
                 "Use DISCOVER output to confirm the correct attribute.")
            return False
        if manager is None:
            raise RuntimeError("No unique existing SetParalman found; no settings changed. "
                               "Bind the existing Parallel Computing Manager as the ComPython external object "
                               "'parallel_manager', then rerun.")
        if type(workers_before) is not int or (workers_before != -1 and workers_before < 1):
            raise RuntimeError("Original GetNumSlave value cannot be safely restored; no settings changed.")
        emit("BEFORE ComStatsim.{}={!r} | SetParalman.GetNumSlave()={!r}".format(
            PARALLEL_ATTRIBUTE, original, workers_before))
        # Capture both time fields before the first mutation; a partial read must
        # never leave an option changed or allow a calculation to start.
        if execute:
            if not study_case.GetContents("*.SetTime", 0):
                raise RuntimeError("No existing SetTime in the active study case; QDS was not executed.")
            clock = app.GetFromStudyCase("SetTime")
            if clock is None:
                raise RuntimeError("No SetTime is available; QDS was not executed.")
            time_values = [(key, clock.GetAttribute(key)) for key in ("cDate", "cTime")]
            for key, value in time_values:
                saved.append(("SetTime." + key, lambda k=key: clock.GetAttribute(k),
                              lambda v, k=key: clock.SetAttribute(k, v), value))
        saved.append(("SetParalman workers", manager.GetNumSlave, manager.SetNumSlave, workers_before))
        code = manager.SetNumSlave(REQUESTED_WORKERS)
        actual = manager.GetNumSlave()
        emit("SET SetParalman.SetNumSlave({}) -> {!r} | readback={!r}".format(REQUESTED_WORKERS, code, actual))
        if code != 0 or code is None or actual != REQUESTED_WORKERS:
            raise RuntimeError("Worker count was not verified; QDS was not executed.")
        saved.append((PARALLEL_ATTRIBUTE, lambda: qds.GetAttribute(PARALLEL_ATTRIBUTE),
                      lambda v: qds.SetAttribute(PARALLEL_ATTRIBUTE, v), original))
        code = qds.SetAttribute(PARALLEL_ATTRIBUTE, PARALLEL_VALUE)
        actual = qds.GetAttribute(PARALLEL_ATTRIBUTE)
        emit("SET ComStatsim.{}: target={} | API return={!r} | readback={!r}".format(
            PARALLEL_ATTRIBUTE, PARALLEL_VALUE, code, actual))
        if actual != PARALLEL_VALUE:
            raise RuntimeError("The option did not read back as 1; QDS was not executed.")
        process_count(app, "CONFIGURED", emit)
        emit("VERIFIED configuration: parallel option=1 | requested workers={} | readback workers={}".format(
            REQUESTED_WORKERS, manager.GetNumSlave()))
        if not execute:
            status = "CONFIGURATION_VERIFIED"
            emit("QDS execution skipped (EXECUTE_QDS=False).")
            return True
        emit("EXECUTE BEGIN: one QDS, complete configured period; normal results may be overwritten.")
        started = time.monotonic()
        try:
            code = qds.Execute()
        finally:
            emit("EXECUTE elapsed {:.2f} s".format(time.monotonic() - started))
        emit("EXECUTE return={!r}".format(code))
        process_count(app, "AFTER_QDS", emit)
        if code is None or code != 0:
            raise RuntimeError("QDS failed; inspect PowerFactory calculation messages.")
        status = "QDS_COMPLETED"
        emit("QDS completed with verified settings. Actual parallel utilisation: NOT VERIFIED by this probe. "
             "Include native PF messages about workers/parallel execution in the shared log.")
        return True
    except BaseException as exc:
        emit("ERROR {}: {}".format(type(exc).__name__, exc))
        raise
    finally:
        errors = []
        for label, getter, setter, original in reversed(saved):
            try:
                setter(original)
                actual = getter()
                if actual != original:
                    raise RuntimeError("readback mismatch: expected {!r}, got {!r}".format(original, actual))
                # Do not print study times; only confirm restoration.
                emit("RESTORE {}: VERIFIED{}".format(
                    label, "" if label.startswith("SetTime.") else " | value={!r}".format(actual)))
            except Exception as exc:
                errors.append("{}: {}".format(label, exc))
                emit("RESTORE {}: FAILED ({})".format(label, type(exc).__name__))
        if errors:
            emit("END status=RESTORATION_FAILED | " + "; ".join(errors))
            raise RuntimeError("Restoration failed: " + "; ".join(errors))
        emit("END status={} | restoration={}".format(status, "VERIFIED" if saved else "NOT_NEEDED"))


def main():
    import powerfactory as pf

    app = pf.GetApplication()
    if app is None:
        raise RuntimeError("PowerFactory application is unavailable.")
    return run(app)


if __name__ == "__main__":
    main()
