"""Privacy and read-only tests of the strict diagnostic probe, with artificial PowerFactory objects.

Every artificial object carries sensitive-looking strings and numbers (names,
paths, users, comments, values, study times). The tests check that none of
them ever reaches the output, that only allowlisted methods are called, that
no other attribute is read, and that failures yield only error codes. They
cannot prove the behaviour of an unknown real project.
"""

from __future__ import annotations

import ast
import importlib.util
import re

import pytest

from _paths import tool

PROBE = tool("probe_contingency.py")
TEST_RUN = tool("test_contingency.py")
if PROBE is None:
    pytest.skip("development tool not in this checkout", allow_module_level=True)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load("probe_contingency", PROBE)

SECRET = "SECRET"  # every sensitive artificial string contains it
SECRET_NUMBERS = ("1462449600", "123.456", "987654", "4354401012")
# Calls that change a project or start a calculation; the probe must never call them.
WRITING_CALLS = {"Execute", "ExecuteAndCheck", "CreateObject", "SetAttribute", "Delete", "AddCopy", "PasteCopy",
                 "Activate", "Deactivate", "Write", "WriteDraw", "AddVariable", "Init", "InitialiseWriting",
                 "FinishWriting", "Clear", "Flush", "SetAsDefault", "Close", "Move", "GetFromStudyCase", "SetObj",
                 "SetSubElmResKey", "AddCntcy", "AddContingencies", "RemoveContingencies", "ClearCont", "Reset",
                 "Update", "AddRef", "GenerateContingenciesForAnalysis", "SetObjs", "RemoveEvents", "GetAll",
                 "GetNTopLoadedElms", "Rename", "SetTime"}
# What the probe may touch on an object: the allowlisted calls, the reference attributes and the
# method names it only looks up (never calls).
LOOKED_UP = set(probe.SIMOUTAGE_METHODS) | set(probe.NMINK_METHODS) | set(probe.ELMRES_READ_METHODS) | \
    set(probe.ELMRES_WRITE_METHODS) | {"GetObject"}
PERMITTED_ACCESS = set(probe.ALLOWED_CALLS) | set(probe.REFERENCE_ATTRIBUTES) | LOOKED_UP


def _contents(data, pattern, recursive):
    found = []
    for child in data["children"]:
        child_data = object.__getattribute__(child, "_data")
        if pattern in ("*", "*." + child_data["kind"]):
            found.append(child)
        if recursive:
            found += _contents(child_data, pattern, recursive)
    return found


class AttributeType:
    """Like PowerFactory's AttributeType member: its name is the type keyword."""

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return "AttributeType." + SECRET + "_SHOULD_NOT_BE_PRINTED"


class Log:
    accessed = []
    called = []


class Fake:
    """A PowerFactory object stand-in that logs every attribute access and every call."""

    def __init__(self, kind, attributes=None, children=(), methods=None, raises=False):
        object.__setattr__(self, "_data", {"kind": kind, "attributes": dict(attributes or {}),
                                           "children": list(children), "methods": dict(methods or {}),
                                           "raises": raises})

    def __getattribute__(self, name):
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        data = object.__getattribute__(self, "_data")
        Log.accessed.append(name)
        builtin = {"GetClassName": lambda: data["kind"],
                   "GetContents": lambda pattern="*", recursive=0: _contents(data, pattern, recursive),
                   "HasAttribute": lambda attribute: 1 if attribute in data["attributes"] else 0,
                   "GetAttributeType": lambda attribute: AttributeType("INTEGER" if attribute != "loadmax" else SECRET),
                   "GetFullName": lambda: "\\" + SECRET + "_USER.IntUser\\" + SECRET + "_PROJECT.IntPrj",
                   "Execute": lambda *args: 0,
                   "CreateObject": lambda *args: None}
        if name in data["methods"]:
            method = data["methods"][name]
        elif name in builtin:
            method = builtin[name]
        elif name in data["attributes"]:
            return data["attributes"][name]
        elif name == "loc_name":
            return SECRET + "_NAME_" + data["kind"]
        else:
            raise AttributeError(name)

        def logged(*args):
            Log.called.append(name)
            if data["raises"] and name != "GetClassName":
                raise RuntimeError(SECRET + " exception text with \\" + SECRET + "_PATH")
            return method(*args)
        return logged


CASE = None  # the ComOutage GetRelCase and GetObjectValue return; set by _app
LINE = None  # the element of every result column; set by _app


def _results(code_three=True):
    def value(row, column=None):
        if column is None:
            return (0, 1462449600.0)  # a study time: must never appear
        if column == -1:
            return (3, 4354401012.0)
        return (3, 0.0) if code_three and row == 1 and column == 1 else (0, 123.456)

    methods = {"Load": lambda: None, "Release": lambda: None, "GetNumberOfRows": lambda: 4,
               "GetNumberOfColumns": lambda: 3, "GetValue": value,
               "GetVariable": lambda column: ["c:loading", "c:" + SECRET + "_VARIABLE", "m:u"][column],
               "GetSubElmRes": lambda *args: None, "Write": lambda *args: None,
               "GetRelCase": lambda number: CASE if number == 1 else None,
               "GetObjectValue": lambda row, column=None: (0, CASE),
               "GetObject": lambda column: LINE,
               "AddVariable": lambda *args: None, "InitialiseWriting": lambda *args: None}
    child = Fake("ElmRes", {"cnttime": 1462449600, "loc_name": SECRET + "_STUDY_TIME_NAME"}, methods=methods)
    top = dict(methods, GetNumberOfRows=lambda: 0, GetNumberOfColumns=lambda: 0)
    return Fake("ElmRes", {"loc_name": SECRET + "_RESULT"}, children=[child], methods=top)


def _app(raises=False, code_three=True):
    grid = Fake("ElmNet", {"loc_name": SECRET + "_GRID"})
    line = Fake("ElmLne", {"cpGrid": grid, "dline": 987654, "loc_name": SECRET + "_LINE"})
    outage = Fake("ComOutage", {"outserv": 0, "number": 987654, "loc_name": SECRET + "_CONTINGENCY"},
                  methods={"GetObject": lambda index: line if index == 0 else None}, raises=raises)
    global CASE, LINE
    CASE, LINE = outage, line
    attributes = dict({name: 987654 for name in probe.SIMOUTAGE_ATTRIBUTES}, p_rescnt=_results(code_three))
    simoutage = Fake("ComSimoutage", attributes, children=[outage],
                     methods={"Execute": lambda: None, "ClearCont": lambda: None}, raises=raises)
    nmink = Fake("ComNmink", {"optSel": 1, "iopt_lne": 1}, methods={"AddRef": lambda *args: None})
    statsim = Fake("ComStatsim", {"iopt_maint": 0, "startTime": 1462449600, "endTime": 1462449600, "stepSize": 1,
                                  "stepUnit": 2, "loc_name": SECRET + "_QDS"})
    study = Fake("IntCase", {"loc_name": SECRET + "_STUDY_CASE", "desc": [SECRET + " comment"]},
                 children=[simoutage, nmink, statsim, Fake("ComLdf")], raises=raises)
    # Storage objects lie deep inside the project: only a recursive search finds them.
    library = Fake("IntPrjfolder", {"loc_name": SECRET + "_LIBRARY"},
                   children=[Fake("IntDplmap"), Fake("IntFolder"), Fake("IntPlannedout", {"loc_name": SECRET + "_FS"})])
    project = Fake("IntPrj", {"loc_name": SECRET + "_PROJECT"}, children=[library])
    return Fake("Application", methods={
        "GetActiveStudyCase": lambda: study, "GetActiveProject": lambda: project, "GetInterfaceVersion": lambda: 2,
        "GetCalcRelevantObjects": lambda pattern: {"*.ElmNet": [grid], "*.ElmLne": [line]}.get(pattern, []),
        "GetFromStudyCase": lambda name: None})


@pytest.fixture
def run():
    def execute(**options):
        Log.accessed, Log.called = [], []
        printed = []
        report = probe.probe(_app(**options), printed.append)
        return report, "\n".join(printed)
    return execute


def _values(report):
    return dict(line.strip().split(": ", 1) for line in report.lines if line.startswith("  "))


def test_no_sensitive_string_or_value_ever_reaches_the_output(run):
    report, text = run()

    assert SECRET not in text
    assert not any(number in text for number in SECRET_NUMBERS)
    assert report.lines == text.split("\n")


def test_every_output_line_is_an_allowlisted_label_with_an_allowlisted_token(run):
    report, _ = run()

    pattern = re.compile(r"^  (?P<label>.+?): (?P<token>\S+)$")
    for line in report.lines[2:]:
        if not line or (line.endswith(":") and line[:-1] in probe.SECTIONS):
            continue
        match = pattern.match(line)
        assert match, line
        label, token = match["label"], match["token"]
        assert label in probe.LABELS, line
        assert token in probe.TOKENS or token in probe.ERROR_CODES.values() or (
            label in probe.INTEGER_LABELS and token.isdigit() and len(token) <= 3), line


def test_only_allowlisted_methods_are_called_and_nothing_writes(run):
    report, _ = run()

    assert set(report.api.calls) <= probe.ALLOWED_CALLS
    assert set(Log.called) <= probe.ALLOWED_CALLS, set(Log.called) - probe.ALLOWED_CALLS
    assert not set(Log.called) & WRITING_CALLS


def test_no_name_path_or_other_attribute_is_read(run):
    run()

    read = set(Log.accessed) - {"PrintPlain"}
    assert read <= PERMITTED_ACCESS, read - PERMITTED_ACCESS
    for forbidden in ("loc_name", "GetFullName", "desc", "cnttime", "dline", "number", "cpGrid", "objectKey",
                      "gnrl_modby", "GetAttribute"):
        assert forbidden not in read, forbidden


def test_the_expected_findings_are_reported(run):
    report, text = run()

    lines = _values(report)
    assert lines["Privacy mode"] == "STRICT" and lines["Interface version"] == "2"
    assert lines["ComSimoutage available"] == "TRUE"
    assert lines["Time sweep interface"] == "PRESENT" and lines["Planned outage interface"] == "PRESENT"
    assert lines["Type iEnableTS"] == "INTEGER", "the name of the AttributeType member"
    assert lines["Type loadmax"] == "OTHER_TYPE", "an unknown member name is never printed"
    assert lines["ComSimoutage.Execute"] == "AVAILABLE_UNTESTED"
    assert lines["Equipment readable"] == "TRUE" and lines["Equipment grid attribute"] == "PRESENT"
    assert lines["ElmRes.AddVariable"] == "AVAILABLE_UNTESTED" and lines["ElmRes.GetValue"] == "AVAILABLE"
    assert lines["Sub-results per study time"] == "DETECTED"
    assert lines["Sparse recording indicator"] == "DETECTED"
    assert lines["Loading variables recorded"] == "DETECTED"
    assert lines["Contingency identification"] == "NOT_VERIFIED_PRIVACY_RESTRICTION"
    assert lines["Variable c:loading"] == "DETECTED" and lines["Variable m:u"] == "DETECTED"
    assert lines["Variable c:maxCntcy"] == "NOT_DETECTED"
    assert lines["Index column status"] == "CODE_0" and lines["Index column status (column -1)"] == "CODE_3"
    assert lines["Row-to-contingency mapping (GetRelCase)"] == "DETECTED"
    assert lines["Sub-result rows present"] == "TRUE" and lines["Sub-result columns present"] == "TRUE"
    assert lines["Row objects are contingencies (GetObjectValue)"] == "DETECTED"
    assert lines["Column objects are equipment (GetObject)"] == "DETECTED"
    assert lines["Attribute cnttime"] == "PRESENT" and lines["Attribute pResElm"] == "ABSENT"
    assert lines["ComStatsim available"] == "TRUE" and lines["QDS time definition attributes"] == "PRESENT"
    assert lines["Attribute iopt_maint"] == "PRESENT" and lines["IntPlannedout instances"] == "DETECTED"
    assert lines["Time identification"] == "NOT_VERIFIED_PRIVACY_RESTRICTION"
    assert lines["IntDplmap instances"] == "DETECTED" and lines["IntDplvec instances"] == "NOT_DETECTED"
    assert lines["Grids readable"] == "TRUE" and lines["Element grid attribute"] == "PRESENT"
    assert all(lines[label] == "NO" for label in probe.PRIVACY_LABELS)
    assert text.startswith("GridLens Diagnostic Probe 2.3\nPrivacy Mode: STRICT")


def test_without_code_three_no_sparse_indicator_is_claimed(run):
    report, _ = run(code_three=False)

    assert _values(report)["Sparse recording indicator"] == "NOT_DETECTED"


def test_failures_yield_only_error_codes_never_their_text(run):
    report, text = run(raises=True)

    assert SECRET not in text and "exception" not in text.lower() and "Traceback" not in text
    tokens = [line.split(": ", 1)[1] for line in report.lines if line.startswith("  ")]
    assert all(token in probe.TOKENS or token in probe.ERROR_CODES.values() or token.isdigit() for token in tokens)
    assert _values(report)["ComSimoutage available"] == "FALSE", "a failing GetContents finds nothing"


def test_a_check_that_crashes_reports_its_category_only(run, monkeypatch):
    def crash(api, report, state):
        raise ValueError(SECRET + " internal detail")
    monkeypatch.setattr(probe, "CHECKS", probe.CHECKS[:1] + (("Study case", crash),) + probe.CHECKS[2:])

    report, text = run()

    assert "  Error: " + probe.ERROR_CODES["Study case"] in report.lines and SECRET not in text


def test_a_label_or_token_outside_the_allowlist_cannot_be_printed():
    report = probe.Report(lambda line: None)
    report.section("Storage")
    with pytest.raises(probe.PrivacyViolation):
        report.add("Project " + SECRET, "TRUE")
    with pytest.raises(probe.PrivacyViolation):
        report.add("IntDplmap instances", SECRET)
    with pytest.raises(probe.PrivacyViolation):
        report.section(SECRET)
    report.add("Interface version", "2; " + SECRET)
    assert report.lines[-1] == "  Interface version: NOT_VERIFIED"
    with pytest.raises(probe.PrivacyViolation):
        probe.ReadOnlyApi(None).call(object(), "Execute")
    with pytest.raises(probe.PrivacyViolation):
        probe.ReadOnlyApi(None).reference(object(), "loc_name")


# --- Static analysis of the source ---------------------------------------------
SOURCE = PROBE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def test_static_no_forbidden_names_imports_files_or_network():
    imports = {alias.name.split(".")[0] for node in ast.walk(TREE) if isinstance(node, (ast.Import, ast.ImportFrom))
               for alias in node.names}
    assert imports <= {"sys", "powerfactory"}, imports
    names = {node.id for node in ast.walk(TREE) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(TREE) if isinstance(node, ast.Attribute)}
    called = {node.func.id for node in ast.walk(TREE) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not {"open", "eval", "exec", "compile", "__import__", "repr", "setattr", "print", "input"} & names
    # str is used for isinstance checks only, never to turn an object into text.
    assert "str" not in called and "format" not in called
    assert not {"loc_name", "GetFullName", "GetAttribute", "desc", "objectKey", "GetFromStudyCase", "SetAttribute",
                "write", "environ", "getcwd", "gethostname", "argv", "executable", "path", "version"} & attributes
    assert "RUN_EXPERIMENT" not in SOURCE


def test_static_every_call_on_a_powerfactory_object_goes_through_the_gateway():
    called = {node.func.attr for node in ast.walk(TREE) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    pf_methods = {name for name in called if name[:1].isupper()}
    # Capitalised calls outside the gateway: only the module entry point.
    assert pf_methods <= {"GetApplication"}, pf_methods
    assert not called & WRITING_CALLS


def test_static_format_only_on_constant_templates():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            assert isinstance(node.func.value, ast.Constant), ast.unparse(node)
    joined = [node for node in ast.walk(TREE) if isinstance(node, ast.JoinedStr)]
    assert not joined, "no f-strings: every line goes through Report.add"


def test_static_only_the_report_prints():
    owners = set()
    for function in (node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)):
        if any(isinstance(item, ast.Attribute) and item.attr in ("PrintPlain", "printer") for item in ast.walk(function)):
            owners.add(function.name)
    assert owners <= {"_print", "probe", "__init__"}, owners


@pytest.mark.skipif(TEST_RUN is None, reason="development tool not in this checkout")
def test_prepared_test_run_is_disabled_by_default():
    """The full behaviour of the test run is covered by tests/test_contingency_run.py."""
    run_tool = _load("test_contingency_tool", TEST_RUN)

    assert run_tool.ENABLED is False and run_tool.PROJECT_COPY_NAME == ""
    assert all(SECRET not in text for text in run_tool.PRECONDITION_TEXTS.values())
    source = TEST_RUN.read_text(encoding="utf-8")
    assert source.count("confirm(") >= 4, "every test asks before it calculates or writes"
