"""GridLens contingency test run: runs the complete contingency analysis on a PROJECT COPY and checks it.

Prepared for part 3, NOT to be run before Hadi releases it. Diagnostic tool,
not part of the GridLens delivery. It calculates and writes into the project,
so it refuses to do anything unless all of these hold:

1. ENABLED is True (it is False as delivered).
2. The active project is named exactly PROJECT_COPY_NAME, and that name
   contains COPY_MARKER, so it cannot be the production project by accident.
3. The active study case holds exactly one ComSimoutage (the contingency
   analysis to test), configured by the engineer, time sweep included.
4. Before every test a Yes/No dialog says what will be calculated or
   written, and the engineer answers Yes. Without a dialog (no Tk) nothing runs.

Every attribute it writes is recorded first, restored in reverse order after
the test and read back to verify the restoration, also after an error. When a
write test ran, the analysis is calculated once more with the original
settings, so that the copy's results match its settings again.

Tests (RUN selects them):

T1  Run the contingency analysis as configured (ComSimoutage.Execute) and
    check: success, study time unchanged, one sub-result per study time,
    study times as defined by the time sweep and equal to the QDS steps of
    the same study case, rows = contingencies, columns = equipment, sparse
    values (GetValue code 3), c:maxCntcy holds contingency numbers, one row
    per analysed contingency.
T2  Planned outages: calculate with isPlannedOutages = 0 and = 1 and compare
    the results; tells whether the switch applies the planned outages, which
    contingencies drop out and whether only at study times inside the window.
T3  Contingency filter: set one contingency to "Not analysed" (outserv = 1),
    calculate, check that it is missing from the results, restore.
T4  Native storage: create an IntDplmap in the study case of the copy, insert
    a key/value pair, read it back, delete the object again.
T5  Writing own values into an ElmRes: not run. The Python reference
    documents Write() for the current calculation results of monitored
    variables, not for values chosen by a script.
T6  Study times set by GridLens: the sweep shall follow the QDS period and the
    windows of the planned outages of a case. T6 picks a few QDS steps around
    the window of one planned outage (before, inside, last inside, at the end)
    and writes them (a) into the studyTime vector, else (b) as startTime /
    endTime / step. It checks which of the two the calculation follows and
    whether the planned outage is applied per study time: its contingency
    must be missing inside the window and present outside it.

Privacy: the output consists of fixed labels and fixed tokens only (PASS,
TRUE, ...). No project, study case, object or user name, no value, study time,
count or error text is printed. Two things are read locally for the safety and
the checks and never printed: the project name (compared with
PROJECT_COPY_NAME) and result values / study times (compared with each other).
"""

import hashlib
import math
import time

ENABLED = False
# The exact name of the project copy, e.g. '<project> - GridLens TEST copy'.
PROJECT_COPY_NAME = ""
COPY_MARKER = "copy"
RUN = ("T1", "T2", "T3", "T4", "T6")
# Rows and columns of a sub-result inspected per check.
SAMPLE_ROWS, SAMPLE_COLUMNS = 500, 2000
# T6 (b) calculates every QDS step from the first to the last chosen time; above this only the window start.
MAX_T6_TIMES = 48
# ComSimoutage / ComStatsim stepUnit: 0 seconds, 1 minutes, 2 hours, 3 days (4 months, 5 years not converted).
STEP_SECONDS = {0: 1, 1: 60, 2: 3600, 3: 86400}
EQUIPMENT_CLASSES = frozenset(("ElmLne", "ElmTr2", "ElmTr3", "ElmTr4", "ElmTerm", "ElmSym", "ElmGenstat", "ElmPvsys",
                               "ElmLod", "ElmCoup", "ElmScap", "ElmSind", "ElmShnt", "ElmVsc", "ElmRec", "ElmBranch"))
CODE_OK, CODE_SPARSE = 0, 3
TEST_KEY, TEST_VALUE = "gridlens.test", "value-1"
WRITTEN_ATTRIBUTES = ("isPlannedOutages", "outserv", "cDate", "cTime", "studyTime", "bIgnoreTime", "startTime",
                      "endTime", "stepSize", "stepUnit")

TOKENS = frozenset({"PASS", "FAIL", "TRUE", "FALSE", "SUCCESS", "ERROR", "NOT_RUN", "NOT_CONFIRMED", "NOT_VERIFIED",
                    "NOT_APPLICABLE", "NOT_DOCUMENTED", "ERROR_EXCEPTION", "STARTED", "VALUE_OTHER"}
                   | {"VALUE_{}".format(number) for number in range(10)})
LABELS = frozenset(
    {"Test run", "Precondition", "Final run with the original settings"}
    | {"Restored " + name for name in WRITTEN_ATTRIBUTES}
    | {"T1 " + label for label in (
        "Confirmed", "Execute", "Study time unchanged", "Sub-results created",
        "Study times match the time-sweep definition", "Study times match the studyTime vector",
        "Study times match startTime/endTime/step", "End time included", "Time sweep equals the QDS time steps",
        "Study times lie on the QDS time grid", "Rows are contingencies", "Columns are equipment",
        "Sparse values present", "c:maxCntcy holds contingency numbers", "c:maxCntcy holds row numbers",
        "One row per analysed contingency", "calcPeriod setting", "Error", "Result")}
    | {"T2 " + label for label in (
        "Confirmed", "Planned outage inside the sweep period", "Execute without planned outages",
        "Execute with planned outages", "Results differ with planned outages",
        "One row per analysed contingency without planned outages", "Planned outage active at every study time",
        "Contingencies missing with planned outages", "Missing contingency switches a planned-outage element",
        "Contingencies missing only inside the planned-outage window", "Error", "Result")}
    | {"T3 " + label for label in ("Confirmed", "Execute", "Not analysed excludes the contingency", "Error", "Result")}
    | {"T4 " + label for label in ("Confirmed", "IntDplmap created", "Key/value read back unchanged",
                                   "Test object deleted", "Error", "Result")}
    | {"T5 Result"}
    | {"T6 " + label for label in (
        "Confirmed", "Planned outage with a matching contingency", "Study times written",
        "Execute with written studyTime", "Study times follow the studyTime vector",
        "Execute with written startTime/endTime/step", "Study times follow startTime/endTime/step",
        "Missing inside the planned-outage window", "Present outside the planned-outage window",
        "Present at the window end", "Error", "Result")})
PRECONDITION_TEXTS = {
    "disabled": "ENABLED is False; this tool runs only after an explicit release",
    "name": "PROJECT_COPY_NAME must name the project copy and contain the copy marker",
    "project": "the active project is not the configured copy (PROJECT_COPY_NAME)",
    "study_case": "no active study case",
    "command": "the active study case must hold exactly one ComSimoutage",
}


class Output:
    """The only output channel: fixed labels and fixed tokens."""

    def __init__(self, printer):
        self.printer = printer
        self.lines = []

    def add(self, label, token):
        if label not in LABELS or token not in TOKENS:
            raise ValueError("label or token not on the allowlist")
        self._print("{}: {}".format(label, token))

    def text(self, key):
        """A fixed explanation line (preconditions)."""
        self._print("Nothing was done: " + PRECONDITION_TEXTS[key] + ".")

    def _print(self, line):
        self.lines.append(line)
        self.printer(line)


def flag(value):
    return "TRUE" if value else "FALSE"


def value_token(value):
    """A small setting number (an option of a command, not a value of the network) as a fixed token."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "NOT_VERIFIED"
    return "VALUE_{}".format(number) if 0 <= number <= 9 and number == value else "VALUE_OTHER"


def confirm(question):
    """Yes/No from the engineer; False without a dialog."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        try:
            return bool(messagebox.askyesno("GridLens contingency test run", question, parent=root))
        finally:
            root.destroy()
    except Exception:
        return False


def identity(obj):
    """A stable local key of a PowerFactory object: its full name (several Python wrappers can stand for
    one object, so 'is' and id() are not reliable). Read locally, never printed."""
    try:
        return "name:" + str(obj.GetFullName())
    except Exception:
        return "id:{}".format(id(obj))


def class_of(obj):
    try:
        return str(obj.GetClassName())
    except Exception:
        return ""


def contents(obj, pattern, recursive=0):
    try:
        return list(obj.GetContents(pattern, recursive) or [])
    except Exception:
        return []


def of_class(obj, class_name, recursive=0):
    return [item for item in contents(obj, "*." + class_name, recursive) if class_of(item) == class_name]


class Restorer:
    """Records original values and puts them back, verified, in reverse order."""

    def __init__(self, output):
        self.output = output
        self.changes = []

    def write(self, obj, attribute, value, same=None):
        original = getattr(obj, attribute)
        self.changes.append((obj, attribute, original))
        setattr(obj, attribute, value)
        written = getattr(obj, attribute)
        if not (same(written, value) if same else written == value):
            raise RuntimeError("an attribute did not accept the value")

    def restore(self):
        ok = True
        for obj, attribute, original in reversed(self.changes):
            try:
                setattr(obj, attribute, original)
                restored = getattr(obj, attribute) == original
            except Exception:
                restored = False
            ok &= restored
            if attribute in WRITTEN_ATTRIBUTES:
                self.output.add("Restored " + attribute, flag(restored))
        self.changes = []
        return ok


def preconditions(app):
    """The key of the reason not to run, or None."""
    if not ENABLED:
        return "disabled"
    if not PROJECT_COPY_NAME or COPY_MARKER.lower() not in PROJECT_COPY_NAME.lower():
        return "name"
    project = app.GetActiveProject()
    # The name is compared locally and never printed.
    if project is None or getattr(project, "loc_name", "") != PROJECT_COPY_NAME:
        return "project"
    study_case = app.GetActiveStudyCase()
    if study_case is None:
        return "study_case"
    if len(of_class(study_case, "ComSimoutage")) != 1:
        return "command"
    return None


# --- reading helpers (values stay local) ------------------------------------------
def study_time(study_case):
    settings = of_class(study_case, "SetTime")
    return tuple((getattr(item, "cDate", None), getattr(item, "cTime", None)) for item in settings), settings


def time_steps(command):
    """The study times a command defines: start, start + step, ... up to end (both variants of the end)."""
    try:
        start, end = float(command.startTime), float(command.endTime)
        step = float(command.stepSize) * STEP_SECONDS[int(command.stepUnit)]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None, None
    if step <= 0 or end < start:
        return None, None
    inclusive, moment = [], start
    while moment <= end + 1e-6 and len(inclusive) < 100000:
        inclusive.append(moment)
        moment += step
    exclusive = [moment for moment in inclusive if moment < end - 1e-6]
    return inclusive, exclusive


def vector_times(command):
    """The study times of the studyTime vector, without those marked in bIgnoreTime."""
    try:
        times = [float(value) for value in command.studyTime]
    except (AttributeError, TypeError, ValueError):
        return None
    try:
        ignore = list(command.bIgnoreTime)
    except (AttributeError, TypeError):
        ignore = []
    if len(ignore) == len(times):
        times = [moment for moment, skip in zip(times, ignore) if not skip]
    return sorted(times) or None


def same_times(first, second, tolerance=1.0):
    return first is not None and second is not None and len(first) == len(second) and all(
        abs(a - b) <= tolerance for a, b in zip(sorted(first), sorted(second)))


def on_grid(times, command):
    """Whether every time lies on the time grid of a command (start + k * step, inside its period)."""
    try:
        start, end = float(command.startTime), float(command.endTime)
        step = float(command.stepSize) * STEP_SECONDS[int(command.stepUnit)]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if step <= 0:
        return None
    return all(start - 1.0 <= moment <= end + 1.0 and abs(((moment - start) / step) - round((moment - start) / step)) < 1e-6
               for moment in times)


def rows_by_time(command):
    """Study time -> keys of the contingency objects in the rows of its sub-result; local only."""
    found = {}
    _, subs = sub_results(command)
    for sub in subs:
        try:
            moment = float(sub.GetAttribute("cnttime"))
            sub.Load()
            ids = set()
            for row in range(min(int(sub.GetNumberOfRows()), SAMPLE_ROWS)):
                code, obj = status(sub.GetObjectValue(row))
                if code == CODE_OK and obj is not None:
                    ids.add(identity(obj))
            found[moment] = ids
        except Exception:
            continue
        finally:
            try:
                sub.Release()
            except Exception:
                pass
    return found


def outage_elements(outage):
    found = []
    for line in range(200):
        try:
            element = outage.GetObject(line)
        except Exception:
            break
        if element is None:
            break
        found.append(element)
    return found


def sub_results(command):
    result = getattr(command, "p_rescnt", None)
    if result is None:
        return None, []
    return result, of_class(result, "ElmRes")


def sub_result_times(subs):
    found = []
    for sub in subs:
        try:
            found.append(float(sub.GetAttribute("cnttime")))
        except Exception:
            return None
    return sorted(found)


def status(returned):
    if isinstance(returned, (list, tuple)) and returned and isinstance(returned[0], int):
        return returned[0], returned[1] if len(returned) > 1 else None
    return None, None


def inspect(sub, numbers):
    """Structure of one sub-result; every value stays inside this function."""
    found = {"rows": 0, "row_objects": [], "columns_equipment": False, "sparse": False, "max_cntcy": None,
             "max_cntcy_rows": None}
    try:
        sub.Load()
    except Exception:
        return found
    try:
        rows, columns = int(sub.GetNumberOfRows()), int(sub.GetNumberOfColumns())
        found["rows"] = rows
        maxcntcy_columns = []
        for column in range(min(columns, SAMPLE_COLUMNS)):
            found["columns_equipment"] |= class_of(sub.GetObject(column)) in EQUIPMENT_CLASSES
            if str(sub.GetVariable(column)) == "c:maxCntcy":
                maxcntcy_columns.append(column)
        refers, checked, values = True, False, []
        for row in range(min(rows, SAMPLE_ROWS)):
            try:
                code, obj = status(sub.GetObjectValue(row))
            except Exception:
                code, obj = None, None
            found["row_objects"].append(obj if code == CODE_OK else None)
            for column in range(min(columns, SAMPLE_COLUMNS)):
                code, value = status(sub.GetValue(row, column))
                found["sparse"] |= code == CODE_SPARSE
                if column in maxcntcy_columns and code == CODE_OK and value is not None:
                    checked = True
                    refers &= int(round(value)) in numbers
                    values.append(int(round(value)))
        found["max_cntcy"] = (refers if checked else None)
        found["max_cntcy_rows"] = all(0 <= value <= rows for value in values) if values else None
    finally:
        try:
            sub.Release()
        except Exception:
            pass
    return found


def fingerprint(command):
    """A local hash of every written value of every sub-result; never printed."""
    digest = hashlib.sha256()
    _, subs = sub_results(command)
    for sub in sorted(subs, key=lambda item: str(getattr(item, "loc_name", ""))):
        try:
            sub.Load()
            rows, columns = int(sub.GetNumberOfRows()), int(sub.GetNumberOfColumns())
            for row in range(min(rows, SAMPLE_ROWS)):
                for column in range(min(columns, SAMPLE_COLUMNS)):
                    code, value = status(sub.GetValue(row, column))
                    digest.update("{}:{}:{}:{:.6g};".format(row, column, code, value if isinstance(value, float) else 0.0)
                                  .encode("ascii"))
        except Exception:
            digest.update(b"unreadable")
        finally:
            try:
                sub.Release()
            except Exception:
                pass
    return digest.hexdigest()


def execute(command):
    try:
        return command.Execute() == 0
    except Exception:
        return False


# --- tests -----------------------------------------------------------------------
def test_run(ctx, out):
    if not confirm("T1 calculates the contingency analysis of the active study case once, as configured "
                   "(time sweep included). Its result object is overwritten. Continue?"):
        out.add("T1 Confirmed", "NOT_CONFIRMED")
        return None
    command, study_case = ctx["command"], ctx["study_case"]
    before, settings = study_time(study_case)
    restorer = Restorer(out)
    try:
        out.add("T1 Execute", "SUCCESS" if execute(command) else "ERROR")
        after, _ = study_time(study_case)
        out.add("T1 Study time unchanged", flag(after == before))
        if after != before:
            for item, (date, clock) in zip(settings, before):
                restorer.changes += [(item, "cDate", date), (item, "cTime", clock)]
        result, subs = sub_results(command)
        out.add("T1 Sub-results created", flag(subs))
        if not subs:
            return False
        times = sub_result_times(subs)
        ctx["times"] = times
        inclusive, exclusive = time_steps(command)
        vector = vector_times(command)
        by_vector = same_times(times, vector)
        by_grid = same_times(times, inclusive) or same_times(times, exclusive)
        if times is None:
            out.add("T1 Study times match the time-sweep definition", "NOT_VERIFIED")
        else:
            out.add("T1 Study times match the time-sweep definition", flag(by_vector or by_grid))
            out.add("T1 Study times match the studyTime vector", "NOT_VERIFIED" if vector is None else flag(by_vector))
            out.add("T1 Study times match startTime/endTime/step", "NOT_VERIFIED" if inclusive is None else flag(by_grid))
            if by_grid:
                out.add("T1 End time included", flag(same_times(times, inclusive)))
        if ctx["statsim"] is None:
            out.add("T1 Time sweep equals the QDS time steps", "NOT_APPLICABLE")
        else:
            qds_inclusive, qds_exclusive = time_steps(ctx["statsim"])
            out.add("T1 Time sweep equals the QDS time steps",
                    "NOT_VERIFIED" if times is None or qds_inclusive is None
                    else flag(same_times(times, qds_inclusive) or same_times(times, qds_exclusive)))
            grid = on_grid(times or [], ctx["statsim"]) if times else None
            out.add("T1 Study times lie on the QDS time grid", "NOT_VERIFIED" if grid is None else flag(grid))
        numbers = {int(getattr(outage, "number", -1)) for outage in ctx["outages"]}
        found = inspect(subs[0], numbers)
        row_classes = [class_of(obj) for obj in found["row_objects"] if obj is not None]
        rows_are_contingencies = bool(row_classes) and all(name == "ComOutage" for name in row_classes)
        out.add("T1 Rows are contingencies", flag(rows_are_contingencies))
        out.add("T1 Columns are equipment", flag(found["columns_equipment"]))
        out.add("T1 Sparse values present", flag(found["sparse"]))
        out.add("T1 c:maxCntcy holds contingency numbers",
                "NOT_VERIFIED" if found["max_cntcy"] is None else flag(found["max_cntcy"]))
        out.add("T1 c:maxCntcy holds row numbers",
                "NOT_VERIFIED" if found["max_cntcy_rows"] is None else flag(found["max_cntcy_rows"]))
        analysed = [outage for outage in ctx["outages"] if getattr(outage, "outserv", 0) in (0, False)]
        out.add("T1 One row per analysed contingency", flag(found["rows"] == len(analysed)))
        out.add("T1 calcPeriod setting", value_token(getattr(command, "calcPeriod", None)))
        ctx["rows"], ctx["rows_are_contingencies"] = found["rows"], rows_are_contingencies
        return True
    finally:
        if restorer.changes:
            restorer.restore()


def planned_windows(ctx):
    """(start, end, component keys) of every planned outage that is not ignored; the window is [start, end)."""
    windows = []
    for outage in of_class(ctx["project"], "IntPlannedout", 1):
        try:
            if getattr(outage, "outserv", 0) not in (0, False):
                continue
            start, end = float(outage.starttime), float(outage.endtime)
        except (AttributeError, TypeError, ValueError):
            continue
        windows.append((start, end, {identity(item) for item in (getattr(outage, "components", None) or [])}))
    return windows


def active_planned_outages(ctx):
    """(study time, window) for every planned outage that is active at a study time; None if unknown.

    The study times are those of the calculated sub-results (T1), else the studyTime vector.
    """
    times = ctx.get("times") or vector_times(ctx["command"])
    if not times:
        return None
    return [(moment, window) for window in planned_windows(ctx) for moment in times
            if window[0] <= moment < window[1]]


def planned_outage_in_period(ctx):
    active = active_planned_outages(ctx)
    return None if active is None else bool(active)


def contingency_elements(ctx):
    """Contingency key -> keys of the equipment it interrupts."""
    return {identity(outage): {identity(element) for element in outage_elements(outage)} for outage in ctx["outages"]}


def test_planned_outages(ctx, out):
    inside = planned_outage_in_period(ctx)
    out.add("T2 Planned outage inside the sweep period", "NOT_VERIFIED" if inside is None else flag(inside))
    if not confirm("T2 sets 'Planned outages' (isPlannedOutages) of the contingency analysis to 0 and to 1, "
                   "calculates both and restores the original value. Continue?"):
        out.add("T2 Confirmed", "NOT_CONFIRMED")
        return None
    command = ctx["command"]
    restorer = Restorer(out)
    ctx["written"] = True
    try:
        restorer.write(command, "isPlannedOutages", 0)
        out.add("T2 Execute without planned outages", "SUCCESS" if execute(command) else "ERROR")
        without = fingerprint(command)
        rows_without = rows_by_time(command)
        restorer.write(command, "isPlannedOutages", 1)
        out.add("T2 Execute with planned outages", "SUCCESS" if execute(command) else "ERROR")
        differ = fingerprint(command) != without
        out.add("T2 Results differ with planned outages", flag(differ))
        rows_with = rows_by_time(command)
        analysed = sum(1 for outage in ctx["outages"] if getattr(outage, "outserv", 0) in (0, False))
        out.add("T2 One row per analysed contingency without planned outages",
                flag(rows_without and all(len(ids) == analysed for ids in rows_without.values())))
        windows = planned_windows(ctx)
        out.add("T2 Planned outage active at every study time",
                flag(rows_without and all(any(start <= moment < end for start, end, _ in windows)
                                          for moment in rows_without)))
        # Which contingencies disappear, whether they switch equipment that a planned outage already takes
        # out of service (-> NOT_APPLICABLE later), and whether only at study times inside its window.
        elements = contingency_elements(ctx)
        missing, explained, only_inside = False, True, True
        for moment, before in rows_without.items():
            for key in before - rows_with.get(moment, set()):
                missing = True
                switched = [(start, end) for start, end, components in windows if elements.get(key, set()) & components]
                explained &= bool(switched)
                only_inside &= any(start <= moment < end for start, end in switched)
        out.add("T2 Contingencies missing with planned outages", flag(missing))
        out.add("T2 Missing contingency switches a planned-outage element", flag(explained) if missing else "NOT_APPLICABLE")
        out.add("T2 Contingencies missing only inside the planned-outage window",
                flag(only_inside) if missing else "NOT_APPLICABLE")
        # Applied when the results change while a planned outage lies in the period.
        return differ if inside else None
    finally:
        restorer.restore()


def test_not_analysed(ctx, out):
    candidates = [outage for outage in ctx["outages"] if getattr(outage, "outserv", 0) in (0, False)]
    if not candidates:
        out.add("T3 Not analysed excludes the contingency", "NOT_APPLICABLE")
        return None
    if not confirm("T3 sets one contingency of the analysis to 'Not analysed' (outserv = 1), calculates and "
                   "restores it. Continue?"):
        out.add("T3 Confirmed", "NOT_CONFIRMED")
        return None
    command, target = ctx["command"], candidates[0]
    restorer = Restorer(out)
    ctx["written"] = True
    try:
        restorer.write(target, "outserv", 1)
        out.add("T3 Execute", "SUCCESS" if execute(command) else "ERROR")
        _, subs = sub_results(command)
        if not subs:
            out.add("T3 Not analysed excludes the contingency", "NOT_VERIFIED")
            return None
        found = inspect(subs[0], set())
        if ctx.get("rows_are_contingencies"):
            excluded = all(identity(obj) != identity(target) for obj in found["row_objects"] if obj is not None)
        elif "rows" in ctx:
            excluded = found["rows"] == ctx["rows"] - 1
        else:
            out.add("T3 Not analysed excludes the contingency", "NOT_VERIFIED")
            return None
        out.add("T3 Not analysed excludes the contingency", flag(excluded))
        return excluded
    finally:
        restorer.restore()


def test_storage(ctx, out):
    if not confirm("T4 creates a test object (IntDplmap) in the active study case, writes and reads one key/value "
                   "pair and deletes the object again. Continue?"):
        out.add("T4 Confirmed", "NOT_CONFIRMED")
        return None
    study_case = ctx["study_case"]
    name = "GridLens_TEST_{}".format(time.strftime("%y%m%d-%H%M%S"))
    created = None
    try:
        created = study_case.CreateObject("IntDplmap", name)
        out.add("T4 IntDplmap created", flag(class_of(created) == "IntDplmap"))
        if class_of(created) != "IntDplmap":
            return False
        created.Insert(TEST_KEY, TEST_VALUE)
        returned = created.GetValue(TEST_KEY)
        value = returned[0] if isinstance(returned, (list, tuple)) else returned
        same = value == TEST_VALUE
        out.add("T4 Key/value read back unchanged", flag(same))
        return same
    finally:
        if created is not None:
            try:
                created.Delete()
            except Exception:
                pass
            out.add("T4 Test object deleted", flag(not any(getattr(item, "loc_name", "") == name
                                                           for item in of_class(study_case, "IntDplmap"))))


def qds_grid(statsim):
    """(start, end, step) of the QDS period, or None."""
    try:
        start, end = float(statsim.startTime), float(statsim.endTime)
        step = float(statsim.stepSize) * STEP_SECONDS[int(statsim.stepUnit)]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return (start, end, step) if step > 0 and end > start else None


def window_times(window, grid):
    """QDS steps around a window [start, end): the step before, the first two inside, the last inside and the
    first at or after the end, inside the QDS period; None if no QDS step lies in the window."""
    begin, finish = window
    start, end, step = grid
    first = start + max(0, math.ceil((begin - start) / step - 1e-9)) * step
    last = start + (math.ceil((finish - start) / step - 1e-9) - 1) * step
    if first >= finish or first > end or last < first:
        return None
    chosen = {first - step, first, first + step, last, last + step}
    return sorted(moment for moment in chosen if start - 1.0 <= moment <= end + 1.0)


def window_check(rows, key, window):
    """Per study time: the contingency missing inside [start, end), present outside, present at the end."""
    begin, finish = window
    inside = [key not in ids for moment, ids in rows.items() if begin <= moment < finish]
    outside = [key in ids for moment, ids in rows.items() if not begin <= moment < finish]
    at_end = [key in ids for moment, ids in rows.items() if abs(moment - finish) <= 1.0]

    def token(checks):
        return flag(all(checks)) if checks else "NOT_APPLICABLE"
    return token(inside), token(outside), token(at_end)


def matching_window(ctx, grid):
    """(window, contingency key) of a planned outage inside the QDS period with a contingency that switches
    one of its components, or None."""
    elements = contingency_elements(ctx)
    for start, end, components in planned_windows(ctx):
        if window_times((start, end), grid) is None:
            continue
        for key, switched in sorted(elements.items()):
            if switched & components:
                return (start, end), key
    return None


def test_study_times(ctx, out):
    grid = qds_grid(ctx["statsim"]) if ctx["statsim"] is not None else None
    found = matching_window(ctx, grid) if grid else None
    out.add("T6 Planned outage with a matching contingency", flag(found))
    if not found:
        return None
    if not confirm("T6 temporarily sets the study times of the contingency analysis to a few QDS steps around "
                   "one planned outage (first the studyTime vector, if needed startTime/endTime/step), with "
                   "planned outages on, calculates and restores every value. Continue?"):
        out.add("T6 Confirmed", "NOT_CONFIRMED")
        return None
    window, key = found
    command, targets = ctx["command"], window_times(window, grid)
    ctx["written"] = True
    rows = None
    restorer = Restorer(out)
    try:
        restorer.write(command, "isPlannedOutages", 1)
        restorer.write(command, "studyTime", list(targets), same=lambda written, wanted: same_times(
            [float(value) for value in written], wanted))
        if isinstance(getattr(command, "bIgnoreTime", None), (list, tuple)):
            restorer.write(command, "bIgnoreTime", [0.0] * len(targets),
                           same=lambda written, wanted: [float(value) for value in written] == wanted)
        out.add("T6 Study times written", "TRUE")
        out.add("T6 Execute with written studyTime", "SUCCESS" if execute(command) else "ERROR")
        follows = same_times(sub_result_times(sub_results(command)[1]), targets)
        out.add("T6 Study times follow the studyTime vector", flag(follows))
        if follows:
            rows = rows_by_time(command)
    finally:
        restorer.restore()
    if rows is None:
        first, last = targets[0], targets[-1]
        if (last - first) / grid[2] + 1 > MAX_T6_TIMES:
            last = min(first + 3 * grid[2], targets[-1])
        restorer = Restorer(out)
        try:
            restorer.write(command, "isPlannedOutages", 1)
            for attribute, value in (("startTime", int(first)), ("endTime", int(last)),
                                     ("stepSize", ctx["statsim"].stepSize), ("stepUnit", ctx["statsim"].stepUnit)):
                restorer.write(command, attribute, value)
            out.add("T6 Execute with written startTime/endTime/step", "SUCCESS" if execute(command) else "ERROR")
            inclusive, exclusive = time_steps(command)
            times = sub_result_times(sub_results(command)[1])
            follows = same_times(times, inclusive) or same_times(times, exclusive)
            out.add("T6 Study times follow startTime/endTime/step", flag(follows))
            if follows:
                rows = rows_by_time(command)
        finally:
            restorer.restore()
    if rows is None:
        return False
    inside, outside, at_end = window_check(rows, key, window)
    out.add("T6 Missing inside the planned-outage window", inside)
    out.add("T6 Present outside the planned-outage window", outside)
    out.add("T6 Present at the window end", at_end)
    if "NOT_APPLICABLE" in (inside, outside):
        return None
    return inside == "TRUE" and outside == "TRUE"


TESTS = (("T1", test_run), ("T2", test_planned_outages), ("T3", test_not_analysed), ("T4", test_storage),
         ("T6", test_study_times))


def run(app, printer=None):
    out = Output(printer or app.PrintPlain)
    out.add("Test run", "STARTED")
    reason = preconditions(app)
    if reason:
        out.text(reason)
        return out
    study_case = app.GetActiveStudyCase()
    command = of_class(study_case, "ComSimoutage")[0]
    statsim = of_class(study_case, "ComStatsim")
    ctx = {"app": app, "project": app.GetActiveProject(), "study_case": study_case, "command": command,
           "statsim": statsim[0] if statsim else None, "outages": of_class(command, "ComOutage"), "written": False}
    for key, test in TESTS:
        if key not in RUN:
            out.add(key + " Result", "NOT_RUN")
            continue
        try:
            outcome = test(ctx, out)
        except Exception:
            # Only a fixed token: the error text may contain names or paths.
            out.add(key + " Error", "ERROR_EXCEPTION")
            outcome = False
        out.add(key + " Result", {True: "PASS", False: "FAIL", None: "NOT_VERIFIED"}[outcome])
    out.add("T5 Result", "NOT_DOCUMENTED")
    if ctx["written"]:
        out.add("Final run with the original settings", "SUCCESS" if execute(command) else "ERROR")
    return out


def main():
    import powerfactory

    run(powerfactory.GetApplication())


if __name__ == "__main__":
    main()
