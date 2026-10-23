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
    the results; tells whether the switch applies the planned outages.
T3  Contingency filter: set one contingency to "Not analysed" (outserv = 1),
    calculate, check that it is missing from the results, restore.
T4  Native storage: create an IntDplmap in the study case of the copy, insert
    a key/value pair, read it back, delete the object again.
T5  Writing own values into an ElmRes: not run. The Python reference
    documents Write() for the current calculation results of monitored
    variables, not for values chosen by a script.

Privacy: the output consists of fixed labels and fixed tokens only (PASS,
TRUE, ...). No project, study case, object or user name, no value, study time,
count or error text is printed. Two things are read locally for the safety and
the checks and never printed: the project name (compared with
PROJECT_COPY_NAME) and result values / study times (compared with each other).
"""

import hashlib
import time

ENABLED = False
# The exact name of the project copy, e.g. '<project> - GridLens TEST copy'.
PROJECT_COPY_NAME = ""
COPY_MARKER = "copy"
RUN = ("T1", "T2", "T3", "T4")
# Rows and columns of a sub-result inspected per check.
SAMPLE_ROWS, SAMPLE_COLUMNS = 500, 2000
# ComSimoutage / ComStatsim stepUnit: 0 seconds, 1 minutes, 2 hours, 3 days (4 months, 5 years not converted).
STEP_SECONDS = {0: 1, 1: 60, 2: 3600, 3: 86400}
EQUIPMENT_CLASSES = frozenset(("ElmLne", "ElmTr2", "ElmTr3", "ElmTr4", "ElmTerm", "ElmSym", "ElmGenstat", "ElmPvsys",
                               "ElmLod", "ElmCoup", "ElmScap", "ElmSind", "ElmShnt", "ElmVsc", "ElmRec", "ElmBranch"))
CODE_OK, CODE_SPARSE = 0, 3
TEST_KEY, TEST_VALUE = "gridlens.test", "value-1"
WRITTEN_ATTRIBUTES = ("isPlannedOutages", "outserv", "cDate", "cTime")

TOKENS = frozenset(("PASS", "FAIL", "TRUE", "FALSE", "SUCCESS", "ERROR", "NOT_RUN", "NOT_CONFIRMED", "NOT_VERIFIED",
                    "NOT_APPLICABLE", "NOT_DOCUMENTED", "ERROR_EXCEPTION", "STARTED"))
LABELS = frozenset(
    {"Test run", "Precondition", "Final run with the original settings"}
    | {"Restored " + name for name in WRITTEN_ATTRIBUTES}
    | {"T1 " + label for label in (
        "Confirmed", "Execute", "Study time unchanged", "Sub-results created",
        "Study times match the time-sweep definition", "End time included", "Time sweep equals the QDS time steps",
        "Rows are contingencies", "Columns are equipment", "Sparse values present",
        "c:maxCntcy holds contingency numbers", "One row per analysed contingency", "Error", "Result")}
    | {"T2 " + label for label in (
        "Confirmed", "Planned outage inside the sweep period", "Execute without planned outages",
        "Execute with planned outages", "Results differ with planned outages", "Error", "Result")}
    | {"T3 " + label for label in ("Confirmed", "Execute", "Not analysed excludes the contingency", "Error", "Result")}
    | {"T4 " + label for label in ("Confirmed", "IntDplmap created", "Key/value read back unchanged",
                                   "Test object deleted", "Error", "Result")}
    | {"T5 Result"})
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

    def write(self, obj, attribute, value):
        original = getattr(obj, attribute)
        self.changes.append((obj, attribute, original))
        setattr(obj, attribute, value)
        if getattr(obj, attribute) != value:
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
    found = {"rows": 0, "row_objects": [], "columns_equipment": False, "sparse": False, "max_cntcy": None}
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
        refers, checked = True, False
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
        found["max_cntcy"] = (refers if checked else None)
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
        inclusive, exclusive = time_steps(command)
        if times is None or inclusive is None:
            out.add("T1 Study times match the time-sweep definition", "NOT_VERIFIED")
        else:
            match = times == inclusive or times == exclusive
            out.add("T1 Study times match the time-sweep definition", flag(match))
            out.add("T1 End time included", flag(times == inclusive))
        if ctx["statsim"] is None:
            out.add("T1 Time sweep equals the QDS time steps", "NOT_APPLICABLE")
        else:
            qds_inclusive, qds_exclusive = time_steps(ctx["statsim"])
            out.add("T1 Time sweep equals the QDS time steps",
                    "NOT_VERIFIED" if times is None or qds_inclusive is None else flag(times in (qds_inclusive, qds_exclusive)))
        numbers = {int(getattr(outage, "number", -1)) for outage in ctx["outages"]}
        found = inspect(subs[0], numbers)
        row_classes = [class_of(obj) for obj in found["row_objects"] if obj is not None]
        rows_are_contingencies = bool(row_classes) and all(name == "ComOutage" for name in row_classes)
        out.add("T1 Rows are contingencies", flag(rows_are_contingencies))
        out.add("T1 Columns are equipment", flag(found["columns_equipment"]))
        out.add("T1 Sparse values present", flag(found["sparse"]))
        out.add("T1 c:maxCntcy holds contingency numbers",
                "NOT_VERIFIED" if found["max_cntcy"] is None else flag(found["max_cntcy"]))
        analysed = [outage for outage in ctx["outages"] if getattr(outage, "outserv", 0) in (0, False)]
        out.add("T1 One row per analysed contingency", flag(found["rows"] == len(analysed)))
        ctx["rows"], ctx["rows_are_contingencies"] = found["rows"], rows_are_contingencies
        return True
    finally:
        if restorer.changes:
            restorer.restore()


def planned_outage_in_period(ctx):
    command = ctx["command"]
    try:
        start, end = float(command.startTime), float(command.endTime)
    except (AttributeError, TypeError, ValueError):
        return None
    for outage in of_class(ctx["project"], "IntPlannedout", 1):
        try:
            if getattr(outage, "outserv", 0) in (0, False) and float(outage.starttime) <= end and float(outage.endtime) > start:
                return True
        except (AttributeError, TypeError, ValueError):
            continue
    return False


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
        restorer.write(command, "isPlannedOutages", 1)
        out.add("T2 Execute with planned outages", "SUCCESS" if execute(command) else "ERROR")
        differ = fingerprint(command) != without
        out.add("T2 Results differ with planned outages", flag(differ))
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
            excluded = all(obj is not target for obj in found["row_objects"])
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


TESTS = (("T1", test_run), ("T2", test_planned_outages), ("T3", test_not_analysed), ("T4", test_storage))


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
    import powerfactory  # noqa: F401  (only available inside PowerFactory)

    run(powerfactory.GetApplication())


if __name__ == "__main__":
    main()
