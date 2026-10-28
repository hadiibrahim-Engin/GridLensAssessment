"""GridLens diagnostic probe for the PowerFactory 2026 contingency interface - PRIVACY MODE STRICT.

Diagnostic tool, not part of the GridLens delivery. Install it as a separate
ComPython in the study case that holds the contingency analysis and run it
once. The output is meant to be passed on to external developers or AI
systems: it contains only fixed technical labels and fixed status tokens.

Privacy by design (strict allowlist):

* Every PowerFactory call goes through ReadOnlyApi. Only the methods in
  ALLOWED_CALLS can be called; they are reading methods according to the
  PowerFactory 2026 Python reference. Writing or executing methods are only
  checked for existence (looked up, never called).
* Attributes are checked with HasAttribute(name) for names from fixed
  allowlists; their values are never read. The only attribute values read are
  the two result-object references in REFERENCE_ATTRIBUTES, which are used and
  never shown.
* No name, path, key, description, user, comment, value, time stamp, count or
  model size is read for output. Result cells are only inspected for the
  GetValue status code; the value itself is never looked at.
* Every output line is "label: token" with the label from LABELS and the token
  from TOKENS (or a validated small integer for the version lines). A failed
  check yields ERROR_<nn> for its category, never the exception text.
* No file is written, no network is used, nothing is executed, created,
  changed, deleted or activated. The probe does not switch study cases or
  operation scenarios and does not use GetFromStudyCase (it creates a missing
  command).

A question that cannot be answered without reading project data is reported as
NOT_VERIFIED_PRIVACY_RESTRICTION. tests/test_inspect_contingency_interface.py checks these
rules with artificial objects; that is no guarantee for an unknown real project
(see docs/superpowers/specs/2026-10-23-n1-settings-design.md, section 2.1).
"""

import sys

PROBE_VERSION = "2.3"
PRIVACY_MODE = "STRICT"

# --- What may be called, checked and printed --------------------------------
# Reading methods only (PowerFactory 2026 Python reference):
#   Application.GetActiveStudyCase / GetActiveProject / GetInterfaceVersion / GetCalcRelevantObjects,
#   DataObject.GetClassName / GetContents / HasAttribute / GetAttributeType,
#   ElmRes.Load / Release / GetNumberOfRows / GetNumberOfColumns / GetValue / GetVariable,
#   ComOutage.GetObject ("get the element stored in line ..."),
#   ElmRes.GetRelCase ("get the contingency object for the given case number"), called with fixed numbers only,
#   ElmRes.GetObjectValue ("returns a value from a result object for row iX"; only the class of the object is used).
ALLOWED_CALLS = frozenset((
    "GetActiveStudyCase", "GetActiveProject", "GetInterfaceVersion", "GetCalcRelevantObjects",
    "GetClassName", "GetContents", "HasAttribute", "GetAttributeType",
    "Load", "Release", "GetNumberOfRows", "GetNumberOfColumns", "GetValue", "GetVariable",
    "GetObject", "GetRelCase", "GetObjectValue",
))
# Attribute values that may be read: references to the result objects, used and never shown.
REFERENCE_ATTRIBUTES = frozenset(("p_rescnt", "p_rescntDC"))

COMMAND_CLASSES = ("ComSimoutage", "ComStatsim", "ComNmink", "ComLdf")
# Attributes whose existence and type (never the value) are checked, per class.
SIMOUTAGE_ATTRIBUTES = (
    "iEnableTS", "startTime", "endTime", "stepSize", "stepUnit", "stepNumber", "studyTime", "calcPeriod",
    "isPlannedOutages", "p_rescnt", "p_rescntDC", "iopt_method", "iopt_Linear", "timePhases", "iopt_evts",
    "rasActive", "iPerformOpt", "iopt_record", "loadmax", "vlmin", "vlmax", "diffLoadBase", "maxLoadBase",
)
# Writing or executing methods: only whether they exist.
SIMOUTAGE_METHODS = ("Execute", "ExecuteAndCheck", "AddCntcy", "AddContingencies", "RemoveContingencies",
                     "ClearCont", "Reset", "Update", "GetNTopLoadedElms")
OUTAGE_ATTRIBUTES = ("outserv", "n_k", "number")
STATSIM_ATTRIBUTES = ("iopt_maint", "startTime", "endTime", "stepSize", "stepUnit", "calcPeriod", "results")
SUBRESULT_ATTRIBUTES = ("cnttime", "pResElm")
NMINK_ATTRIBUTES = ("optSel", "iopt_lne", "iopt_trf", "iopt_sym", "iopt_n1", "iopt_n2")
NMINK_METHODS = ("AddRef", "Clear", "GenerateContingenciesForAnalysis", "GetAll")
ELMRES_READ_METHODS = ("Load", "Release", "GetNumberOfRows", "GetNumberOfColumns", "GetValue", "GetVariable",
                       "GetObject", "FindColumn", "GetColumnValues", "GetSubElmRes", "GetRelCase", "GetUnit",
                       "GetDescription")
ELMRES_WRITE_METHODS = ("InitialiseWriting", "AddVariable", "Write", "WriteDraw", "FinishWriting", "Flush",
                        "Clear", "SetObj", "SetSubElmResKey", "SetAsDefault")
# Equipment classes a contingency may switch; only membership is reported.
EQUIPMENT_CLASSES = frozenset(("ElmLne", "ElmTr2", "ElmTr3", "ElmTr4", "ElmTerm", "ElmSym", "ElmGenstat", "ElmPvsys",
                               "ElmLod", "ElmCoup", "ElmScap", "ElmSind", "ElmShnt", "ElmVsc", "ElmRec", "ElmBranch"))
# Standard PowerFactory variable names that would mark a contingency or phase reference in a result
# object. Only "one of them is recorded" is reported, never which variable or column. The list is a
# starting point: a variable that is not in it cannot be recognised.
CONTINGENCY_VARIABLES = frozenset(("c:maxCntcy", "c:cntcy", "b:icntcy", "b:ifcase", "c:ifcase", "c:ncont"))
PHASE_VARIABLES = frozenset(("b:tphase", "c:tphase", "c:timephase"))
LOADING_VARIABLES = frozenset(("c:loading", "c:maxLoading", "m:loading"))
VOLTAGE_VARIABLES = frozenset(("m:u", "m:u1", "c:maxvolt", "c:minvolt"))
# Every standard variable name of these lists is reported on its own: recorded or not.
REPORTED_VARIABLES = tuple(sorted(CONTINGENCY_VARIABLES | PHASE_VARIABLES | LOADING_VARIABLES | VOLTAGE_VARIABLES))
# GetRelCase is tried with these fixed case numbers only; no number is ever taken from a result cell.
REL_CASE_NUMBERS = (0, 1, 2, 3)
# Variable names (never values) are read for at most this many columns.
VARIABLE_COLUMNS = 5000
STORAGE_CLASSES = ("IntDplmap", "IntDplvec", "IntFolder")
# Bounds of the GetValue status sample: rows x columns of one result object.
SAMPLE_ROWS, SAMPLE_COLUMNS = 50, 40
# GetValue status codes (Python reference): 0 ok, 1 row out of bound, 2 column out of bound,
# 3 not written in a sparse file because below the recording limit.
CODE_OK, CODE_SPARSE = 0, 3

TOKENS = frozenset((
    "TRUE", "FALSE", "NO", "PRESENT", "ABSENT", "AVAILABLE", "AVAILABLE_UNTESTED", "NOT_AVAILABLE",
    "DETECTED", "NOT_DETECTED", "NOT_VERIFIED", "NOT_VERIFIED_PRIVACY_RESTRICTION", "NOT_APPLICABLE", "STRICT",
    "INTEGER", "INTEGER64", "DOUBLE", "STRING", "OBJECT", "INTEGER_VEC", "DOUBLE_VEC", "STRING_VEC", "OBJECT_VEC",
    "OTHER_TYPE", "INTEGER64_VEC", "DOUBLE_MAT", "INVALID", "CODE_0", "CODE_1", "CODE_2", "CODE_3", "CODE_OTHER",
))
# The members of PowerFactory's AttributeType (Python reference, DataObject.GetAttributeType).
ATTRIBUTE_TYPES = frozenset(("INTEGER", "INTEGER64", "DOUBLE", "STRING", "OBJECT", "INTEGER_VEC", "DOUBLE_VEC",
                             "STRING_VEC", "OBJECT_VEC", "INTEGER64_VEC", "DOUBLE_MAT", "INVALID"))
# Labels whose value is a small integer (validated) instead of a token.
INTEGER_LABELS = frozenset(("Interface version", "Python major", "Python minor"))
SECTIONS = ("PowerFactory API", "Study case", "Contingency Analysis", "Contingency set", "Contingency Definition",
            "QDS command", "ElmRes", "Result Structure", "Network scope", "Storage", "Privacy")
ERROR_CODES = {section: "ERROR_{:02d}".format(number) for number, section in enumerate(SECTIONS, 1)}
PRIVACY_LABELS = ("Object names collected", "Project paths collected", "Network parameters collected",
                  "Raw result values output", "Time stamps output", "Counts or sizes output", "Files written",
                  "Network access", "Calculations executed", "Objects changed")


def _labels():
    labels = {"Privacy mode", "Interface version", "Python major", "Python minor", "Version compatibility",
              "Active study case", "Error"}
    labels |= {"{} available".format(name) for name in COMMAND_CLASSES}
    labels |= {"Time sweep interface", "Planned outage interface", "Recording limit interface",
               "Result interface", "Time phase interface", "Remedial action interface",
               "Regional analysis interface"}
    for attribute in SIMOUTAGE_ATTRIBUTES + OUTAGE_ATTRIBUTES + NMINK_ATTRIBUTES + STATSIM_ATTRIBUTES + SUBRESULT_ATTRIBUTES:
        labels |= {"Attribute {}".format(attribute), "Type {}".format(attribute)}
    labels |= {"ComSimoutage.{}".format(name) for name in SIMOUTAGE_METHODS}
    labels |= {"ComNmink.{}".format(name) for name in NMINK_METHODS}
    labels |= {"ElmRes.{}".format(name) for name in ELMRES_READ_METHODS + ELMRES_WRITE_METHODS}
    labels |= {"Contingencies in the command", "ComOutage.GetObject", "Equipment readable",
               "Equipment class recognised", "Equipment grid attribute"}
    labels |= {"AC result object", "Readable", "Rows present", "Columns present", "Sub-results per study time",
               "Sub-result readable", "Index column readable", "Sparse recording indicator",
               "Loading variables recorded", "Voltage variables recorded", "Contingency identification",
               "Time phase identification", "Time identification", "Sub-result rows present",
               "Sub-result columns present", "Index column status", "Index column status (column -1)",
               "Row-to-contingency mapping (GetRelCase)", "Row objects are contingencies (GetObjectValue)",
               "Column objects are equipment (GetObject)"}
    labels |= {"QDS time definition attributes", "IntPlannedout instances"}
    labels |= {"Variable {}".format(name) for name in REPORTED_VARIABLES}
    labels |= {"Grids readable", "Element grid attribute"}
    labels |= {"{} instances".format(name) for name in STORAGE_CLASSES}
    labels |= set(PRIVACY_LABELS)
    return frozenset(labels)


LABELS = _labels()


class PrivacyViolation(RuntimeError):
    """A line that is not on the allowlist was about to be printed: a defect of the probe, never shown."""


class ProbeError(Exception):
    """A check failed; it carries no message, only the check category is reported."""


class Report:
    """The only way to output anything: fixed labels and fixed tokens."""

    def __init__(self, printer):
        self.printer = printer
        self.lines = []
        self.current = None

    def title(self):
        self._print("GridLens Diagnostic Probe {}".format(PROBE_VERSION))
        self._print("Privacy Mode: {}".format(PRIVACY_MODE))

    def section(self, name):
        if name not in SECTIONS:
            raise PrivacyViolation()
        self.current = name
        self._print("")
        self._print(name + ":")

    def add(self, label, token):
        if label not in LABELS:
            raise PrivacyViolation()
        if label in INTEGER_LABELS:
            if not (isinstance(token, int) and not isinstance(token, bool) and 0 <= token <= 999):
                token = "NOT_VERIFIED"
        elif token not in TOKENS and token not in ERROR_CODES.values():
            raise PrivacyViolation()
        self._print("  {}: {}".format(label, token))

    def error(self):
        self.add("Error", ERROR_CODES[self.current])

    def _print(self, line):
        self.lines.append(line)
        self.printer(line)


class ReadOnlyApi:
    """Gateway for every PowerFactory access; it records each call for the tests."""

    def __init__(self, app):
        self.app = app
        self.calls = []

    def call(self, obj, method, *args):
        if method not in ALLOWED_CALLS:
            raise PrivacyViolation()
        self.calls.append(method)
        try:
            return getattr(obj, method)(*args)
        except Exception:
            raise ProbeError() from None

    def has_method(self, obj, method):
        """Whether the method exists; it is looked up, never called."""
        try:
            return callable(getattr(obj, method))
        except Exception:
            return False

    def has_attribute(self, obj, attribute):
        try:
            return self.call(obj, "HasAttribute", attribute) in (1, True)
        except ProbeError:
            return False

    def attribute_type(self, obj, attribute):
        try:
            kind = self.call(obj, "GetAttributeType", attribute)
        except ProbeError:
            return "NOT_VERIFIED"
        # PowerFactory returns an AttributeType member; its name (INTEGER, DOUBLE, ...) is used. A text is
        # reduced to its first keyword. Only a known keyword is reported; anything else is OTHER_TYPE.
        member = getattr(kind, "name", None)
        if isinstance(member, str):
            keyword = member.upper()
        else:
            keyword = kind.split(",")[0].strip().upper() if isinstance(kind, str) else ""
        return keyword if keyword in ATTRIBUTE_TYPES else "OTHER_TYPE"

    def reference(self, obj, attribute):
        """The value of a result-object reference attribute; used, never shown."""
        if attribute not in REFERENCE_ATTRIBUTES:
            raise PrivacyViolation()
        try:
            return getattr(obj, attribute)
        except Exception:
            return None

    def class_of(self, obj):
        try:
            value = self.call(obj, "GetClassName")
        except ProbeError:
            return ""
        return value if isinstance(value, str) else ""

    def contents(self, obj, pattern, recursive=False):
        try:
            found = self.call(obj, "GetContents", pattern, 1) if recursive else self.call(obj, "GetContents", pattern)
            return list(found or [])
        except (ProbeError, TypeError):
            return []

    def of_class(self, obj, class_name, recursive=False):
        return [item for item in self.contents(obj, "*." + class_name, recursive) if self.class_of(item) == class_name]


def flag(value, yes="TRUE", no="FALSE"):
    return yes if value else no


def check_api(api, report, state):
    report.add("Privacy mode", PRIVACY_MODE)
    try:
        version = api.call(api.app, "GetInterfaceVersion")
    except ProbeError:
        version = None
    report.add("Interface version", version)
    report.add("Python major", sys.version_info[0])
    report.add("Python minor", sys.version_info[1])
    # Which interface versions GridLens supports is not established yet.
    report.add("Version compatibility", "NOT_VERIFIED")


def check_study_case(api, report, state):
    try:
        state["study_case"] = api.call(api.app, "GetActiveStudyCase")
    except ProbeError:
        state["study_case"] = None
    report.add("Active study case", flag(state["study_case"] is not None, "PRESENT", "ABSENT"))
    for class_name in COMMAND_CLASSES:
        found = api.of_class(state["study_case"], class_name) if state["study_case"] is not None else []
        state[class_name] = found[0] if found else None
        report.add("{} available".format(class_name), flag(found))


def _attributes(api, report, obj, attributes):
    present = {}
    for attribute in attributes:
        present[attribute] = api.has_attribute(obj, attribute)
        report.add("Attribute {}".format(attribute), flag(present[attribute], "PRESENT", "ABSENT"))
        if present[attribute]:
            report.add("Type {}".format(attribute), api.attribute_type(obj, attribute))
    return present


def _methods(api, report, obj, prefix, methods):
    for name in methods:
        report.add("{}.{}".format(prefix, name), flag(api.has_method(obj, name), "AVAILABLE_UNTESTED", "NOT_AVAILABLE"))


def check_simoutage(api, report, state):
    command = state.get("ComSimoutage")
    if command is None:
        report.add("Time sweep interface", "NOT_APPLICABLE")
        return
    present = _attributes(api, report, command, SIMOUTAGE_ATTRIBUTES)
    sweep = all(present[name] for name in ("iEnableTS", "startTime", "endTime", "stepSize", "stepUnit"))
    report.add("Time sweep interface", flag(sweep, "PRESENT", "ABSENT"))
    report.add("Planned outage interface", flag(present["isPlannedOutages"], "PRESENT", "ABSENT"))
    report.add("Recording limit interface", flag(present["loadmax"] or present["iopt_record"], "PRESENT", "ABSENT"))
    report.add("Result interface", flag(present["p_rescnt"], "PRESENT", "ABSENT"))
    report.add("Time phase interface", flag(present["timePhases"], "PRESENT", "ABSENT"))
    report.add("Remedial action interface", flag(present["rasActive"], "PRESENT", "ABSENT"))
    report.add("Regional analysis interface", flag(present["iPerformOpt"], "PRESENT", "ABSENT"))
    _methods(api, report, command, "ComSimoutage", SIMOUTAGE_METHODS)
    state["results"] = api.reference(command, "p_rescnt") if present["p_rescnt"] else None


def check_contingency_set(api, report, state):
    command = state.get("ComSimoutage")
    outages = api.of_class(command, "ComOutage") if command is not None else []
    report.add("Contingencies in the command", flag(outages, "PRESENT", "ABSENT"))
    if not outages:
        return
    first = outages[0]
    _attributes(api, report, first, OUTAGE_ATTRIBUTES)
    has_getter = api.has_method(first, "GetObject")
    report.add("ComOutage.GetObject", flag(has_getter, "AVAILABLE", "NOT_AVAILABLE"))
    element = None
    if has_getter:
        try:
            element = api.call(first, "GetObject", 0)
        except ProbeError:
            element = None
    # Only whether an element comes back, whether its class is a known equipment class and
    # whether it carries the grid attribute; never which element.
    report.add("Equipment readable", flag(element is not None))
    report.add("Equipment class recognised", flag(element is not None and api.class_of(element) in EQUIPMENT_CLASSES))
    report.add("Equipment grid attribute", flag(element is not None and api.has_attribute(element, "cpGrid"),
                                                "PRESENT", "ABSENT"))


def check_statsim(api, report, state):
    """The QDS command of the same study case: whether its time definition can be compared with the sweep."""
    command = state.get("ComStatsim")
    if command is None:
        report.add("QDS time definition attributes", "NOT_APPLICABLE")
        return
    present = _attributes(api, report, command, STATSIM_ATTRIBUTES)
    report.add("QDS time definition attributes", flag(all(present[name] for name in ("startTime", "endTime", "stepSize",
                                                                                     "stepUnit")), "PRESENT", "ABSENT"))


def check_nmink(api, report, state):
    command = state.get("ComNmink")
    if command is None:
        report.add("ComNmink available", "FALSE")
        return
    _attributes(api, report, command, NMINK_ATTRIBUTES)
    _methods(api, report, command, "ComNmink", NMINK_METHODS)


def check_elmres(api, report, state):
    results = state.get("results")
    if results is None or api.class_of(results) != "ElmRes":
        report.add("AC result object", "ABSENT")
        state["results"] = None
        return
    report.add("AC result object", "PRESENT")
    for name in ELMRES_READ_METHODS:
        report.add("ElmRes.{}".format(name), flag(api.has_method(results, name), "AVAILABLE", "NOT_AVAILABLE"))
    for name in ELMRES_WRITE_METHODS:
        report.add("ElmRes.{}".format(name), flag(api.has_method(results, name), "AVAILABLE_UNTESTED", "NOT_AVAILABLE"))


def _status(returned):
    """The GetValue status code; the value next to it is never looked at."""
    if isinstance(returned, (list, tuple)) and returned and isinstance(returned[0], int):
        return returned[0]
    return None


def _code_token(code):
    if code in (0, 1, 2, 3):
        return "CODE_{}".format(code)
    return "CODE_OTHER" if code is not None else "NOT_VERIFIED"


def _inspect(api, result):
    """Structure of one result object as booleans and status codes; values are never kept or shown."""
    found = dict.fromkeys(("readable", "rows", "columns", "index", "sparse", "contingency", "phase", "loading",
                           "voltage", "relcase"), False)
    found.update(variables=set(), index_code=None, index_code_last=None, row_objects=False, column_objects=False)
    try:
        api.call(result, "Load")
    except ProbeError:
        return found
    try:
        rows, columns = api.call(result, "GetNumberOfRows"), api.call(result, "GetNumberOfColumns")
        if not all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in (rows, columns)):
            return found
        found["readable"] = True
        rows, columns = int(rows), int(columns)
        found["rows"], found["columns"] = rows > 0, columns > 0
        for column in range(min(columns, VARIABLE_COLUMNS)):
            variable = api.call(result, "GetVariable", column)
            # Only names of the fixed list are kept; any other variable name is dropped at once.
            if isinstance(variable, str) and variable in REPORTED_VARIABLES:
                found["variables"].add(variable)
        found["contingency"] = bool(found["variables"] & CONTINGENCY_VARIABLES)
        found["phase"] = bool(found["variables"] & PHASE_VARIABLES)
        found["loading"] = bool(found["variables"] & LOADING_VARIABLES)
        found["voltage"] = bool(found["variables"] & VOLTAGE_VARIABLES)
        for row in range(min(rows, SAMPLE_ROWS)):
            code = _status(api.call(result, "GetValue", row))
            found["index_code"] = code if found["index_code"] is None else found["index_code"]
            found["index"] |= code == CODE_OK
            last = _status(api.call(result, "GetValue", row, -1))
            found["index_code_last"] = last if found["index_code_last"] is None else found["index_code_last"]
            for column in range(min(columns, SAMPLE_COLUMNS)):
                found["sparse"] |= _status(api.call(result, "GetValue", row, column)) == CODE_SPARSE
        for row in range(min(rows, SAMPLE_ROWS)):
            returned = api.call(result, "GetObjectValue", row)
            # Only the class of a returned object is looked at, never the object itself.
            if isinstance(returned, (list, tuple)) and len(returned) > 1 and returned[0] == CODE_OK:
                found["row_objects"] |= api.class_of(returned[1]) == "ComOutage"
        for column in range(min(columns, SAMPLE_COLUMNS)):
            found["column_objects"] |= api.class_of(api.call(result, "GetObject", column)) in EQUIPMENT_CLASSES
        for number in REL_CASE_NUMBERS:
            try:
                case = api.call(result, "GetRelCase", number)
            except ProbeError:
                continue
            found["relcase"] |= case is not None and api.class_of(case) == "ComOutage"
    except ProbeError:
        found["readable"] = False
    finally:
        try:
            api.call(result, "Release")
        except ProbeError:
            pass
    return found


def check_result_structure(api, report, state):
    results = state.get("results")
    if results is None:
        report.add("Readable", "NOT_APPLICABLE")
        return
    top = _inspect(api, results)
    report.add("Readable", flag(top["readable"]))
    report.add("Rows present", flag(top["rows"]))
    report.add("Columns present", flag(top["columns"]))
    children = api.of_class(results, "ElmRes")
    report.add("Sub-results per study time", flag(children, "DETECTED", "NOT_DETECTED"))
    sample = top
    if children:
        sample = _inspect(api, children[0])
        report.add("Sub-result readable", flag(sample["readable"]))
        report.add("Sub-result rows present", flag(sample["rows"]))
        report.add("Sub-result columns present", flag(sample["columns"]))
    report.add("Index column readable", flag(sample["index"]))
    # The first status code of the index column, with the column omitted and with column -1; never the value.
    report.add("Index column status", _code_token(sample["index_code"]))
    report.add("Index column status (column -1)", _code_token(sample["index_code_last"]))
    report.add("Row objects are contingencies (GetObjectValue)", flag(sample["row_objects"], "DETECTED", "NOT_DETECTED"))
    report.add("Column objects are equipment (GetObject)", flag(sample["column_objects"], "DETECTED", "NOT_DETECTED"))
    if children:
        _attributes(api, report, children[0], SUBRESULT_ATTRIBUTES)
    relcase = sample["relcase"] or top["relcase"]
    report.add("Row-to-contingency mapping (GetRelCase)", flag(relcase, "DETECTED", "NOT_DETECTED"))
    for name in REPORTED_VARIABLES:
        report.add("Variable {}".format(name), flag(name in sample["variables"], "DETECTED", "NOT_DETECTED"))
    report.add("Sparse recording indicator", flag(sample["sparse"], "DETECTED", "NOT_DETECTED"))
    report.add("Loading variables recorded", flag(sample["loading"], "DETECTED", "NOT_DETECTED"))
    report.add("Voltage variables recorded", flag(sample["voltage"], "DETECTED", "NOT_DETECTED"))
    # Without reading column objects or values, an identification can be confirmed but never ruled out.
    report.add("Contingency identification", "DETECTED" if sample["contingency"] else "NOT_VERIFIED_PRIVACY_RESTRICTION")
    report.add("Time phase identification", "DETECTED" if sample["phase"] else "NOT_VERIFIED_PRIVACY_RESTRICTION")
    # Proving the time base would mean reading the index values, which are study times.
    report.add("Time identification", "NOT_VERIFIED_PRIVACY_RESTRICTION")


def check_network_scope(api, report, state):
    try:
        grids = list(api.call(api.app, "GetCalcRelevantObjects", "*.ElmNet") or [])
        lines = list(api.call(api.app, "GetCalcRelevantObjects", "*.ElmLne") or [])
    except (ProbeError, TypeError):
        grids, lines = [], []
    report.add("Grids readable", flag(grids))
    report.add("Element grid attribute", flag(lines and api.has_attribute(lines[0], "cpGrid"), "PRESENT", "ABSENT"))


def check_storage(api, report, state):
    try:
        project = api.call(api.app, "GetActiveProject")
    except ProbeError:
        project = None
    report.add("IntPlannedout instances", flag(project is not None and api.of_class(project, "IntPlannedout", recursive=True),
                                               "DETECTED", "NOT_DETECTED"))
    for class_name in STORAGE_CLASSES:
        # Stored anywhere in the project, so the search is recursive (GetContents(pattern, 1)).
        found = project is not None and bool(api.of_class(project, class_name, recursive=True))
        # Whether GridLens may create such objects needs a separate, released write test.
        report.add("{} instances".format(class_name), flag(found, "DETECTED", "NOT_DETECTED"))


CHECKS = (
    ("PowerFactory API", check_api),
    ("Study case", check_study_case),
    ("Contingency Analysis", check_simoutage),
    ("Contingency set", check_contingency_set),
    ("Contingency Definition", check_nmink),
    ("QDS command", check_statsim),
    ("ElmRes", check_elmres),
    ("Result Structure", check_result_structure),
    ("Network scope", check_network_scope),
    ("Storage", check_storage),
)


def probe(app, printer=None):
    """Run every check; returns the report (report.lines is the complete output, report.api the call log)."""
    report = Report(printer or app.PrintPlain)
    report.title()
    api = ReadOnlyApi(app)
    state = {}
    for section, check in CHECKS:
        report.section(section)
        try:
            check(api, report, state)
        except PrivacyViolation:
            raise
        except Exception:
            # Never the exception text: only the category of the failed check.
            report.error()
    report.section("Privacy")
    for label in PRIVACY_LABELS:
        report.add(label, "NO")
    report.api = api
    return report


def main():
    import powerfactory

    probe(powerfactory.GetApplication())


if __name__ == "__main__":
    main()
