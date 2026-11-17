"""Standalone ComPython: does ElmRes.SetAttribute('butdefault', 1) add variables?

Run this whole file as a separate ComPython in a study case with ComStatsim and
a bound ElmRes. TEST_BUTTON=True tests the write on a temporary configuration
copy, never on the bound result. CopyData preserves result parameters, excluding
containers; the temporary variable selection starts empty. No QDS or other
calculation runs. The temporary folder is deleted afterwards (PF recycle bin).

TEST_BUTTON=False only inspects the existing result. The probe prints technical
attribute/class/variable names, counts and numeric option values, not object
names, paths, recorded data or study times. Share BEGIN through END.

Writing a button attribute may only store its value without running the GUI
action. Only an actual change in IntMon/vars verifies an effect on selection.
DEFAULT_VARIABLES_ADDED requires all four required class-wide selections;
PARTIAL_SELECTION_CHANGE reports an effect that does not provide all of them.
ElmRes.SetAsDefault is deliberately not used: it selects the default result
object for plots, rather than adding default recording variables.
"""

import re
import uuid

PROBE_VERSION = "1.1"
TEST_BUTTON = True
BUTTON_ATTRIBUTE = "butdefault"
BUTTON_VALUE = 1
REQUIRED = (('ElmLne', 'c:loading'), ('ElmTr2', 'c:loading'),
            ('ElmTr3', 'c:loading'), ('ElmTerm', 'm:u'))
CLASS_NAME = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
VARIABLE_NAME = re.compile(r"^[a-z]{1,2}:[A-Za-z0-9_:]+$")


def selection(result):
    """Keep references for source checks; never print them or their names."""
    rows = []
    for monitor in result.GetContents("*.IntMon", 0) or []:
        variables = monitor.GetAttribute("vars")
        if not isinstance(variables, (list, tuple)):
            raise RuntimeError("IntMon.vars is unreadable; no reliable selection comparison is possible.")
        target = monitor.GetAttribute("obj_id")
        kind = target.GetClassName() if target is not None else monitor.GetAttribute("classnm")
        rows.append((monitor, target, kind, tuple(variables)))
    return rows


def show_selection(rows, phase, emit):
    emit("SELECTION {}: IntMon={} | variables={}".format(phase, len(rows), sum(len(row[3]) for row in rows)))
    pairs = set()
    class_wide = set()
    for _monitor, target, kind, variables in rows:
        shown_kind = kind if isinstance(kind, str) and CLASS_NAME.fullmatch(kind) else "OTHER_CLASS"
        scope = "CLASS_WIDE" if target is None else "PER_OBJECT"
        for variable in sorted(set(variables)):
            shown_variable = variable if isinstance(variable, str) and VARIABLE_NAME.fullmatch(variable) else "OTHER_VARIABLE"
            emit("VARIABLE {}: {} | {} | {}".format(phase, shown_kind, scope, shown_variable))
            pairs.add((kind, variable))
            if target is None:
                class_wide.add((kind, variable))
    for kind, variable in REQUIRED:
        emit("REQUIRED {} {} {}: selected={} | class_wide={}".format(
            phase, kind, variable, (kind, variable) in pairs, (kind, variable) in class_wide))
    return pairs


def inspect_button(result, phase, emit):
    for method, args in (("HasAttribute", (BUTTON_ATTRIBUTE,)),
                         ("GetAttributeType", (BUTTON_ATTRIBUTE,)),
                         ("GetAttributeDescription", (BUTTON_ATTRIBUTE,)),
                         ("GetAttribute", (BUTTON_ATTRIBUTE,))):
        try:
            value = getattr(result, method)(*args)
            if method == "GetAttributeDescription":
                shown = " ".join(str(value or "").split())
            elif method == "GetAttributeType":
                shown = str(value)
            else:
                shown = repr(value) if isinstance(value, (bool, int, float)) else "<non-numeric>"
            emit("ATTRIBUTE {} ElmRes.{} | {}={}".format(phase, BUTTON_ATTRIBUTE, method, shown))
        except Exception as exc:
            emit("ATTRIBUTE {} ElmRes.{} | {} failed ({})".format(
                phase, BUTTON_ATTRIBUTE, method, type(exc).__name__))


def run(app):
    def emit(message):
        app.PrintPlain("[ElmRes default probe] " + message)

    emit("BEGIN version={} | test_button={}".format(PROBE_VERSION, TEST_BUTTON))
    folder = None
    source = qds = None
    source_before = None
    status = "FAILED"
    try:
        study = app.GetActiveStudyCase()
        if study is None or not study.GetContents("*.ComStatsim", 0):
            raise RuntimeError("An active study case with an existing ComStatsim is required.")
        qds = app.GetFromStudyCase("ComStatsim")
        source = qds.GetAttribute("results")
        if source is None or source.GetClassName() != "ElmRes":
            raise RuntimeError("ComStatsim.results must already reference an ElmRes; no object was bound or created.")
        source_before = selection(source)
        inspect_button(source, "SOURCE", emit)
        show_selection(source_before, "SOURCE", emit)
        if not TEST_BUTTON:
            status = "INSPECTED"
            return True
        folder = study.CreateObject("IntFolder", "OA_probe_defaults_" + uuid.uuid4().hex[:12])
        if folder is None:
            raise RuntimeError("Could not create a temporary probe folder.")
        result = folder.CreateObject("ElmRes", "Default_variable_probe")
        if result is None:
            raise RuntimeError("Could not create a temporary ElmRes.")
        # CopyData copies parameters but excludes the source's containers/IntMon
        # and its recorded result data. No Clear/Load/Execute is called.
        code = result.CopyData(source)
        if code not in (None, 0):
            raise RuntimeError("CopyData failed; result parameters were not reliably copied.")
        before = selection(result)
        if before:
            raise RuntimeError("Temporary result selection is not empty; button effect would be ambiguous.")
        inspect_button(result, "COPY_BEFORE", emit)
        show_selection(before, "COPY_BEFORE", emit)
        emit("WRITE ElmRes.SetAttribute({!r}, {}) on temporary configuration copy".format(
            BUTTON_ATTRIBUTE, BUTTON_VALUE))
        write_error = None
        try:
            code = result.SetAttribute(BUTTON_ATTRIBUTE, BUTTON_VALUE)
            emit("WRITE returned {!r}; this alone does not prove the button action ran.".format(code))
        except Exception as exc:
            write_error = exc
            emit("WRITE failed ({})".format(type(exc).__name__))
        inspect_button(result, "COPY_AFTER", emit)
        after = selection(result)
        pairs = show_selection(after, "COPY_AFTER", emit)
        added = pairs - {(kind, variable) for _mon, _obj, kind, variables in before for variable in variables}
        emit("EFFECT: new class/variable pair(s)={}".format(len(added)))
        emit("RECORDING: NOT_TESTED (no calculation executed)")
        if write_error is not None:
            status = "BUTTON_WRITE_FAILED"
            return False
        if not added:
            status = "NO_SELECTION_CHANGE"
            emit("Writing butdefault did not add IntMon variables in this context; do not integrate as a working action.")
            return False
        class_wide = {(kind, variable) for _mon, target, kind, variables in after if target is None
                      for variable in variables}
        missing = set(REQUIRED) - class_wide
        if missing:
            status = "PARTIAL_SELECTION_CHANGE"
            emit("Missing required class-wide selections: " + ", ".join(
                "{} {}".format(kind, variable) for kind, variable in sorted(missing)))
            return False
        status = "DEFAULT_VARIABLES_ADDED"
        return True
    except BaseException as exc:
        emit("ERROR {}".format(type(exc).__name__))
        raise
    finally:
        errors = []
        if folder is not None:
            try:
                code = folder.Delete()
                if code != 0 or code is None:
                    raise RuntimeError("Delete returned {!r}".format(code))
                emit("CLEANUP temporary folder: DELETED")
            except Exception as exc:
                errors.append("temporary folder cleanup failed ({})".format(type(exc).__name__))
        if source is not None and source_before is not None:
            try:
                if qds.GetAttribute("results") != source:
                    raise RuntimeError("ComStatsim.results binding changed")
                if selection(source) != source_before:
                    raise RuntimeError("Original variable selection changed")
                emit("VERIFY original result binding and variable selection: UNCHANGED")
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            emit("END status=CLEANUP_OR_SOURCE_CHECK_FAILED | " + "; ".join(errors))
            raise RuntimeError("; ".join(errors))
        emit("END status={}".format(status))


def main():
    import powerfactory

    app = powerfactory.GetApplication()
    if app is None:
        raise RuntimeError("PowerFactory application is unavailable.")
    return run(app)


if __name__ == "__main__":
    main()
