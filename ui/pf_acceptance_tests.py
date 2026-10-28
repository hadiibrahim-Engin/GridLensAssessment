"""GridLens acceptance tests for DIgSILENT PowerFactory 2026 (run as a ComPython).

These small tests answer the open PowerFactory questions of docs/ARCHITECTURE.md
(section 2.4 and 11) in the real program, so that a statement about the
correctness of GridLens results rests on PowerFactory itself and not on the
mock objects of the unit tests. They are a development tool, not part of the
delivery, and need nothing but the standard library and PowerFactory.

PRIVACY: LOCAL USE ONLY. The output names outages, equipment and values.

How to run
----------
Paste the COMPLETE file into a ComPython in the active study case (with a
configured ComStatsim that records c:loading of lines and transformers).

1. First run with WRITE = False (default): reads only. It shows the BEFORE
   state (ComStatsim options, every planned outage with window and "Ignored"
   flag, the outages each test would use) and the plan of QDS runs. Nothing is
   changed or calculated.
2. Then set WRITE = True and run again. Each test prints the BEFORE state,
   runs its QDS runs, prints the values per time step and its verdict, and
   finally the AFTER state with a check that everything was restored.

What a test run changes, all restored and read back at the end: ComStatsim
option iopt_maint and the "Ignored" flag (outserv) of the planned outages.
Like a GridLens run, every QDS run overwrites the result object the ComStatsim
writes into; with KEEP_RESULT_COPIES each run is kept as a copy
GridLensTest_<stamp>_<run> in the study case so that it can be opened after the
test. Copies are never deleted by this script.

Every run also writes a folder ~/GridLens/acceptance/<stamp>/ with report.txt
(what the output window showed), results.json and one CSV per test with the
value of every inspected time step (open it in Excel).

Tests (names as in docs/ARCHITECTURE.md, section 2.4)
-----------------------------------------------------
P1  iopt_maint = 1 applies an outage inside its window: its equipment is out of
    service there and in service in REF.
P2  outserv = 1 ("Ignored") excludes an outage while iopt_maint = 1: with every
    outage ignored the run equals REF.
P3  Two outages active in one run are applied together, and each switches back
    at the end of its own window.
P4  Two outages on the same equipment: what PowerFactory does when the first
    ends (information only, there is no expected answer yet).
P5  Window boundaries: in which time steps does the outage take effect? The
    verdict says whether the effect matches [start, end) or is shifted.
P6  Kept result objects GridLens_<stamp>_<case> of earlier GridLens runs exist
    in the study case and can be opened (read only, no calculation).
"""

import json
import math
import os
import time

# --- configuration ------------------------------------------------------------
WRITE = False                 # False: read only, show BEFORE state and plan. True: run the tests.
TESTS = ("P1", "P2", "P3", "P4", "P5", "P6")
OUTAGE_A = ""                 # planned outage for P1, P2, P5 (loc_name); "" = chosen automatically
OUTAGE_B = ""                 # second outage for P3, overlapping OUTAGE_A in time; "" = chosen automatically
KEEP_RESULT_COPIES = True     # keep every QDS run as GridLensTest_<stamp>_<run> in the study case
MARGIN_STEPS = 3              # time steps shown before and after each window
OUT_LOADING = 0.5             # % loading at or below which equipment counts as out of service
EQUAL_TOLERANCE = 0.1         # % loading; smaller differences count as equal
MAX_COMPARE_COLUMNS = 200     # network loadings compared in P2 besides the outage equipment
OUTPUT_DIR = ""               # "" = ~/GridLens/acceptance

PREFIX = "[GL-ACCEPTANCE] "
BRANCH_CLASSES = ("ElmLne", "ElmTr2", "ElmTr3")
LOADING_VARIABLES = ("c:loading", "m:loading")
COPY_PREFIX = "GridLensTest_"
KEPT_PREFIX = "GridLens_"
PASS, FAIL, INFO, SKIPPED, NOT_RECORDED = "PASS", "FAIL", "INFO", "SKIPPED", "NOT RECORDED"


# --- small helpers -----------------------------------------------------------------
class Report:
    """Every line goes to the PowerFactory output window and into report.txt."""

    def __init__(self, app):
        self.app, self.lines = app, []

    def __call__(self, text="", error=False):
        for line in str(text).split("\n"):
            self.lines.append(line)
            printer = getattr(self.app, "PrintError" if error else "PrintPlain", None) if self.app is not None else None
            if callable(printer):
                try:
                    printer(PREFIX + line)
                    continue
                except Exception:
                    pass
            print(PREFIX + line, flush=True)

    def section(self, title):
        self("")
        self("=" * 78)
        self(title)
        self("=" * 78)


def safe_attr(obj, name, default=None):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def name_of(obj):
    return str(safe_attr(obj, "loc_name", "") or "?")


def key_of(obj):
    try:
        return str(obj.GetFullName())
    except Exception:
        return name_of(obj)


def class_of(obj):
    try:
        return str(obj.GetClassName())
    except Exception:
        return ""


def number(value):
    if value is None or type(value) is bool or isinstance(value, (list, tuple)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def as_list(value):
    if value is None:
        return []
    return [item for item in value if item is not None] if isinstance(value, (list, tuple)) else [value]


def clock(epoch):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch)) if epoch is not None else "?"


def code_of(returned):
    """PowerFactory return code as a number; 0 is success."""
    if isinstance(returned, (list, tuple)):
        returned = returned[0] if returned else None
    return number(returned)


def set_attr(obj, name, value):
    try:
        setattr(obj, name, value)
    except Exception:
        obj.SetAttribute(name, value)
    if safe_attr(obj, name) != value:
        raise RuntimeError("{} was not applied or could not be read back".format(name))
    return True


def table(report, header, rows):
    widths = [max(len(str(item)) for item in column) for column in zip(header, *rows)] if rows else [len(h) for h in header]
    for line in [header, ["-" * width for width in widths]] + list(rows):
        report("  " + "  ".join(str(item).ljust(width) for item, width in zip(line, widths)).rstrip())


# --- reading the project ----------------------------------------------------------------
def find_qds(study_case):
    """The ComStatsim of the study case; never created (GetFromStudyCase would create one)."""
    found = [item for item in as_list(study_case.GetContents("*.ComStatsim")) if class_of(item) == "ComStatsim"]
    return found[0] if found else None


def find_outages(app):
    folders = []
    for key in ("outage", "outages"):
        try:
            folders.extend(as_list(app.GetProjectFolder(key)))
        except Exception:
            pass
    if not folders:
        folders = as_list(app.GetActiveProject())
    found = {}
    for folder in folders:
        for outage in as_list(folder.GetContents("*.IntPlannedout", 1)):
            found[key_of(outage)] = outage
    return sorted(found.values(), key=lambda item: name_of(item).casefold())


def outage_info(outage, period):
    start, end = number(safe_attr(outage, "starttime")), number(safe_attr(outage, "endtime"))
    components = [item for item in as_list(safe_attr(outage, "components")) if not isinstance(item, (str, int, float))]
    branches = [item for item in components if class_of(item) in BRANCH_CLASSES]
    begin, finish = period
    inside = start is not None and end is not None and end > start and (
        begin is None or finish is None or (end > begin and start < finish))
    return {"object": outage, "name": name_of(outage), "key": key_of(outage), "start": start, "end": end,
            "ignored": number(safe_attr(outage, "outserv", 0)) == 1.0, "components": components,
            "branches": branches, "in_period": inside}


def overlap(first, second):
    return first["start"] < second["end"] and second["start"] < first["end"]


def choose_outages(outages):
    """(A, B, same-equipment pair) for the tests, from the configuration or automatically."""
    usable = [item for item in outages if item["in_period"] and item["branches"]]
    named = {item["name"]: item for item in outages}
    first = named.get(OUTAGE_A) if OUTAGE_A else (usable[0] if usable else None)
    second = named.get(OUTAGE_B) if OUTAGE_B else next(
        (item for item in usable if first is not None and item is not first and overlap(item, first)
         and not set(map(key_of, item["branches"])) & set(map(key_of, first["branches"]))), None)
    shared = None
    for index, left in enumerate(usable):
        for right in usable[index + 1:]:
            if set(map(key_of, left["branches"])) & set(map(key_of, right["branches"])):
                shared = (left, right)
                break
        if shared:
            break
    return first, second, shared


# --- state that the tests change, restored and verified ------------------------------------
class State:
    """iopt_maint, the results binding and every outserv: captured once, restored in reverse, read back."""

    def __init__(self, qds, outages):
        self.qds, self.outages = qds, outages
        self.result_binding = safe_attr(qds, "results")
        self.before = self.read()

    def read(self):
        return {"ComStatsim.iopt_maint": safe_attr(self.qds, "iopt_maint"),
                "ComStatsim.results": key_of(safe_attr(self.qds, "results")) if safe_attr(self.qds, "results") else None,
                **{"outserv " + item["key"]: safe_attr(item["object"], "outserv") for item in self.outages}}

    def restore(self):
        problems = []
        for item in reversed(self.outages):
            wanted = self.before["outserv " + item["key"]]
            try:
                set_attr(item["object"], "outserv", wanted)
            except Exception as exc:
                problems.append("outserv of {}: {}".format(item["name"], exc))
        try:
            set_attr(self.qds, "iopt_maint", self.before["ComStatsim.iopt_maint"])
        except Exception as exc:
            problems.append("iopt_maint: {}".format(exc))
        try:
            set_attr(self.qds, "results", self.result_binding)
        except Exception as exc:
            problems.append("results binding: {}".format(exc))
        after = self.read()
        rows = [(name, self.before[name], after[name], "OK" if after[name] == self.before[name] else "DIFFERENT")
                for name in self.before]
        return rows, problems


# --- QDS runs and result reading -------------------------------------------------------------
class Runner:
    """QDS runs; each run's values are read right after it, because the next run overwrites the same ElmRes."""

    def __init__(self, report, study_case, qds, outages, stamp, watched):
        self.report, self.study_case, self.qds, self.outages, self.stamp = report, study_case, qds, outages, stamp
        self.watched = [item for item in watched if item is not None]  # outages whose windows the tests inspect
        self.runs = {}

    def run(self, label, active=None):
        """One QDS run: REF when `active` is None (iopt_maint 0), else iopt_maint 1 with only `active` applied."""
        if label in self.runs:
            return self.runs[label]
        if active is None:
            set_attr(self.qds, "iopt_maint", 0)
            text = "iopt_maint=0 (no planned outage)"
        else:
            keys = {item["key"] for item in active}
            for item in self.outages:
                set_attr(item["object"], "outserv", 0 if item["key"] in keys else 1)
            set_attr(self.qds, "iopt_maint", 1)
            text = "iopt_maint=1, active: {}".format(", ".join(item["name"] for item in active) or "none (all Ignored)")
        self.report("  run {:<10} {}".format(label, text))
        started = time.time()
        code = code_of(self.qds.Execute())
        elmres = safe_attr(self.qds, "results")
        result = {"label": label, "text": text, "code": code, "seconds": round(time.time() - started, 1),
                  "elmres": elmres, "copy": None}
        self.report("      ComStatsim.Execute() returned {} after {} s".format(code, result["seconds"]))
        if code == 0 and elmres is not None:
            result.update(read_results(elmres, self.watched))
            if KEEP_RESULT_COPIES:
                result["copy"] = keep_copy(self.study_case, elmres, "{}{}_{}".format(COPY_PREFIX, self.stamp, label))
                self.report("      kept as {}".format(result["copy"] or "- (PowerFactory refused the copy)"))
        self.runs[label] = result
        return result


def read_results(elmres, watched):
    """Time axis and the loadings the tests compare, read now: the outage equipment and up to
    MAX_COMPARE_COLUMNS further lines/transformers, in the steps around the watched windows."""
    try:
        loaded = elmres.Load()
    except Exception as exc:
        raise RuntimeError("Result object could not be loaded") from exc
    if loaded is not None and code_of(loaded) != 0:
        raise RuntimeError("Result object Load() failed")
    rows = int(elmres.GetNumberOfRows())
    columns = {}
    for column in range(int(elmres.GetNumberOfColumns())):
        try:
            variable, obj = str(elmres.GetVariable(column)), elmres.GetObject(column)
        except Exception:
            continue
        if variable in LOADING_VARIABLES and obj is not None and class_of(obj) in BRANCH_CLASSES:
            columns.setdefault(key_of(obj), column)
    result = {"rows": rows, "times": [cell(elmres, row, -1) for row in range(rows)], "columns": columns}
    keys = [key_of(branch) for item in watched for branch in item["branches"] if key_of(branch) in columns]
    keys = list(dict.fromkeys(keys)) + [key for key in sorted(columns) if key not in keys][:MAX_COMPARE_COLUMNS]
    result["values"] = {(key, row): cell(elmres, row, columns[key])
                        for row in inspected_rows(result, watched) for key in keys}
    return result


def cell(elmres, row, column):
    try:
        raw = elmres.GetValue(row, column)
    except Exception:
        return None
    if isinstance(raw, (list, tuple)):
        if len(raw) < 2 or number(raw[0]) != 0.0:
            return None
        raw = raw[1]
    return number(raw)


def value(run, key, row):
    """Loading of one branch in one row of a run, as read after the run; None when not recorded or not readable."""
    return run.get("values", {}).get((key, row))


def keep_copy(study_case, elmres, name):
    try:
        copies = as_list(study_case.AddCopy(elmres))
        copy = copies[0] if copies else None
        if copy is None:
            return None
        set_attr(copy, "loc_name", name)
        return name_of(copy)
    except Exception:
        return None


def is_out(loading):
    return loading is not None and abs(loading) <= OUT_LOADING


def inside(epoch, item):
    return epoch is not None and item["start"] <= epoch < item["end"]


def inspected_rows(run, items):
    """Rows within MARGIN_STEPS of any window of `items`."""
    times = run["times"]
    wanted = set()
    for item in items:
        hits = [row for row, epoch in enumerate(times) if inside(epoch, item)]
        first = next((row for row, epoch in enumerate(times) if epoch is not None and epoch >= item["start"]), len(times))
        last = max(hits) if hits else first - 1
        wanted.update(range(max(0, min(first, last + 1) - MARGIN_STEPS), min(len(times), max(first, last) + 1 + MARGIN_STEPS)))
    return sorted(wanted)


def failed_run(*runs):
    """A verdict when a run failed or recorded nothing to compare; None when all runs are usable."""
    for run in runs:
        if run["code"] != 0:
            return FAIL, "ComStatsim.Execute() of run {} returned {}".format(run["label"], run["code"])
        if not run.get("rows"):
            return NOT_RECORDED, "run {} wrote no rows into its result object".format(run["label"])
        times = run.get("times", [])
        if any(moment is None for moment in times) or any(
                right <= left for left, right in zip(times, times[1:])):
            return FAIL, "run {} has an invalid time axis".format(run["label"])
        if times != runs[0].get("times"):
            return FAIL, "run {} has a different time axis from the reference".format(run["label"])
        if not run.get("values") or any(item is None for item in run["values"].values()):
            return NOT_RECORDED, "run {} has missing or unreadable loading values".format(run["label"])
    return None


def missing_columns(run, items):
    keys = [key_of(branch) for item in items for branch in item["branches"]]
    return [key.rsplit("\\", 1)[-1] for key in keys if key not in run["columns"]]


def write_csv(folder, name, header, rows):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8-sig") as handle:
        for line in [header] + rows:
            handle.write(";".join("" if item is None else (("%.4f" % item) if isinstance(item, float) else str(item))
                                  for item in line) + "\n")
    return path


def fmt(loading):
    return "-" if loading is None else "{:.2f}".format(loading)


# --- the tests ----------------------------------------------------------------------------
def test_p1(ctx):
    a = ctx["A"]
    if a is None:
        return SKIPPED, "no planned outage with a line or transformer inside the simulated period", []
    ref, run_a = ctx["runner"].run("REF"), ctx["runner"].run("A", [a])
    broken = failed_run(ref, run_a)
    if broken:
        return broken + ([],)
    missing = missing_columns(ref, [a])
    if missing:
        return NOT_RECORDED, "c:loading not recorded for: {} (add it to the result variables)".format(", ".join(missing)), []
    rows = inspected_rows(ref, [a])
    lines, applied, leaked = [], 0, 0
    for row in rows:
        epoch = ref["times"][row]
        for branch in a["branches"]:
            key = key_of(branch)
            in_window, r, o = inside(epoch, a), value(ref, key, row), value(run_a, key, row)
            applied += in_window and is_out(o) and not is_out(r)
            leaked += (not in_window) and is_out(o) and not is_out(r)
            lines.append([clock(epoch), epoch, name_of(branch), "yes" if in_window else "no", r, o])
    header = ["time", "epoch", "equipment", "in window", "REF loading %", "A loading %"]
    ctx["show"](header, lines)
    ctx["csv"]("P1_iopt_maint.csv", header, lines)
    if applied:
        return PASS, "{} applied: its equipment is out of service in {} inspected step(s) of its window".format(
            a["name"], applied) + ("; out of service also in {} step(s) outside the window (see P5)".format(leaked) if leaked else ""), lines
    return FAIL, "{} was not applied: its equipment never went out of service inside the window".format(a["name"]), lines


def test_p2(ctx):
    a = ctx["A"]
    if a is None:
        return SKIPPED, "no planned outage with a line or transformer inside the simulated period", []
    ref, ignored = ctx["runner"].run("REF"), ctx["runner"].run("IGNORED", [])
    broken = failed_run(ref, ignored)
    if broken:
        return broken + ([],)
    rows = inspected_rows(ref, [a])
    keys = [key_of(branch) for branch in a["branches"] if key_of(branch) in ref["columns"]]
    keys += sorted({key for key, _ in ref["values"]} - set(keys))  # every loading read after the run
    worst, lines = (0.0, None, None), []
    for row in rows:
        for key in keys:
            r, i = value(ref, key, row), value(ignored, key, row)
            difference = abs(r - i) if r is not None and i is not None else (0.0 if r is None and i is None else float("inf"))
            if difference > worst[0]:
                worst = (difference, row, key)
            if key in keys[:len(a["branches"])]:
                lines.append([clock(ref["times"][row]), ref["times"][row], key.rsplit("\\", 1)[-1], r, i])
    header = ["time", "epoch", "equipment", "REF loading %", "all Ignored loading %"]
    ctx["show"](header, lines)
    ctx["csv"]("P2_outserv.csv", header, lines)
    compared = "{} loadings x {} steps".format(len(keys), len(rows))
    if worst[0] <= EQUAL_TOLERANCE:
        return PASS, "with every outage Ignored the run equals REF ({}; largest difference {:.4f} %)".format(
            compared, worst[0]), lines
    return FAIL, "an Ignored outage still acts: {} differs by {} % at {} ({})".format(
        worst[2].rsplit("\\", 1)[-1], "missing value" if worst[0] == float("inf") else "{:.2f}".format(worst[0]),
        clock(ref["times"][worst[1]]), compared), lines


def state_lines(runs, items):
    """Per row and equipment: in window per outage, loading per run."""
    ref = runs[0]
    lines = []
    for row in inspected_rows(ref, items):
        epoch = ref["times"][row]
        for item in items:
            for branch in item["branches"]:
                key = key_of(branch)
                lines.append([clock(epoch), epoch, "{} ({})".format(name_of(branch), item["name"])]
                             + ["yes" if inside(epoch, other) else "no" for other in items]
                             + [value(run, key, row) for run in runs])
    return lines


def test_p3(ctx):
    a, b = ctx["A"], ctx["B"]
    if a is None or b is None:
        return SKIPPED, "needs two planned outages on different lines/transformers whose windows overlap; set OUTAGE_A and OUTAGE_B", []
    runner = ctx["runner"]
    ref, run_a, run_b, both = runner.run("REF"), runner.run("A", [a]), runner.run("B", [b]), runner.run("A_B", [a, b])
    broken = failed_run(ref, run_a, run_b, both)
    if broken:
        return broken + ([],)
    missing = missing_columns(ref, [a, b])
    if missing:
        return NOT_RECORDED, "c:loading not recorded for: {}".format(", ".join(missing)), []
    lines = state_lines([ref, run_a, run_b, both], [a, b])
    header = ["time", "epoch", "equipment (outage)", "in A", "in B", "REF %", "A only %", "B only %", "A+B %"]
    ctx["show"](header, lines)
    ctx["csv"]("P3_two_outages.csv", header, lines)
    wrong = []
    for line in lines:
        owner = a if line[2].endswith("({})".format(a["name"])) else b
        in_own = line[3] == "yes" if owner is a else line[4] == "yes"
        if in_own and not is_out(line[8]):
            wrong.append("{} in service at {} although its outage is active".format(line[2], line[0]))
        if not in_own and is_out(line[8]) and not is_out(line[5]):
            wrong.append("{} out of service at {} outside its own window".format(line[2], line[0]))
    if not wrong:
        return PASS, "{} and {} act together where they overlap and each switches back at its own end".format(
            a["name"], b["name"]), lines
    return FAIL, "; ".join(wrong[:4]) + (" (+{} more)".format(len(wrong) - 4) if len(wrong) > 4 else ""), lines


def test_p4(ctx):
    pair = ctx["shared"]
    if pair is None:
        return SKIPPED, "no two planned outages in the period share a line or transformer", []
    a, b = pair
    runner = ctx["runner"]
    ref, run_a, run_b, both = runner.run("REF"), runner.run("S1", [a]), runner.run("S2", [b]), runner.run("S1_S2", [a, b])
    broken = failed_run(ref, run_a, run_b, both)
    if broken:
        return broken + ([],)
    shared = set(map(key_of, a["branches"])) & set(map(key_of, b["branches"]))
    lines = [line for line in state_lines([ref, run_a, run_b, both], [a, b])
             if any(line[2] == "{} ({})".format(name_of(branch), a["name"]) for branch in a["branches"]
                    if key_of(branch) in shared)]
    header = ["time", "epoch", "equipment (outage)", "in S1", "in S2", "REF %", "S1 only %", "S2 only %", "S1+S2 %"]
    ctx["show"](header, lines)
    ctx["csv"]("P4_same_equipment.csv", header, lines)
    after_first = [line for line in lines if line[3] != line[4]]  # exactly one of the two is active
    out = sum(1 for line in after_first if is_out(line[8]))
    return INFO, "{} and {} share equipment; where only one of them is active the equipment is out of service in {} of {} " \
                 "step(s) of the joint run - see the table".format(a["name"], b["name"], out, len(after_first)), lines


def test_p5(ctx):
    a = ctx["A"]
    if a is None:
        return SKIPPED, "no planned outage with a line or transformer inside the simulated period", []
    ref, run_a = ctx["runner"].run("REF"), ctx["runner"].run("A", [a])
    broken = failed_run(ref, run_a)
    if broken:
        return broken + ([],)
    key = next((key_of(branch) for branch in a["branches"] if key_of(branch) in ref["columns"]), None)
    if key is None:
        return NOT_RECORDED, "c:loading of the equipment of {} is not recorded".format(a["name"]), []
    rows = inspected_rows(ref, [a])
    times = ref["times"]
    window_rows = [row for row in rows if inside(times[row], a)]
    effect_rows = [row for row in rows if is_out(value(run_a, key, row)) and not is_out(value(ref, key, row))]
    lines = [[clock(times[row]), times[row], "yes" if row in window_rows else "no", value(ref, key, row),
              value(run_a, key, row), "yes" if row in effect_rows else "no"] for row in rows]
    header = ["time", "epoch", "in [start, end)", "REF %", "A %", "out of service"]
    ctx["report"]("  window of {}: {} to {}  (equipment {})".format(a["name"], clock(a["start"]), clock(a["end"]),
                                                                     key.rsplit("\\", 1)[-1]))
    ctx["show"](header, lines)
    ctx["csv"]("P5_window_boundary.csv", header, lines)
    if not window_rows:
        return INFO, "no time step lies in [start, end); the outage falls between two steps ({} affected step(s))".format(
            len(effect_rows)), lines
    if not effect_rows:
        return FAIL, "the outage had no effect in any inspected step", lines
    if effect_rows == window_rows:
        return PASS, "the effect covers exactly the steps in [start, end) ({} steps)".format(len(window_rows)), lines
    first_shift = rows.index(effect_rows[0]) - rows.index(window_rows[0])
    last_shift = rows.index(effect_rows[-1]) - rows.index(window_rows[-1])
    return FAIL, "the effect is shifted: first affected step {:+d}, last affected step {:+d} steps against [start, end) " \
                 "(GridLens assesses such steps as spill-over)".format(first_shift, last_shift), lines


def test_p6(ctx):
    kept = [item for item in as_list(ctx["study_case"].GetContents("*.ElmRes"))
            if name_of(item).startswith(KEPT_PREFIX) and not name_of(item).startswith(COPY_PREFIX)]
    if not kept:
        return SKIPPED, "no result object {}<stamp>_<case> in the study case; run GridLens once first".format(KEPT_PREFIX), []
    lines, broken = [], []
    for item in sorted(kept, key=name_of):
        try:
            item.Load()
            rows, columns = int(item.GetNumberOfRows()), int(item.GetNumberOfColumns())
        except Exception as exc:
            rows, columns = None, None
            broken.append("{}: {}".format(name_of(item), exc))
        lines.append([name_of(item), rows, columns])
        if rows is not None and (rows <= 0 or columns <= 0):
            broken.append("{} is empty".format(name_of(item)))
    ctx["show"](["result object", "rows", "columns"], lines)
    ctx["csv"]("P6_kept_results.csv", ["result object", "rows", "columns"], lines)
    if broken:
        return FAIL, "; ".join(broken[:4]), lines
    return PASS, "{} kept result object(s) open with rows and columns".format(len(kept)), lines


TEST_FUNCTIONS = {"P1": test_p1, "P2": test_p2, "P3": test_p3, "P4": test_p4, "P5": test_p5, "P6": test_p6}
TEST_TITLES = {"P1": "iopt_maint applies an outage in its window", "P2": "outserv=1 (Ignored) excludes an outage",
               "P3": "two outages together, each switches back at its own end",
               "P4": "two outages on the same equipment (information)", "P5": "effect at the window boundaries",
               "P6": "kept result objects of GridLens runs"}
WRITING_TESTS = ("P1", "P2", "P3", "P4", "P5")


# --- the run --------------------------------------------------------------------------------
def show_before(report, qds, period, outages, chosen):
    a, b, shared = chosen
    report.section("BEFORE")
    report("ComStatsim: {}  iopt_maint={}  period {} to {}  results={}".format(
        name_of(qds), safe_attr(qds, "iopt_maint"), clock(period[0]), clock(period[1]),
        name_of(safe_attr(qds, "results")) if safe_attr(qds, "results") else "-"))
    report("{} planned outage(s):".format(len(outages)))
    table(report, ["planned outage", "start", "end", "Ignored", "in period", "lines/transformers"],
          [(item["name"], clock(item["start"]), clock(item["end"]), "yes" if item["ignored"] else "no",
            "yes" if item["in_period"] else "no", ", ".join(name_of(branch) for branch in item["branches"]) or "-")
           for item in outages])
    report("")
    report("Outage A (P1, P2, P5): {}".format(a["name"] if a else "- none usable"))
    report("Outage B (P3):         {}".format(b["name"] if b else "- none overlapping A on other equipment"))
    report("Same-equipment pair (P4): {}".format(" + ".join(item["name"] for item in shared) if shared else "- none"))


def plan_text(selected, chosen):
    a, b, shared = chosen
    runs = []
    for test in selected:
        if test in ("P1", "P5") and a:
            runs += ["REF", "A"]
        elif test == "P2" and a:
            runs += ["REF", "IGNORED"]
        elif test == "P3" and a and b:
            runs += ["REF", "A", "B", "A_B"]
        elif test == "P4" and shared:
            runs += ["REF", "S1", "S2", "S1_S2"]
    unique = list(dict.fromkeys(runs))
    return unique


def main():
    try:
        import powerfactory
    except ImportError:
        print(PREFIX + "Run this file as a ComPython inside PowerFactory 2026.", flush=True)
        return None
    app = powerfactory.GetApplication()
    report = Report(app)
    stamp = time.strftime("%y%m%d-%H%M%S") + "-{:09d}".format(time.time_ns() % 1_000_000_000)
    folder = os.path.join(os.path.expanduser(OUTPUT_DIR or os.path.join("~", "GridLens", "acceptance")), stamp)
    os.makedirs(folder, exist_ok=True)
    results = {"stamp": stamp, "write": WRITE, "tests": {}}
    report("GridLens acceptance tests - {} - {}".format(stamp, "WRITE: QDS runs" if WRITE else "READ ONLY: plan and BEFORE state"))
    report("PRIVACY: LOCAL USE ONLY. Output folder: {}".format(folder))
    study_case = app.GetActiveStudyCase()
    qds = find_qds(study_case) if study_case is not None else None
    if qds is None:
        report("No active study case with a ComStatsim. Nothing was changed.", error=True)
        return False
    period = (number(safe_attr(qds, "startTime")), number(safe_attr(qds, "endTime")))
    outages = [outage_info(item, period) for item in find_outages(app)]
    chosen = choose_outages(outages)
    selected = [test for test in TESTS if test in TEST_FUNCTIONS]
    show_before(report, qds, period, outages, chosen)
    runs = plan_text(selected, chosen)
    report("")
    report("Selected tests: {}".format(", ".join(selected)))
    report("QDS runs needed: {}".format(", ".join(runs) if runs else "none"))
    results["before"] = {"iopt_maint": safe_attr(qds, "iopt_maint"), "period": [clock(period[0]), clock(period[1])],
                         "outages": [dict({key: item[key] for key in ("name", "start", "end", "ignored", "in_period")},
                                          branches=[name_of(branch) for branch in item["branches"]]) for item in outages]}
    if not WRITE:
        selected = [test for test in selected if test not in WRITING_TESTS]
        report("WRITE = False: only the read-only tests run ({}). Set WRITE = True for the QDS tests.".format(
            ", ".join(selected) or "none"))
    state = State(qds, outages) if WRITE and runs else None
    def show(header, rows):
        """A test's rows in the output window; the epoch column (index 1) only goes into the CSV."""
        if not rows:
            report("  (no rows)")
            return
        table(report, [item for index, item in enumerate(header) if index != 1],
              [[fmt(item) if isinstance(item, float) else item for index, item in enumerate(row) if index != 1]
               for row in rows])

    context = {"A": chosen[0], "B": chosen[1], "shared": chosen[2], "study_case": study_case, "report": report,
               "runner": Runner(report, study_case, qds, outages, stamp,
                                [chosen[0], chosen[1]] + list(chosen[2] or ())), "show": show,
               "csv": lambda name, header, rows: write_csv(folder, name, header, rows)}
    try:
        for test in selected:
            report.section("{}  {}".format(test, TEST_TITLES[test]))
            try:
                verdict, text, _ = TEST_FUNCTIONS[test](context)
            except Exception as exc:
                verdict, text = FAIL, "error: {}: {}".format(type(exc).__name__, exc)
            report("  {}: {}".format(verdict, text), error=verdict == FAIL)
            results["tests"][test] = {"verdict": verdict, "text": text}
    finally:
        if state is not None:
            report.section("AFTER: restore and read back")
            rows, problems = state.restore()
            table(report, ["attribute", "before", "after", "check"], rows)
            restored = not problems and all(row[3] == "OK" for row in rows)
            report("  {}".format("everything restored" if restored else "NOT fully restored: check the rows marked "
                                 "DIFFERENT and set them back by hand" + ("; " + "; ".join(problems) if problems else "")),
                   error=not restored)
            results["after"] = {"restored": restored, "rows": [list(map(str, row)) for row in rows]}
        required = [test for test in selected if test in ("P1", "P2", "P3", "P5")]
        results["accepted"] = bool(
            WRITE and required and results.get("after", {}).get("restored", False)
            and all(results["tests"].get(test, {}).get("verdict") == PASS for test in required)
            and all(item["verdict"] not in (FAIL, NOT_RECORDED) for item in results["tests"].values())
        )
        runs_done = context["runner"].runs
        results["runs"] = [{key: run.get(key) for key in ("label", "text", "code", "seconds", "copy", "rows")}
                           for run in runs_done.values()]
        report.section("SUMMARY")
        table(report, ["test", "verdict", "result"], [(test, item["verdict"], item["text"][:110])
                                                       for test, item in results["tests"].items()])
        with open(os.path.join(folder, "results.json"), "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2, default=str)
        with open(os.path.join(folder, "report.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(report.lines) + "\n")
        report("Files: {}".format(folder))
    if WRITE:
        return results["accepted"]
    return all(item["verdict"] not in (FAIL, NOT_RECORDED) for item in results["tests"].values())


if __name__ == "__main__":
    main()
