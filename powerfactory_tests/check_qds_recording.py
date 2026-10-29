"""Outage Assessment probe: where does the quasi-dynamic simulation keep its result variables, and can a run be kept?

Diagnostic tool, not part of the Outage Assessment delivery. Run it as its own
ComPython in the study case Outage Assessment uses. It answers the questions the
first real Outage Assessment 8.0 run left open:

Q1  Where is the variable selection of the QDS? The configured result object
    (ComStatsim.results) lay in the user's temporary folder and held no IntMon;
    a copy of it recorded only the two status columns.
Q2  Does a QDS run as configured record loading and voltage, and into which
    object (the same one, a new temporary one)?
Q3  Does a copy of that object made AFTER the run keep its data, also after the
    next QDS run overwrites the original? (Outage Assessment would keep each run that way;
    the n-1 results are kept the same way.)
Q4  Does the n-1 time sweep calculate exactly the study times written into
    ComSimoutage.studyTime? (Outage Assessment wrote 2, PowerFactory calculated 4.)

Part A (Q1) only reads. Parts B to D calculate and run only with
ENABLED = True: B runs the QDS twice with its own settings (as pressing
"Execute" does), C makes one copy of the result object in the study case and
deletes it again (KEEP_PROBE_COPY keeps it), D writes studyTime and bIgnoreTime
of the contingency analysis, runs it once and restores and verifies both.
The Study Case time is restored after every run.

Privacy: no object name, path, user, study time or result value is printed.
Printed are PowerFactory class names, attribute and variable names (c:loading),
option numbers, counts, TRUE/FALSE and positions in QDS steps relative to a
reference time. Locations are reduced to STUDY_CASE, PROJECT, USER_TMP, OTHER.
"""

import math
import re

ENABLED = False
KEEP_PROBE_COPY = False
PROBE_VERSION = "1.0"
COPY_NAME = "OA_probe_copy"
ASSESSED = ("c:loading", "m:loading", "m:u", "m:u1")
STEP_SECONDS = {0: 1, 1: 60, 2: 3600, 3: 86400}
STATSIM_PATTERN = re.compile(r"res|rec|var|mon|sav|out|file|buf|calc|store", re.I)
SWEEP_PATTERN = re.compile(r"time|per|step|sweep|ts$|phase|planned", re.I)
CLASS_RE = re.compile(r"^[A-Z][a-z]{2}[A-Za-z0-9]{1,30}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
VARIABLE_RE = re.compile(r"^[a-z]{1,2}:[A-Za-z0-9_]{1,30}$")
TOKENS = {"TRUE", "FALSE", "NONE", "SKIPPED", "NOT_FOUND", "UNREADABLE", "EQUAL", "DIFFERENT", "STUDY_CASE",
          "PROJECT", "USER_TMP", "OTHER", "LARGE_NUMBER", "CLASS_WIDE"}
SAMPLE_COLUMNS = 3
# PowerFactory's temporary user folder, e.g. \<user>.IntUser\Set\Tmp\RecB\ (the folder class may be shown).
TMP_RE = re.compile(r"\\Set(\.\w+)?\\Tmp(\.\w+)?\\")


class Out:
    """Every printed line goes through token(): only allowlisted shapes pass, anything else is reduced."""

    def __init__(self, printer):
        self.printer = printer
        self.lines = []

    def head(self, text):
        self._print("")
        self._print("[probe] " + text)

    def add(self, label, value):
        self._print("[probe]   {}: {}".format(label, value if isinstance(value, Shown) else token(value)))

    def _print(self, line):
        self.lines.append(line)
        self.printer(line)


class Shown(str):
    """A text this probe built only from tokens; printed as it is."""


def token(value):
    if value is None:
        return "NONE"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return "UNREADABLE"
        if abs(value) > 1e8:
            return "LARGE_NUMBER"
        return "{:g}".format(value)
    if isinstance(value, (list, tuple)):
        return "VECTOR({})".format(len(value))
    if isinstance(value, str):
        if value in TOKENS or CLASS_RE.match(value) or VARIABLE_RE.match(value):
            return value
        return "TEXT({})".format(len(value))
    kind = class_of(value)
    return "OBJECT {}".format(kind) if kind else "UNREADABLE"


def class_of(obj):
    try:
        kind = obj.GetClassName()
    except Exception:
        return ""
    return kind if isinstance(kind, str) and CLASS_RE.match(kind) else ""


def full_name(obj):
    try:
        return str(obj.GetFullName())
    except Exception:
        return ""


def location(obj, study_case, project):
    """Where an object lies, as a token; the path itself is never printed."""
    path = full_name(obj)
    if not path:
        return "UNREADABLE"
    if TMP_RE.search(path):
        return "USER_TMP"
    if study_case is not None and path.startswith(full_name(study_case)):
        return "STUDY_CASE"
    if project is not None and path.startswith(full_name(project)):
        return "PROJECT"
    return "OTHER"


def contents(obj, pattern, recursive=False):
    try:
        found = obj.GetContents(pattern, 1) if recursive else obj.GetContents(pattern)
        return list(found or [])
    except Exception:
        return []


def attribute_names(obj):
    for getter in ("GetAttributes", "GetAttributeNames"):
        method = getattr(obj, getter, None)
        if callable(method):
            for args in ((), (0,)):
                try:
                    names = sorted({str(item) for item in method(*args) or ()})
                except Exception:
                    continue
                if names:
                    return [name for name in names if NAME_RE.match(name)]
    try:
        return [name for name in sorted(dir(obj)) if NAME_RE.match(name) and not name.startswith("_")
                and not callable(getattr(obj, name, None))]
    except Exception:
        return []


def monitored_class(monitor):
    """The class of the object an IntMon monitors; CLASS_WIDE when it names none."""
    target = getattr(monitor, "obj_id", None)
    return "CLASS_WIDE" if target is None else class_of(target) or "OTHER"


def read(obj, attribute):
    try:
        return True, getattr(obj, attribute)
    except Exception:
        return False, None


def counts_text(items):
    counted = {}
    for item in items:
        counted[item] = counted.get(item, 0) + 1
    return Shown(", ".join("{} x{}".format(token(name), number) for name, number in sorted(counted.items())) or "none")


def dump_attributes(out, obj, pattern, study_case, project):
    for name in attribute_names(obj):
        if pattern is not None and not pattern.search(name):
            continue
        found, value = read(obj, name)
        if not found or callable(value):
            continue
        if class_of(value):
            out.add("attribute " + name, Shown("OBJECT {} @ {}".format(class_of(value), location(value, study_case, project))))
        else:
            out.add("attribute " + name, value)


def recorded(elmres):
    """(rows, {variable: columns}) of a result object, or (None, None)."""
    try:
        elmres.Load()
        rows = int(elmres.GetNumberOfRows())
        variables = {}
        for column in range(int(elmres.GetNumberOfColumns())):
            name = str(elmres.GetVariable(column))
            variables[name] = variables.get(name, 0) + 1
        return rows, variables
    except Exception:
        return None, None


def show_recording(out, label, elmres):
    rows, variables = recorded(elmres)
    if variables is None:
        out.add(label + " readable", False)
        return rows, variables
    out.add(label + " rows", rows)
    out.add(label + " columns", sum(variables.values()))
    shown = {name if VARIABLE_RE.match(name) else "OTHER": number for name, number in variables.items()}
    out.add(label + " variables", Shown(", ".join("{} x{}".format(token(name), number)
                                                  for name, number in sorted(shown.items())) or "none"))
    out.add(label + " records loading or voltage", any(name in ASSESSED for name in variables))
    return rows, variables


def sample(elmres, rows):
    """Values of up to SAMPLE_COLUMNS assessed columns at the first, middle and last row; compared, never shown."""
    values = []
    try:
        elmres.Load()
        columns = [column for column in range(int(elmres.GetNumberOfColumns()))
                   if str(elmres.GetVariable(column)) in ASSESSED][:SAMPLE_COLUMNS]
        for column in columns:
            for row in sorted({0, rows // 2, max(rows - 1, 0)}):
                returned = elmres.GetValue(row, column)
                values.append(returned[1] if isinstance(returned, (list, tuple)) and returned and returned[0] == 0 else None)
    except Exception:
        return None
    return values


def run(command):
    try:
        return command.Execute()
    except Exception as exc:
        return "ERROR " + type(exc).__name__


class Clock:
    """The Study Case time; every calculation may move it, so it is put back after each one."""

    def __init__(self, app):
        self.time = app.GetFromStudyCase("SetTime")
        self.saved = (self.time.cDate, self.time.cTime) if self.time is not None else None

    def restore(self):
        if self.saved is None:
            return True
        self.time.cDate, self.time.cTime = self.saved
        return (self.time.cDate, self.time.cTime) == self.saved


def part_a(out, app, study_case, project, qds):
    out.head("A  Where the QDS keeps its result variables (read only)")
    dump_attributes(out, qds, STATSIM_PATTERN, study_case, project)
    out.add("ComStatsim contents (classes, recursive)", counts_text(class_of(item) or "OTHER" for item in contents(qds, "*", True)))
    configured = getattr(qds, "results", None)
    out.add("configured result object", configured is not None)
    if configured is not None:
        out.add("configured result object location", location(configured, study_case, project))
        parent = getattr(configured, "GetParent", lambda: None)()
        out.add("configured result object parent class", class_of(parent) or "NONE")
        out.add("configured result object contents (classes)", counts_text(class_of(item) or "OTHER" for item in contents(configured, "*")))
        dump_attributes(out, configured, None, study_case, project)
        show_recording(out, "configured result object now", configured)
    out.add("study case contents (classes, top level)", counts_text(class_of(item) or "OTHER" for item in contents(study_case, "*")))
    for scope, holder in (("study case", study_case), ("ComStatsim", qds), ("project", project)):
        monitors = contents(holder, "*.IntMon", True) if holder is not None else []
        out.add("IntMon in the " + scope, len(monitors))
        if monitors:
            out.add("IntMon in the {}: parent classes".format(scope),
                    counts_text(class_of(getattr(item, "GetParent", lambda: None)()) or "OTHER" for item in monitors))
            out.add("IntMon in the {}: monitored classes".format(scope), counts_text(monitored_class(item) for item in monitors))
            out.add("IntMon in the {}: variables".format(scope),
                    counts_text(name if VARIABLE_RE.match(name) else "OTHER" for item in monitors
                                for name in (str(value) for value in (getattr(item, "vars", None) or ()))))
    results = [item for item in contents(study_case, "*.ElmRes") if class_of(item) == "ElmRes"]
    out.add("result objects in the study case", len(results))
    out.add("of them with IntMon inside", sum(1 for item in results if contents(item, "*.IntMon")))
    return configured


def part_b_c(out, app, study_case, project, qds, configured, clock):
    out.head("B  QDS run as configured, recording")
    code = run(qds)
    out.add("ComStatsim.Execute returned", code)
    out.add("Study Case time restored", clock.restore())
    after = getattr(qds, "results", None)
    out.add("result object after the run is the configured one", full_name(after) == full_name(configured))
    out.add("result object after the run location", location(after, study_case, project) if after is not None else "NONE")
    if after is None:
        return
    rows, variables = show_recording(out, "result object after the run", after)
    if not variables:
        return

    out.head("C  Copy made after the run")
    first = sample(after, rows)
    try:
        copies = study_case.AddCopy(after)
        copy = copies[0] if isinstance(copies, (list, tuple)) else copies
    except Exception:
        copy = None
    out.add("AddCopy into the study case", copy is not None)
    if copy is None:
        return
    try:
        copy.loc_name = COPY_NAME
    except Exception:
        pass
    copy_rows, copy_variables = show_recording(out, "copy", copy)
    out.add("copy has the same rows and columns", (copy_rows, copy_variables) == (rows, variables))
    out.add("copy has the same values (sampled)", "EQUAL" if first and sample(copy, rows) == first else "DIFFERENT")
    out.add("copy holds IntMon", bool(contents(copy, "*.IntMon")))
    code = run(qds)
    out.add("second ComStatsim.Execute returned", code)
    out.add("Study Case time restored", clock.restore())
    out.add("result object after the second run is the same as after the first", full_name(getattr(qds, "results", None)) == full_name(after))
    unchanged = recorded(copy) == (rows, variables) and bool(first) and sample(copy, rows) == first
    out.add("copy unchanged after the second run", "EQUAL" if unchanged else "DIFFERENT")
    if KEEP_PROBE_COPY:
        out.add("probe copy kept in the study case", True)
        return
    try:
        copy.Delete()
        out.add("probe copy deleted", True)
    except Exception:
        out.add("probe copy deleted", False)


def part_d(out, app, study_case, project, qds, clock):
    out.head("D  n-1 study times")
    commands = [item for item in contents(study_case, "*.ComSimoutage") if class_of(item) == "ComSimoutage"]
    out.add("contingency analyses in the study case", len(commands))
    if len(commands) != 1:
        out.add("n-1 test", "SKIPPED")
        return
    command = commands[0]
    dump_attributes(out, command, SWEEP_PATTERN, study_case, project)
    start, end = getattr(qds, "startTime", None), getattr(qds, "endTime", None)
    try:
        step = float(qds.stepSize) * STEP_SECONDS[int(qds.stepUnit)]
        steps = int((float(end) - float(start)) // step)
    except Exception:
        out.add("QDS time grid readable", False)
        return
    reference = float(start) + (steps // 2) * step
    written = [reference, reference + step]

    def offsets(moments):
        return Shown(", ".join("{:g}".format(round((moment - reference) / step, 3)) for moment in sorted(moments)) or "none")

    for attribute in ("startTime", "endTime"):
        found, value = read(command, attribute)
        if found and isinstance(value, (int, float)):
            out.add(attribute + " in QDS steps from the written first time", Shown("{:g}".format(round((value - reference) / step, 3))))
    saved = {}
    for attribute in ("studyTime", "bIgnoreTime"):
        found, value = read(command, attribute)
        saved[attribute] = (found, list(value) if isinstance(value, (list, tuple)) else value)
        if found and isinstance(value, (list, tuple)) and attribute == "studyTime":
            out.add("studyTime before, in QDS steps from the written first time", offsets(float(item) for item in value))
    try:
        command.studyTime = list(written)
        if isinstance(saved["bIgnoreTime"][1], list):
            command.bIgnoreTime = [0.0, 0.0]
        out.add("studyTime written and read back equal", [float(item) for item in command.studyTime] == written)
        out.add("written study times, in QDS steps", offsets(written))
        code = run(command)
        out.add("ComSimoutage.Execute returned", code)
        out.add("Study Case time restored", clock.restore())
        found, value = read(command, "studyTime")
        out.add("studyTime after the run, in QDS steps", offsets(float(item) for item in value) if found and isinstance(value, (list, tuple)) else "UNREADABLE")
        result = getattr(command, "p_rescnt", None)
        moments = [getattr(sub, "cnttime", None) for sub in contents(result, "*.ElmRes")] if result is not None else []
        out.add("calculated study times (cnttime of the sub-results), in QDS steps",
                offsets(float(moment) for moment in moments if isinstance(moment, (int, float))))
    finally:
        for attribute in ("bIgnoreTime", "studyTime"):
            found, value = saved[attribute]
            if not found:
                continue
            try:
                setattr(command, attribute, value)
            except Exception:
                pass
            current = read(command, attribute)[1]
            out.add("restored " + attribute, (list(current) if isinstance(current, (list, tuple)) else current) == value)


def main(app=None, printer=print):
    if app is None:
        import powerfactory
        app = powerfactory.GetApplication()
    out = Out(lambda line: app.PrintPlain(line) if hasattr(app, "PrintPlain") else printer(line))
    out.head("Outage Assessment probe QDS recording {} (ENABLED = {})".format(PROBE_VERSION, "TRUE" if ENABLED else "FALSE"))
    study_case = app.GetActiveStudyCase()
    project = app.GetActiveProject()
    qds = app.GetFromStudyCase("ComStatsim")
    out.add("study case active", study_case is not None)
    out.add("ComStatsim found", qds is not None)
    if study_case is None or qds is None:
        return out.lines
    configured = part_a(out, app, study_case, project, qds)
    if not ENABLED:
        out.head("B to D not run: set ENABLED = True to run the QDS twice, copy its result object and test the n-1 study times")
        return out.lines
    clock = Clock(app)
    for part in (lambda: part_b_c(out, app, study_case, project, qds, configured, clock),
                 lambda: part_d(out, app, study_case, project, qds, clock)):
        try:
            part()
        except Exception as exc:
            out.add("part stopped with", type(exc).__name__ if CLASS_RE.match(type(exc).__name__) else "ERROR")
            out.add("Study Case time restored", clock.restore())
    out.head("done")
    return out.lines


if __name__ == "__main__":
    main()
