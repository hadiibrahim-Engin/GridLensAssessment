"""Result explorer against a synthetic PowerFactory API; no real project needed."""

import ast
import csv
import importlib.util
import json
import math
from pathlib import Path

import pytest

from _paths import tool

SCRIPT = tool("explore_result_object.py")
if SCRIPT is None:
    pytest.skip("development tool ui/explore_result_object.py is not part of this checkout", allow_module_level=True)
SPEC = importlib.util.spec_from_file_location("result_explorer", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class Obj:
    def __init__(self, name, kind, parent=None, **values):
        self.loc_name, self.kind, self.parent = name, kind, parent
        self.children = []
        self.__dict__.update(values)
        if parent is not None:
            parent.children.append(self)

    def GetClassName(self):
        return self.kind

    def GetFullName(self):
        return (self.parent.GetFullName()+"\\" if self.parent else "\\") + self.loc_name + "." + self.kind

    def GetParent(self):
        return self.parent

    def GetContents(self, pattern, recursive=0):
        result = []
        for child in self.children:
            result.append(child)
            if recursive:
                result.extend(child.GetContents(pattern, 1))
        return result

    def GetAttributeNames(self):
        return [name for name in ("loc_name", "desc", "calTp", "cnttime", "unreadable") if hasattr(self, name)]

    def HasAttribute(self, name):
        return name in self.__dict__

    def GetAttribute(self, name):
        if name == "unreadable":
            raise RuntimeError("Cannot read this field")
        return getattr(self, name)

    def GetAttributeType(self, name):
        return "DOUBLE" if isinstance(getattr(self, name, None), float) else "STRING"

    def GetAttributeUnit(self, name):
        return "s" if name == "cnttime" else ""

    def GetAttributeDescription(self, name):
        return "Description of " + name


class Result(Obj):
    def __init__(self, name, parent, columns=(), index=(), row_objects=(), load_code=0, **values):
        super().__init__(name, "ElmRes", parent, desc=["GridLens saved case", "Unicode: Süd"], calTp=31, **values)
        self.columns, self.index = list(columns), list(index)
        self.row_objects, self.load_code = row_objects, load_code
        self.loaded, self.released = 0, 0
        self.object_cells = {}

    def Load(self):
        self.loaded += 1
        return self.load_code

    def Release(self):
        self.released += 1
        return 0

    def GetNumberOfRows(self):
        return len(self.index)

    def GetNumberOfColumns(self):
        return len(self.columns)

    def GetVariable(self, col):
        return "b:tnow" if col == -1 else self.columns[col][0]

    def GetUnit(self, col):
        return "s" if col == -1 else self.columns[col][1]

    def GetDescription(self, col):
        return "Time" if col == -1 else "Recorded " + self.columns[col][0]

    def GetObject(self, col):
        return None if col == -1 else self.columns[col][2]

    def GetValue(self, row, col):
        value = self.index[row] if col == -1 else self.columns[col][3][row]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, tuple) else (0, value)

    def GetObjectValue(self, row, col):
        if col == -1:
            return (0, self.row_objects[row]) if self.row_objects else (2, None)
        return self.object_cells.get((row, col), (2, None))


class App:
    def __init__(self):
        self.project = Obj("Study project", "IntPrj")
        self.case = Obj("Study case", "IntCase", self.project)
        self.messages = []

    def GetActiveStudyCase(self):
        return self.case

    def GetActiveProject(self):
        return self.project

    def PrintPlain(self, text):
        self.messages.append(text)


@pytest.fixture
def model():
    app = App()
    line = Obj("Line Süd", "ElmLne", app.project, uknom=110.0)
    bus = Obj("Node", "ElmTerm", app.project)
    start = 1783296000
    index = [start+i*3600 for i in range(4)]
    res = Result("GridLens_saved_C1", app.case, [
        ("c:loading", "%", line, [0.0, 50.0, 110.0, float("nan")]),
        ("m:P:bus1", "MW", line, [-3.0, -1.0, 1.0, 3.0]),
        ("m:u", "p.u.", bus, [1.0, .99, .98, .97])], index=index)
    Obj("Line monitor", "IntMon", res, desc=["Recorded variable definitions"])
    return app, res, line, bus


def inspect(tmp_path, app, result, **kwargs):
    folder = tmp_path / "inspection"
    folder.mkdir()
    summary = probe.Explorer(app, folder, **kwargs).inspect(result)
    return folder, summary, folder / summary["results"][0]["folder"]


def test_complete_inventory_counts_equipment_once_per_object_not_per_column(tmp_path, model):
    app, result, line, bus = model
    folder, summary, sub = inspect(tmp_path, app, result)
    assert summary["result_objects"] == 1
    assert summary["discovered_objects"] == 2
    assert summary["unique_equipment"] == 2
    assert summary["equipment_by_class"] == {"ElmLne": 1, "ElmTerm": 1}
    assert summary["variable_names_count"] == 3
    assert summary["data_cells"] == 12 and summary["finite_values"] == 11
    assert summary["non_finite_values"] == 1
    assert result.loaded == result.released == 1
    assert result.desc == ["GridLens saved case", "Unicode: Süd"]
    assert [obj.loc_name for obj in result.children] == ["Line monitor"]
    assert (folder / "report.txt").exists()
    assert "Recorded variable definitions" in (folder / "report.txt").read_text()
    assert json.loads((sub / "metadata.json").read_text())["attributes"]["calTp"]["value"] == 31
    with (sub / "data_values.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 5 and rows[-1][1] == "nan"
    with (sub / "columns.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream))[0]["object_name"] == "Line Süd"


def test_time_span_is_not_row_count_and_all_column_statistics_are_exact(tmp_path, model):
    app, result, *_ = model
    _, summary, sub = inspect(tmp_path, app, result)
    axis = summary["results"][0]["axis"]
    assert axis["span_hours"] == 3.0
    assert axis["nominal_interval_hours_if_each_row_covers_one_step"] == 4.0
    assert axis["uniform_steps"] and axis["gap_candidates"] == []
    assert axis["first_epoch_candidate_utc"].endswith("+00:00")
    stats = json.loads((sub / "statistics.json").read_text())
    assert stats[0]["statistics"]["finite_values"] == 3
    assert stats[0]["statistics"]["mean"] == pytest.approx(160/3)
    assert stats[0]["statistics"]["maximum"] == {"row": 2, "value": 110.0, "axis_value": result.index[2]}
    assert stats[1]["statistics"]["mean"] == 0
    assert stats[1]["statistics"]["population_stddev"] == pytest.approx(math.sqrt(5))
    assert stats[1]["statistics"]["negative_values"] == 2


def test_sparse_contingency_results_keep_status_codes_and_use_subresult_times(tmp_path):
    app = App()
    parent = Result("Saved_N1", app.case)
    line = Obj("Line", "ElmLne", app.project)
    faults = [Obj("Fault 1", "ComOutage", app.project), Obj("Fault 2", "ComOutage", app.project)]
    for i in range(2):
        sub = Result("Step {}".format(i), parent, [("c:loading", "%", line, [(0, 112.0+i), (3, 999.0)])],
                     index=[0, 1], row_objects=faults, cnttime=1783296000+i*3600)
        sub.GetUnit = lambda col: "" if col == -1 else "%"
    folder, summary, _ = inspect(tmp_path, app, parent)
    assert summary["result_objects"] == 3 and summary["unique_equipment"] == 1
    assert summary["data_cells"] == 4 and summary["finite_values"] == 2
    assert summary["cell_status_counts"] == {"0": 2, "3": 2}
    assert summary["unique_row_objects"] == 2 and summary["row_objects_by_class"] == {"ComOutage": 2}
    assert summary["subresult_study_times"]["span_hours"] == 1
    child = summary["results"][1]
    assert "span_hours" not in child["axis"]
    assert child["axis"]["interpretation"] == "contingency/index axis"
    path = folder / child["folder"]
    statistics = json.loads((path / "statistics.json").read_text())
    assert statistics[0]["statistics"]["mean"] == 112.0
    assert statistics[0]["statistics"]["status_counts"] == {"0": 1, "3": 1}
    with (path / "data_codes.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream))[-1] == ["1", "3"]


def test_object_valued_cells_are_resolved_without_replacing_numeric_raw_indices(tmp_path, model):
    app, result, *_ = model
    fault = Obj("Outage", "ComOutage", app.project)
    result.object_cells[(2, 0)] = (0, fault)
    _, summary, folder = inspect(tmp_path, app, result)
    cells = [json.loads(line) for line in (folder / "object_cells.jsonl").read_text().splitlines()]
    assert cells == [{"row": 2, "column": 0, "status": "0", "object": probe.obj_ref(fault)}]
    assert summary["results"][0]["resolved_object_cells"] == 1
    with (folder / "data_values.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream))[3][1] == "110.0"


def test_failed_cells_and_attributes_are_reported_but_other_columns_still_scan(tmp_path, model):
    app, result, *_ = model
    result.columns[1][3][1] = RuntimeError("Unreadable cell")
    result.unreadable = 5
    folder, summary, sub = inspect(tmp_path, app, result)
    assert summary["results"][0]["status"] == "SCANNED"
    assert summary["cell_status_counts"]["EXCEPTION"] == 1
    assert summary["finite_values"] == 10
    errors = [json.loads(line) for line in (folder / "read_errors.jsonl").read_text().splitlines()]
    assert any(e["method"] == "GetValue" and e["arguments"] == [1, 1] for e in errors)
    assert any(e["method"] == "GetAttribute" and e["arguments"] == ["unreadable"] for e in errors)
    metadata = json.loads((sub / "metadata.json").read_text())
    assert "error" in metadata["attributes"]["unreadable"]["value"]
    assert result.released == 1


def test_load_failure_does_not_hide_readable_subresults(tmp_path):
    app = App()
    root = Result("Root", app.case, load_code=1)
    child = Result("Sub", root, index=[0])
    _, summary, _ = inspect(tmp_path, app, root)
    assert summary["unreadable_results"] == 1 and summary["scanned_results"] == 1
    assert not summary["coverage"]["all_rows_and_columns_scanned"]
    assert root.released == 0 and child.released == 1


def test_raw_export_can_be_disabled_but_complete_statistics_and_axis_are_retained(tmp_path, model):
    app, result, *_ = model
    result.columns.insert(0, ("b:tnow", "s", None, list(result.index)))
    _, summary, folder = inspect(tmp_path, app, result, export_values=False)
    assert summary["data_cells"] == 16 and summary["finite_values"] == 15
    assert not (folder / "data_values.csv").exists()
    assert (folder / "statistics.csv").exists()
    with (folder / "rows.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["axis_column"] == "0"
    assert rows[-1]["axis_value"] == str(result.index[-1])


def test_disabled_subresults_are_explicitly_listed(tmp_path, model):
    app, result, *_ = model
    sub = Result("Nested", result)
    folder, summary, _ = inspect(tmp_path, app, result, subresults=False)
    assert summary["result_objects"] == 1 and not sub.loaded
    assert not summary["coverage"]["subresults_enabled"]
    hierarchy = json.loads((folder / "hierarchy.json").read_text())
    assert hierarchy[0]["excluded_subresults"][0]["name"] == "Nested"


def test_empty_name_lists_results_without_creating_output_files(monkeypatch, tmp_path, model):
    app, result, *_ = model
    monkeypatch.setattr(probe, "RESULT_NAME", "")
    monkeypatch.setattr(probe, "OUTPUT_DIRECTORY", str(tmp_path / "no_output"))
    assert probe.main(app) is None
    assert any(result.GetFullName() in line for line in app.messages)
    assert not list(tmp_path.iterdir())


def test_one_name_main_creates_a_complete_local_report(monkeypatch, tmp_path, model):
    app, result, *_ = model
    monkeypatch.setattr(probe, "RESULT_NAME", result.loc_name)
    monkeypatch.setattr(probe, "OUTPUT_DIRECTORY", str(tmp_path))
    summary = probe.main(app)
    folder = Path(summary["output_directory"])
    assert folder.parent == tmp_path and (folder / "summary.json").exists()
    assert any(str(folder / "report.txt") in text for text in app.messages)


def test_exact_name_selection_prefers_active_case_and_accepts_full_path_and_slashes():
    app = App()
    current = Result("Results / C1", app.case)
    other_case = Obj("Other", "IntCase", app.project)
    other = Result("Results / C1", other_case)
    assert probe.find_result(app, "Results / C1")[0] is current
    assert probe.find_result(app, other.GetFullName())[0] is other
    Result("Results / C1", Obj("Folder", "IntFolder", app.case))
    with pytest.raises(ValueError, match="More than one ElmRes"):
        probe.find_result(app, "Results / C1")
    assert probe.find_result(app, current.GetFullName())[0] is current


def test_duplicate_object_variable_columns_are_preserved(tmp_path, model):
    app, result, *_ = model
    result.columns.append(result.columns[0])
    _, summary, _ = inspect(tmp_path, app, result)
    duplicates = summary["results"][0]["duplicate_object_variable_columns"]
    assert len(duplicates) == 1 and duplicates[0]["columns"] == [0, 3]
    assert summary["unique_equipment"] == 2 and summary["data_cells"] == 16


def test_time_gaps_duplicates_and_reverse_steps_are_not_misreported_as_coverage():
    report = probe.time_summary([0, 3600, 10800, 10800, 7200], "s", "b:tnow", {}, True)
    assert report["span_hours"] == 3
    assert report["duplicate_numeric_values"] == 1 and report["descending_steps"] == 1
    assert not report["uniform_steps"] and len(report["gap_candidates"]) == 1
    assert "nominal_interval_hours_if_each_row_covers_one_step" not in report
    unknown = probe.time_summary([0, 1, 2], "", "index", {}, False)
    assert "span_hours" not in unknown


def test_metadata_json_discovery_and_nonfinite_cycle_serialization():
    assert probe.names_from('{"attributes":[{"name":"loc_name"},{"name":"calTp"}]}') == ["loc_name", "calTp"]
    value = [float("inf")]
    value.append(value)
    assert probe.encode(value) == [{"non_finite": "inf"}, {"not_expanded": "cyclic Python value"}]


def test_class_metadata_discovers_attributes_not_exposed_by_dir(tmp_path, model):
    app, result, *_ = model
    original_get = result.GetAttribute
    result.GetAttribute = lambda name: 12345 if name == "native_only" else original_get(name)
    app.GetAvailableAttributesAsJson = lambda cls: '{"attributes":[{"name":"native_only"}]}'
    _, _, folder = inspect(tmp_path, app, result)
    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["attributes"]["native_only"]["value"] == 12345
    assert any(source["method"] == "GetAvailableAttributesAsJson" for source in metadata["attribute_discovery"])


def test_getcontents_single_argument_variant_still_discovers_result_children(tmp_path, model):
    app, result, *_ = model
    Result("Nested", result)
    result.GetContents = lambda pattern: list(result.children)
    _, summary, _ = inspect(tmp_path, app, result)
    assert summary["result_objects"] == 2 and summary["discovered_objects"] == 3


def test_current_grid_context_is_separate_from_stored_measurements(tmp_path, model):
    app, result, line, bus = model
    grid = Obj("Grid 110 kV", "ElmNet", app.project)
    line.cpGrid = bus.cpGrid = grid
    line.outserv = 1
    folder, summary, _ = inspect(tmp_path, app, result)
    assert summary["unique_grids_from_current_column_owners"] == 1
    context = json.loads((folder / "recorded_object_context.json").read_text())
    details = next(row for row in context if row["object"]["name"] == line.loc_name)
    assert details["attributes"]["outserv"] == 1
    assert "not archived result values" in details["context"]
    assert summary["finite_values"] == 11


def test_script_does_not_call_powerfactory_mutators_or_execute_arbitrary_methods():
    tree = ast.parse(SCRIPT.read_text())
    forbidden = {"Execute", "CreateObject", "AddCopy", "Delete", "Clear", "Activate", "Deactivate", "SetAttribute",
                 "SetSubElmResKey", "SetAsDefault", "AddVariable", "Write", "Flush", "GetFromStudyCase"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    assert arg.value not in forbidden
