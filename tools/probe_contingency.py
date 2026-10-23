"""GridLens probe: what PowerFactory 2026 offers for the n-1 contingency analysis.

Diagnostic tool, not part of the GridLens delivery. Install it as a separate
ComPython anywhere in the active study case and run it once. Copy the complete
output window into a text file and hand it back; GridLens part 3 (n-1 and
(n-1)') is planned from that output only.

READ ONLY. The probe never calls Execute(), CreateObject(), SetAttribute(),
Delete(), AddCopy(), Activate() or any writing ElmRes method, never assigns an
attribute and never activates a study case or operation scenario. It does not
use app.GetFromStudyCase() either, because that call creates the command when
the study case has none. Every object is found with GetContents() or
GetCalcRelevantObjects(). tests/test_probe_contingency.py checks this.

What it reports:

1. ComSimoutage: every attribute with type, unit, value and PowerFactory's own
   description; time sweep, AC/DC method, result recording, post-fault phases
   and remedial actions are highlighted by keyword.
2. ComStatsim: period, time step and time definition, and the study time.
3. Contingency definitions: classes found, number of cases, the equipment
   each one switches, where they are stored.
4. Contingency result objects (ElmRes): rows, columns, variables, time and
   contingency columns, and whether rows look dense or sparse.
5. The ElmRes interface: which reading and writing methods exist (by
   introspection only, nothing is called except reading methods).
6. Project folders and objects that could hold persistent GridLens results,
   settings and case configurations.
7. The grids of the model (active and inactive) with their lines,
   transformers and terminals, and the grids of each contingency's equipment
   (ComOutage.GetObject, a reading method of the Python reference).

Version 1.1 also reads the sub-results of a time sweep (one child ElmRes per
study time) and counts the GetValue codes: per the Python reference, code 3
means "not written because below the recording limit" in a sparse file.

Every finding is one of: VERIFIED, PRESENT BUT UNTESTED, ABSENT, MISSING OR
INACCESSIBLE, OPEN QUESTION. A method that exists is only "present but
untested": its existence does not prove that it does what part 3 needs.
"""

import math
import time

PROBE_VERSION = "1.1"
MAX_VALUE_LENGTH = 160
# At most this many items are printed in full per list (contingencies, columns, rows).
LIST_LIMIT = 25
# Rows read to judge the result structure.
SAMPLE_ROWS = 50

# Words that mark an attribute worth highlighting, by topic.
TOPICS = (
    ("time sweep", ("sweep", "time", "step", "period", "start", "end", "calc_t", "tstep", "date")),
    ("AC/DC method", ("ldf", "method", "dc", "ac", "linear")),
    ("result recording", ("res", "record", "result", "monitor", "filter")),
    ("post-fault phases", ("post", "phase", "fault", "tpost", "stage")),
    ("remedial actions", ("ras", "remedial", "action", "corrective", "redispatch")),
    ("limits and restrictions", ("limit", "max", "min", "island", "unsupplied", "shed", "loading", "volt")),
)
# Candidate classes of contingency definitions and related objects. A class
# without instance is reported as "no instance found", never as non-existent:
# without CreateObject the probe cannot tell an unknown class from an unused one.
CONTINGENCY_CLASSES = ("ComOutage", "ComContingency", "IntContingency", "ComNmink", "IntEvt", "EvtOutage",
                       "EvtSwitch", "IntRas", "IntFltcases", "IntMon")
STORAGE_CLASSES = ("IntFolder", "IntDplmap", "IntDplvec", "IntComment", "IntDocument", "IntUserdata", "IntReport",
                   "SetDesktop", "IntScheme")
PROJECT_FOLDERS = ("study", "scen", "netdat", "netmod", "oplib", "outage", "outages", "res", "script", "lib",
                   "equip", "chars", "thermal", "ra", "demand", "templ")
# Names of ElmRes methods, sorted by what they do; only READ_METHODS are ever called.
READ_METHODS = ("Load", "Release", "GetNumberOfRows", "GetNumberOfColumns", "GetObject", "GetVariable", "GetValue",
                "FindColumn", "FindMaxInColumn", "FindMinInColumn", "GetDescription", "GetUnit", "GetFirstValidObject",
                "GetObjValue", "GetSubElmRes", "GetRelCase", "GetRelCaseNumber", "GetNumberOfContingencies")
WRITE_METHODS = ("Init", "InitialiseWriting", "AddVariable", "Write", "WriteDraw", "Clear", "Flush", "Close",
                 "SetAsDefault", "SetObj", "SetSubElmResKey")
TIME_COUPLED_CLASSES = ("ElmQdsl",)
# Equipment classes counted per grid.
GRID_ELEMENT_CLASSES = ("ElmLne", "ElmTr2", "ElmTr3", "ElmTerm")
# ComOutage.GetObject(line) is read for at most this many lines.
MAX_OUTAGE_LINES = 200
# Recording limits of ComSimoutage that make its results sparse.
RECORDING_ATTRIBUTES = ("iopt_record", "loadmax", "loadmax_nk", "vlmin", "vlmax", "vmax_step", "phiu_step",
                        "diffLoadRestr", "diffLoadBase", "maxLoadBase", "diffVoltRestr", "diffVoltBase",
                        "maxVoltRestr", "maxVoltBase", "minVoltRestr", "minVoltBase", "recTermLoad", "termLoadThres")

VERIFIED, UNTESTED, ABSENT, MISSING, OPEN = ("VERIFIED", "PRESENT BUT UNTESTED", "ABSENT", "MISSING OR INACCESSIBLE",
                                             "OPEN QUESTION")
KINDS = (VERIFIED, UNTESTED, ABSENT, MISSING, OPEN)


def emit(app, message=""):
    printer = getattr(app, "PrintPlain", None)
    if callable(printer):
        try:
            printer(message)
            return
        except Exception:
            pass
    print(message, flush=True)


def call(method, *args):
    """Call a reading PowerFactory method; None when it fails or is no method."""
    if not callable(method):
        return None
    try:
        return method(*args)
    except Exception:
        return None


def safe(obj, name, default=None):
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return default if value is None else value


def class_of(obj):
    try:
        return str(obj.GetClassName())
    except Exception:
        return ""


def name_of(obj):
    value = safe(obj, "loc_name", "")
    if value:
        return str(value)
    return "<unnamed>"


def path_of(obj):
    try:
        return str(obj.GetFullName())
    except Exception:
        return name_of(obj)


def render(value):
    if isinstance(value, (list, tuple)):
        parts = ["{} '{}'".format(class_of(item), name_of(item)) if hasattr(item, "GetClassName") else str(item)
                 for item in value[:LIST_LIMIT]]
        text = "[{}{}]".format(", ".join(parts), ", ... {} more".format(len(value) - LIST_LIMIT) if len(value) > LIST_LIMIT else "")
    elif hasattr(value, "GetClassName"):
        text = "{} '{}'".format(class_of(value), name_of(value))
    else:
        text = str(value)
    return text if len(text) <= MAX_VALUE_LENGTH else text[:MAX_VALUE_LENGTH] + " ...(truncated)"


def contents(obj, pattern="*", recursive=0):
    return list(call(safe(obj, "GetContents"), pattern, recursive) or [])


def methods_of(obj):
    """Public method names, by introspection; nothing is called."""
    try:
        names = dir(obj)
    except Exception:
        return []
    return sorted(name for name in names if name[:1].isupper() and callable(safe(obj, name)))


def attribute_names(obj):
    """Attribute names: PowerFactory's accessor where it works, else dir()."""
    for getter in ("GetAttributes", "GetAttributeNames"):
        returned = call(safe(obj, getter))
        try:
            names = sorted({str(item).strip() for item in returned or () if str(item).strip()})
        except TypeError:
            names = []
        if names:
            return names
    try:
        candidates = sorted(dir(obj))
    except Exception:
        return []
    return [name for name in candidates if not name.startswith("_") and not name[:1].isupper()
            and safe(obj, name) is not None and not callable(safe(obj, name))]


def describe(obj, name):
    """(value, type, unit, description) of one attribute, all read only."""
    value = safe(obj, name)
    kind = call(safe(obj, "GetAttributeType"), name)
    unit = call(safe(obj, "GetAttributeUnit"), name)
    description = call(safe(obj, "GetAttributeDescription"), name)
    return value, "" if kind is None else str(kind), str(unit or ""), str(description or "")


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def epoch_text(value):
    seconds = number(value)
    if seconds is None or seconds < 315532800.0:
        return None
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))
    except (OverflowError, OSError, ValueError):
        return None


class Findings:
    """The classified results, printed again as a summary at the end."""

    def __init__(self, app):
        self.app = app
        self.items = []

    def add(self, kind, topic, text):
        self.items.append((kind, topic, text))
        emit(self.app, "    [{}] {}: {}".format(kind, topic, text))

    def summary(self):
        emit(self.app)
        emit(self.app, "=" * 78)
        emit(self.app, "SUMMARY - GridLens contingency probe {}".format(PROBE_VERSION))
        emit(self.app, "=" * 78)
        for kind in KINDS:
            entries = [(topic, text) for item_kind, topic, text in self.items if item_kind == kind]
            emit(self.app)
            emit(self.app, "{} ({})".format(kind, len(entries)))
            emit(self.app, "-" * 78)
            for topic, text in entries:
                emit(self.app, "  - {}: {}".format(topic, text))
            if not entries:
                emit(self.app, "  (none)")


def heading(app, text):
    emit(app)
    emit(app, "=" * 78)
    emit(app, text)
    emit(app, "=" * 78)


def print_attributes(app, obj, findings, topic):
    """Every attribute, then the ones that match a topic keyword."""
    names = attribute_names(obj)
    if not names:
        findings.add(MISSING, topic, "{} exposes no readable attribute".format(class_of(obj)))
        return {}
    described = {}
    emit(app, "  attributes ({}):".format(len(names)))
    for name in names:
        value, kind, unit, description = describe(obj, name)
        described[name] = (value, description)
        signature = ", ".join(part for part in (kind, unit) if part)
        when = epoch_text(value) if any(word in name.lower() for word in ("time", "start", "end")) else None
        emit(app, "    {}{} = {}{}{}".format(name, " [{}]".format(signature) if signature else "", render(value),
                                         " ({})".format(when) if when else "",
                                         "   -- " + description if description else ""))
    for label, words in TOPICS:
        hits = [name for name, (_, description) in described.items()
                if any(word in name.lower() or word in description.lower() for word in words)]
        emit(app, "  {} - candidate attributes: {}".format(label, ", ".join(hits[:40]) or "none"))
    return described


def study_commands(study_case, class_name):
    """Commands of that class in the study case, found without creating one."""
    return [item for item in contents(study_case, "*.{}".format(class_name)) if class_of(item) == class_name]


def probe_comsimoutage(app, study_case, findings):
    heading(app, "1. ComSimoutage (contingency analysis command)")
    commands = study_commands(study_case, "ComSimoutage")
    if not commands:
        findings.add(MISSING, "ComSimoutage", "the active study case contains no ComSimoutage; the probe does not "
                                              "create one. Add a contingency analysis to the study case and run the probe again")
        return []
    findings.add(VERIFIED, "ComSimoutage", "{} command(s) in the study case: {}".format(
        len(commands), ", ".join(name_of(item) for item in commands)))
    for command in commands:
        emit(app)
        emit(app, "  {} ({})".format(name_of(command), path_of(command)))
        described = print_attributes(app, command, findings, "ComSimoutage")
        for name, (value, description) in described.items():
            if class_of(value) == "ElmRes":
                findings.add(VERIFIED, "ComSimoutage result binding", "{}.{} -> ElmRes '{}' ({})".format(
                    name_of(command), name, name_of(value), description or "no description"))
        sweep = [name for name, (_, description) in described.items()
                 if "sweep" in name.lower() or "sweep" in description.lower()]
        if sweep:
            findings.add(UNTESTED, "time sweep", "attributes {} exist; whether they reproduce the ComStatsim time steps "
                                                "exactly is not verified without a calculation".format(", ".join(sweep)))
        else:
            findings.add(OPEN, "time sweep", "no attribute of {} mentions a time sweep in name or description".format(
                name_of(command)))
        children = contents(command)
        counts = {}
        for child in children:
            counts[class_of(child)] = counts.get(class_of(child), 0) + 1
        emit(app, "  children: {}".format(", ".join("{} x{}".format(kind, count) for kind, count in sorted(counts.items()))
                                          or "none"))
        findings.add(VERIFIED, "ComSimoutage children", "{}: {}".format(
            name_of(command), ", ".join("{} x{}".format(kind, count) for kind, count in sorted(counts.items())) or "none"))
        emit(app, "  methods: {}".format(", ".join(methods_of(command))))
    return commands


def probe_comstatsim(app, study_case, findings):
    heading(app, "2. ComStatsim (quasi-dynamic simulation) and study time")
    commands = study_commands(study_case, "ComStatsim")
    if not commands:
        findings.add(MISSING, "ComStatsim", "no ComStatsim in the active study case")
    for command in commands:
        emit(app)
        emit(app, "  {} ({})".format(name_of(command), path_of(command)))
        described = print_attributes(app, command, findings, "ComStatsim")
        start, end = (number(described.get(name, (None,))[0]) for name in ("startTime", "endTime"))
        if start is not None and end is not None:
            findings.add(VERIFIED, "QDS period", "{} to {} (startTime/endTime, epoch seconds)".format(
                epoch_text(start) or start, epoch_text(end) or end))
        else:
            findings.add(MISSING, "QDS period", "startTime/endTime not readable on {}".format(name_of(command)))
        step = [(name, described[name][0]) for name in ("calcPeriod", "stepSize", "stepUnit") if name in described]
        findings.add(VERIFIED if step else MISSING, "QDS time step", ", ".join(
            "{}={}".format(name, render(value)) for name, value in step) or "calcPeriod/stepSize/stepUnit not readable")
        result = described.get("results", (None,))[0]
        if class_of(result) == "ElmRes":
            describe_result(app, result, findings, "QDS result object")
    for setting in contents(study_case, "*.SetTime"):
        emit(app)
        emit(app, "  study time {} ({})".format(name_of(setting), path_of(setting)))
        described = print_attributes(app, setting, findings, "SetTime")
        zone = [name for name, (_, description) in described.items()
                if "zone" in name.lower() or "zone" in description.lower() or "utc" in description.lower()]
        findings.add(VERIFIED if zone else OPEN, "time definition", "time zone attributes: {}".format(", ".join(zone))
                     if zone else "no time zone attribute on SetTime; epoch seconds are shown in the local time of this computer")
    coupled = []
    for pattern in TIME_COUPLED_CLASSES:
        found = call(safe(app, "GetCalcRelevantObjects"), "*." + pattern) or []
        if found:
            coupled.append("{} x{}".format(pattern, len(found)))
    findings.add(VERIFIED, "time-coupled models", ", ".join(coupled) + " in the active grid; whether the contingency "
                 "time sweep starts from the same internal state as the QDS is not verifiable read-only"
                 if coupled else "no ElmQdsl in the active grid")


def probe_contingencies(app, project, study_case, commands, findings):
    heading(app, "3. Contingency definitions")
    roots = [("study case", study_case)] + [("command " + name_of(command), command) for command in commands]
    if project is not None:
        roots.append(("project", project))
    seen = set()
    for class_name in CONTINGENCY_CLASSES:
        found = []
        for where, root in roots:
            for item in contents(root, "*.{}".format(class_name), 1):
                key = path_of(item)
                if class_of(item) == class_name and key not in seen:
                    seen.add(key)
                    found.append((where, item))
        if not found:
            findings.add(OPEN, "contingency class " + class_name, "no instance found in the study case, its "
                                                                 "contingency commands or the project")
            continue
        findings.add(VERIFIED, "contingency class " + class_name, "{} instance(s), first in {}".format(
            len(found), found[0][0]))
        emit(app)
        emit(app, "  {}: {} instance(s)".format(class_name, len(found)))
        for where, item in found[:LIST_LIMIT]:
            emit(app, "    {} ({}) in {}".format(name_of(item), path_of(item), where))
            for name in ("loc_name", "number", "cpCase", "iopt_tp", "outserv", "event", "obj_id"):
                value = safe(item, name)
                if value is not None and name != "loc_name":
                    emit(app, "      {} = {}".format(name, render(value)))
            switched = []
            for child in contents(item):
                target = safe(child, "p_target") or safe(child, "obj_id")
                switched.append("{} {}".format(class_of(child), render(target) if target is not None else name_of(child)))
            if switched:
                emit(app, "      events/equipment: {}".format("; ".join(switched[:LIST_LIMIT])))
        first = found[0][1]
        emit(app, "  attributes of the first {}:".format(class_name))
        print_attributes(app, first, findings, class_name)
    findings.add(OPEN, "contingency set", "which of the classes above PowerFactory 2026 uses as the contingency set "
                                          "of ComSimoutage must be confirmed from section 1 (children and references)")


def describe_result(app, elmres, findings, topic, depth=0):
    """Structure of one ElmRes, with reading methods only."""
    emit(app)
    emit(app, "  {} '{}' ({})".format(topic, name_of(elmres), path_of(elmres)))
    loaded = call(safe(elmres, "Load"))
    rows, columns = number(call(safe(elmres, "GetNumberOfRows"))), number(call(safe(elmres, "GetNumberOfColumns")))
    emit(app, "    Load() -> {}; rows = {}; columns = {}".format(render(loaded), rows, columns))
    if rows is None or columns is None:
        findings.add(MISSING, topic, "'{}': row or column count not readable".format(name_of(elmres)))
        call(safe(elmres, "Release"))
        return
    rows, columns = int(rows), int(columns)
    variables, classes, special = {}, {}, []
    for column in range(min(columns, 5000)):
        variable = str(call(safe(elmres, "GetVariable"), column) or "")
        obj = call(safe(elmres, "GetObject"), column)
        variables[variable] = variables.get(variable, 0) + 1
        classes[class_of(obj) or "-"] = classes.get(class_of(obj) or "-", 0) + 1
        lowered = variable.lower()
        if any(word in lowered for word in ("case", "cont", "fault", "time", "nr", "id")) or obj is None:
            special.append((column, variable, class_of(obj) or "-", name_of(obj) if obj is not None else "-"))
    emit(app, "    variables: {}".format(", ".join("{} x{}".format(name, count) for name, count in sorted(variables.items())[:60])))
    emit(app, "    object classes: {}".format(", ".join("{} x{}".format(name, count) for name, count in sorted(classes.items()))))
    for column, variable, kind, name in special[:LIST_LIMIT]:
        emit(app, "    column {}: {} of {} '{}' (time, case or id column candidate)".format(column, variable, kind, name))
    timeline = []
    empty = 0
    checked = 0
    codes = {}
    for row in range(min(rows, SAMPLE_ROWS)):
        timeline.append(call(safe(elmres, "GetValue"), row, -1))
        for column in range(min(columns, 40)):
            value = call(safe(elmres, "GetValue"), row, column)
            checked += 1
            code = value[0] if isinstance(value, (list, tuple)) and len(value) > 1 else None
            codes[code] = codes.get(code, 0) + 1
            payload = value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else value
            if number(payload) is None:
                empty += 1
    emit(app, "    first values of the time column (-1): {}".format(render(timeline[:12])))
    emit(app, "    GetValue codes in the sample (0 ok, 3 below the recording limit): {}".format(
        ", ".join("{}: {}".format(code, count) for code, count in sorted(codes.items(), key=lambda item: str(item[0])))
        or "none"))
    if codes.get(3):
        findings.add(VERIFIED, topic + " sparse", "'{}': {} of {} sampled cells return code 3 (not written, below the "
                     "recording limit)".format(name_of(elmres), codes[3], checked))
    findings.add(VERIFIED, topic, "'{}': {} rows x {} columns, {} distinct variables".format(
        name_of(elmres), rows, columns, len(variables)))
    findings.add(VERIFIED if checked else OPEN, topic + " density", "{} of {} sampled cells without a number "
                 "(rows 0..{}, columns 0..{}); empty cells suggest a sparse structure, but only a known contingency x "
                 "time-step count can prove it".format(empty, checked, min(rows, SAMPLE_ROWS) - 1, min(columns, 40) - 1))
    call(safe(elmres, "Release"))
    subresults = [child for child in contents(elmres) if class_of(child) == "ElmRes"]
    if subresults and depth < 1:
        findings.add(VERIFIED, topic + " sub-results", "{} child ElmRes, e.g. {}".format(
            len(subresults), ", ".join(name_of(child) for child in subresults[:5])))
        for child in subresults[:2]:
            for name in ("cnttime", "pResElm", "calTp"):
                value = safe(child, name)
                if value is not None:
                    emit(app, "    sub-result {}: {} = {}{}".format(name_of(child), name, render(value),
                                                                  " ({})".format(epoch_text(value)) if epoch_text(value) else ""))
            describe_result(app, child, findings, topic + " (one study time)", depth + 1)


def probe_results(app, study_case, commands, findings):
    heading(app, "4. Contingency result objects (ElmRes)")
    for command in commands:
        limits = ["{}={}".format(name, render(safe(command, name))) for name in RECORDING_ATTRIBUTES
                  if safe(command, name) is not None]
        emit(app, "  recording limits of {}: {}".format(name_of(command), ", ".join(limits) or "none readable"))
        if limits:
            findings.add(VERIFIED, "recording limits", "{}: {} - values inside these limits are not written, so a "
                         "missing value is not 'no violation'".format(name_of(command), ", ".join(limits[:6])))
    candidates = {}
    for command in commands:
        for name in attribute_names(command):
            value = safe(command, name)
            if class_of(value) == "ElmRes":
                candidates[path_of(value)] = value
    for item in contents(study_case, "*.ElmRes", 1):
        lowered = (name_of(item) + " " + str(safe(item, "calTp", ""))).lower()
        if any(word in lowered for word in ("cont", "outage", "n-1", "simoutage")):
            candidates[path_of(item)] = item
    if not candidates:
        findings.add(MISSING, "contingency ElmRes", "no ElmRes bound to a ComSimoutage and none whose name suggests "
                                                    "contingency results; run a contingency analysis once by hand to "
                                                    "let the probe read its structure")
        return None
    first = None
    for key in sorted(candidates)[:5]:
        describe_result(app, candidates[key], findings, "contingency ElmRes")
        first = first or candidates[key]
    findings.add(OPEN, "contingency identity", "how a result row names its contingency and its time step must be "
                                               "read from the column list above and confirmed with a known case")
    return first


def probe_elmres_interface(app, elmres, study_case, findings):
    heading(app, "5. ElmRes interface (introspection only)")
    sample = elmres
    if sample is None:
        sample = next(iter(contents(study_case, "*.ElmRes", 1)), None)
    if sample is None:
        findings.add(MISSING, "ElmRes interface", "no ElmRes in the study case to inspect")
        return
    methods = methods_of(sample)
    emit(app, "  methods of ElmRes '{}': {}".format(name_of(sample), ", ".join(methods)))
    for name in READ_METHODS:
        if name in methods:
            findings.add(VERIFIED if name in ("Load", "Release", "GetNumberOfRows", "GetNumberOfColumns", "GetObject",
                                              "GetVariable", "GetValue") else UNTESTED, "ElmRes read " + name, "present")
    for name in WRITE_METHODS:
        if name in methods:
            findings.add(UNTESTED, "ElmRes write " + name, "present, never called by the probe; whether it can store "
                                                           "GridLens classification values needs tools/test_contingency.py on a project copy")
        else:
            findings.add(ABSENT, "ElmRes write " + name, "not offered by this ElmRes")
    others = [name for name in methods if name not in READ_METHODS + WRITE_METHODS]
    emit(app, "  other methods: {}".format(", ".join(others)))


def probe_storage(app, project, study_case, findings):
    heading(app, "6. Places for persistent results, settings and case configurations")
    getter = safe(app, "GetProjectFolder")
    for key in PROJECT_FOLDERS:
        folder = call(getter, key)
        if folder is not None:
            findings.add(VERIFIED, "project folder '{}'".format(key), "{} ({})".format(class_of(folder), path_of(folder)))
    kept = [item for item in contents(study_case, "*.ElmRes") if name_of(item).startswith("GridLens_")]
    findings.add(VERIFIED, "GridLens result objects", "{} ElmRes named GridLens_* in the study case{}".format(
        len(kept), ": " + ", ".join(name_of(item) for item in kept[:8]) if kept else ""))
    counts = {}
    for child in contents(study_case):
        counts[class_of(child)] = counts.get(class_of(child), 0) + 1
    emit(app, "  study case children: {}".format(", ".join("{} x{}".format(kind, count) for kind, count in sorted(counts.items()))))
    for class_name in STORAGE_CLASSES:
        found = contents(project, "*.{}".format(class_name), 1) if project is not None else []
        found = [item for item in found if class_of(item) == class_name]
        if found:
            findings.add(VERIFIED, "storage class " + class_name, "{} instance(s), e.g. {}".format(
                len(found), path_of(found[0])))
            emit(app, "  first {}:".format(class_name))
            print_attributes(app, found[0], findings, class_name)
        else:
            findings.add(OPEN, "storage class " + class_name, "no instance in the project; whether the class can be "
                                                              "created there is not verifiable without CreateObject")
    findings.add(OPEN, "native settings storage", "which object can hold an immutable GridLens settings snapshot per "
                                                  "run must be decided from the instances above and tested on a project copy")


def grid_of(obj):
    """Grid name of an element: attribute cpGrid, else the ElmNet in its path."""
    grid = safe(obj, "cpGrid")
    if hasattr(grid, "GetClassName"):
        return name_of(grid)
    for part in reversed(path_of(obj).split("\\")):
        if part.endswith(".ElmNet"):
            return part[:-len(".ElmNet")]
    return ""


def outage_elements(outage):
    """The interrupted components of a ComOutage, by ComOutage.GetObject(line) until None."""
    found = []
    getter = safe(outage, "GetObject")
    for line in range(MAX_OUTAGE_LINES if callable(getter) else 0):
        element = call(getter, line)
        if element is None:
            break
        found.append(element)
    return found


def probe_grids(app, project, commands, findings):
    heading(app, "7. Grids of the model and of the contingencies")
    grids = {}
    for grid in call(safe(app, "GetCalcRelevantObjects"), "*.ElmNet") or []:
        grids[name_of(grid)] = "active"
    for grid in contents(call(safe(app, "GetProjectFolder"), "netdat") or project, "*.ElmNet", 1):
        grids.setdefault(name_of(grid), "inactive")
    counts = {}
    for class_name in GRID_ELEMENT_CLASSES:
        for element in call(safe(app, "GetCalcRelevantObjects"), "*." + class_name) or []:
            key = (grid_of(element) or "(no grid)", class_name)
            counts[key] = counts.get(key, 0) + 1
    for name in sorted(set(grids) | {grid for grid, _ in counts}, key=str.casefold):
        emit(app, "  {:<40} {:<9} {}".format(name, grids.get(name, "-"), ", ".join(
            "{} x{}".format(class_name, counts[(name, class_name)]) for class_name in GRID_ELEMENT_CLASSES
            if (name, class_name) in counts) or "no line, transformer or terminal"))
    findings.add(VERIFIED if grids else MISSING, "grids", "{} grid(s): {}".format(len(grids), ", ".join(
        "{} ({})".format(name, state) for name, state in sorted(grids.items())[:12])) if grids else "no ElmNet found")
    for command in commands:
        outages = [item for item in contents(command, "*.ComOutage") if class_of(item) == "ComOutage"]
        by_grid, unreadable = {}, []
        emit(app)
        emit(app, "  contingencies of {} and the grids of their equipment:".format(name_of(command)))
        for index, outage in enumerate(outages):
            elements = outage_elements(outage)
            if not elements:
                unreadable.append(name_of(outage))
            names = sorted({grid_of(element) or "(no grid)" for element in elements})
            for name in names:
                by_grid[name] = by_grid.get(name, 0) + 1
            if index < LIST_LIMIT * 4:
                emit(app, "    {} (Not analysed: {}): {} | grids: {}".format(
                    name_of(outage), safe(outage, "outserv", "?"),
                    ", ".join("{} '{}'".format(class_of(element), name_of(element)) for element in elements[:6]) or "-",
                    ", ".join(names) or "-"))
        findings.add(VERIFIED if outages and len(unreadable) < len(outages) else OPEN, "contingency equipment",
                     "{} of {} contingencies of {} name their equipment through ComOutage.GetObject; per grid: {}".format(
                         len(outages) - len(unreadable), len(outages), name_of(command),
                         ", ".join("{} {}".format(name, count) for name, count in sorted(by_grid.items())) or "none"))


def probe(app):
    findings = Findings(app)
    heading(app, "GridLens contingency probe {} - read only".format(PROBE_VERSION))
    emit(app, "  started {}".format(time.strftime("%Y-%m-%d %H:%M:%S")))
    project = call(safe(app, "GetActiveProject"))
    study_case = call(safe(app, "GetActiveStudyCase"))
    version = call(safe(app, "GetVersion")) or call(safe(app, "GetBuildNumber"))
    findings.add(VERIFIED if version else MISSING, "PowerFactory version", render(version) if version else "not readable")
    if project is None or study_case is None:
        findings.add(MISSING, "context", "no active project or study case; activate both and run the probe again")
        findings.summary()
        return findings
    findings.add(VERIFIED, "context", "project '{}', study case '{}'".format(name_of(project), name_of(study_case)))
    holder = {"commands": [], "result": None}
    sections = (
        lambda: probe_comstatsim(app, study_case, findings),
        lambda: holder.update(commands=probe_comsimoutage(app, study_case, findings)),
        lambda: probe_contingencies(app, project, study_case, holder["commands"], findings),
        lambda: holder.update(result=probe_results(app, study_case, holder["commands"], findings)),
        lambda: probe_elmres_interface(app, holder.get("result"), study_case, findings),
        lambda: probe_storage(app, project, study_case, findings),
        lambda: probe_grids(app, project, holder["commands"], findings),
    )
    for section in sections:
        try:
            section()
        except Exception as exc:  # one failing section must not hide the others
            findings.add(MISSING, "probe section", "stopped with {}: {}".format(type(exc).__name__, exc))
    for question in (
            "Does a ComSimoutage time sweep compute exactly the ComStatsim time steps (start, end, step, last step)?",
            "Does the time sweep apply IntPlannedout objects in their windows with the same iopt_maint semantics as the QDS?",
            "Which result rows and columns identify contingency, time step and post-fault phase?",
            "Are contingency results sparse (only violations stored) or dense?",
            "Which object holds the common contingency set, and can n-1 and (n-1)' share it unchanged?",
            "Can an ElmRes store GridLens classification codes, and can they be read back unchanged?",
            "Which native object stores GridLens settings and case configurations inside the project?",
            "What does PowerFactory report for a contingency whose element a planned outage already switches off?"):
        findings.add(OPEN, "part 3", question)
    findings.summary()
    return findings


def main():
    import powerfactory  # noqa: F401  (only available inside PowerFactory)

    app = powerfactory.GetApplication()
    probe(app)


if __name__ == "__main__":
    main()
