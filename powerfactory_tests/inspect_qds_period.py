"""GridLens probe: which simulated period does GridLens read from the quasi-dynamic simulation?

Diagnostic tool, not part of the GridLens delivery. Run it as its own
ComPython in the study case GridLens uses. It only reads: nothing is
calculated, written or created.

The question: the QDS dialog shows a user-defined period in one year, the
case manager shows another one, and every planned outage counts as outside
the simulated period. GridLens reads ComStatsim.startTime / endTime of the
object app.GetFromStudyCase("ComStatsim") returns. This probe shows

Q1  how many ComStatsim objects the project holds and where (active study
    case or elsewhere), and which one GridLens reads,
Q2  for each: calcPeriod and every time-like attribute, so the attribute that
    holds the period of the dialog can be found,
Q3  the year of the study case time and of the planned outage windows.

Privacy: no object name, path, user or result value is printed. Times appear
only as their year and as hours relative to the first time of the same object.
"""

import math
import re
from datetime import datetime

PROBE_VERSION = "1.0"
TIME_PATTERN = re.compile(r"time|start|end|begin|per|date|year|step|day|month|hour", re.I)
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
CLASS_RE = re.compile(r"^[A-Z][a-z]{2}[A-Za-z0-9]{1,30}$")
# Epoch seconds between 1980 and 2100 are treated as times.
EPOCH_MIN, EPOCH_MAX = 315532800, 4102444800


def emit(app, line):
    if hasattr(app, "PrintPlain"):
        app.PrintPlain("[probe] " + line)
    else:
        print("[probe] " + line)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def year_of(seconds):
    try:
        return datetime.fromtimestamp(seconds).year
    except (OSError, OverflowError, ValueError):
        return None


def shown(value, origin=None):
    """A value as a token: times as their year and the hours from `origin`, other numbers as they are."""
    if value is None:
        return "NONE"
    numeric = number(value)
    if numeric is None:
        if isinstance(value, (list, tuple)):
            return "VECTOR({})".format(len(value))
        if isinstance(value, str):
            return "TEXT({})".format(len(value))
        return "OBJECT {}".format(class_of(value) or "OTHER")
    if EPOCH_MIN < numeric < EPOCH_MAX:
        text = "YEAR {}".format(year_of(numeric))
        if origin is not None:
            text += ", {:+g} h".format(round((numeric - origin) / 3600.0, 2))
        return text
    if abs(numeric) > 1e8:
        return "LARGE_NUMBER"
    return "{:g}".format(numeric)


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
    path = full_name(obj)
    if not path:
        return "UNREADABLE"
    if study_case is not None and path.startswith(full_name(study_case)):
        return "ACTIVE_STUDY_CASE"
    if project is not None and path.startswith(full_name(project)):
        return "OTHER_PLACE_IN_PROJECT"
    return "OUTSIDE_PROJECT"


def contents(obj, pattern):
    try:
        return [item for item in obj.GetContents(pattern, 1) or [] if item is not None]
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


def read(obj, attribute):
    try:
        return True, getattr(obj, attribute)
    except Exception:
        return False, None


def report_command(app, index, qds, study_case, project, read_by_gridlens):
    emit(app, "")
    emit(app, "ComStatsim #{}: {}{}".format(index, location(qds, study_case, project),
                                           ", READ BY GRIDLENS" if read_by_gridlens else ""))
    values = []
    for name in attribute_names(qds):
        if not TIME_PATTERN.search(name):
            continue
        found, value = read(qds, name)
        if found and not callable(value):
            values.append((name, value))
    times = [number(value) for _, value in values
             if number(value) is not None and EPOCH_MIN < number(value) < EPOCH_MAX]
    origin = min(times) if times else None
    for name in ("calcPeriod", "startTime", "endTime"):
        if name not in [item[0] for item in values]:
            found, value = read(qds, name)
            values.append((name, value if found else "NOT_FOUND"))
    for name, value in sorted(values):
        emit(app, "  {}: {}".format(name, value if value == "NOT_FOUND" else shown(value, origin)))
    start, end = number(read(qds, "startTime")[1]), number(read(qds, "endTime")[1])
    readable = start is not None and end is not None and end >= start
    emit(app, "  period as GridLens reads it (startTime..endTime): {}".format(
        "YEAR {} .. YEAR {}".format(year_of(start), year_of(end)) if readable else "NOT READABLE"))


def main(app=None):
    if app is None:
        import powerfactory
        app = powerfactory.GetApplication()
    emit(app, "GridLens probe QDS period {} (read only)".format(PROBE_VERSION))
    study_case = app.GetActiveStudyCase()
    project = app.GetActiveProject()
    if study_case is None or project is None:
        emit(app, "No active project or study case; activate the study case GridLens uses and run again.")
        return
    found, value = read(study_case, "iStudyTime")
    emit(app, "study case time [iStudyTime]: {}".format(shown(value) if found else "NOT_FOUND"))
    clock = contents(study_case, "*.SetTime")
    if clock:
        found, date = read(clock[0], "cDate")
        digits = number(date) if found else None
        emit(app, "SetTime.cDate year: {}".format(int(digits) // 10000 if digits else "NOT_FOUND"))
    in_case = [item for item in contents(study_case, "*.ComStatsim") if class_of(item) == "ComStatsim"]
    in_case_names = {full_name(item) for item in in_case}
    elsewhere = [item for item in contents(project, "*.ComStatsim")
                 if class_of(item) == "ComStatsim" and full_name(item) not in in_case_names]
    emit(app, "ComStatsim in the active study case: {}; elsewhere in the project: {}".format(len(in_case), len(elsewhere)))
    # GetFromStudyCase creates a ComStatsim when the study case has none; this probe creates nothing.
    gridlens = app.GetFromStudyCase("ComStatsim") if in_case else None
    gridlens_name = full_name(gridlens) if gridlens is not None else ""
    if not in_case:
        emit(app, "The active study case holds no ComStatsim: GridLens would create a new one with default settings.")
    elif gridlens_name not in in_case_names:
        emit(app, "GridLens would read a ComStatsim that is not among the ones listed below.")
    for index, qds in enumerate(in_case + elsewhere, 1):
        report_command(app, index, qds, study_case, project, full_name(qds) == gridlens_name)
    years = {}
    for outage in contents(project, "*.IntPlannedout"):
        start = number(read(outage, "starttime")[1])
        key = "YEAR {}".format(year_of(start)) if start is not None and EPOCH_MIN < start < EPOCH_MAX else "NOT READABLE"
        years[key] = years.get(key, 0) + 1
    emit(app, "")
    emit(app, "planned outages by start year: {}".format(
        ", ".join("{} x{}".format(key, count) for key, count in sorted(years.items())) or "none"))


if __name__ == "__main__":
    main()
