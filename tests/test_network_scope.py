"""Network scope: grid selection for the assessed equipment and (stored only) for the contingencies."""

from __future__ import annotations

import importlib.util

import pytest

from _paths import delivered

SPEC = importlib.util.spec_from_file_location("gridlens_scope", delivered("gridlens_report.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)

PERIOD = (0.0, 30 * 24 * 3600.0)


class Obj:
    def __init__(self, name, kind, path=None, children=(), elements=(), **attributes):
        self.loc_name, self._kind, self._path = name, kind, path or "\\P\\" + name + "." + kind
        self._children, self._elements = list(children), list(elements)
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self._kind

    def GetFullName(self):
        return self._path

    def GetContents(self, pattern="*", recursive=0):
        found = []
        for child in self._children:
            if pattern in ("*", "*." + child._kind):
                found.append(child)
            if recursive:
                found += child.GetContents(pattern, 1)
        return found

    def GetObject(self, line):
        return self._elements[line] if line < len(self._elements) else None

    def Execute(self):
        raise AssertionError("nothing may be executed")


GA = Obj("Grid A", "ElmNet")
GB = Obj("Grid B", "ElmNet")
GC = Obj("Grid C", "ElmNet")


def line(name, grid):
    return Obj(name, "ElmLne", cpGrid=grid)


@pytest.fixture(autouse=True)
def defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


def test_grid_selection_is_parsed_sorted_and_checked():
    assert gl.parse_setting("monitoring_grids", ["Grid B", "Grid A"]) == (("Grid A", "Grid B"), None)
    assert gl.parse_setting("contingency_grids", None) == (None, None)
    assert "twice" in gl.parse_setting("monitoring_grids", ["GA", "GA"])[1]
    assert "list of grid names" in gl.parse_setting("monitoring_grids", "Grid A")[1]
    assert "list of grid names" in gl.parse_setting("monitoring_grids", ["", "x"])[1]
    assert gl.parse_setting("monitoring_grids", None)[1], "only the contingencies may follow the assessment"
    assert gl.setting_text("monitoring_grids", ()) == "every grid"
    assert gl.setting_text("contingency_grids", None) == gl.SAME_AS_ASSESSMENT


def test_selected_grids_decide_the_assessed_equipment_and_take_precedence(monkeypatch):
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "B")
    assert gl.element_in_scope(line("L1", GB)) and not gl.element_in_scope(line("L2", GA))
    gl.activate_settings({"monitoring_grids": ["Grid A"]})
    assert gl.element_in_scope(line("L2", GA)) and not gl.element_in_scope(line("L1", GB))
    assert gl.grid_scope_text() == "elements in the grid Grid A"
    gl.reset_settings()
    monkeypatch.setattr(gl, "GRID_NAME_FILTER", "")
    assert gl.element_in_scope(line("L1", GB)) and gl.grid_scope_text() == "all elements"


def test_project_grids_lists_every_grid_of_the_model_and_marks_inactive_ones():
    class App:
        def GetCalcRelevantObjects(self, pattern):
            return [GA, GB] if pattern == "*.ElmNet" else []

        def GetProjectFolder(self, key):
            return Obj("Network Data", "IntPrjfolder", children=[GA, GB, GC]) if key == "netdat" else None

    assert gl.project_grids(App()) == [("Grid A", True), ("Grid B", True), ("Grid C", False)]

    class Broken:
        def GetCalcRelevantObjects(self, pattern):
            raise RuntimeError("no project")

    assert gl.project_grids(Broken()) == []


def _study_case():
    outages = [Obj("Line A1", "ComOutage", elements=[line("Line A1", GA)], number=1, outserv=0),
               Obj("Tie A-B", "ComOutage", elements=[line("Tie A-B", GA), line("Tie part B", GB)], number=2, outserv=0),
               Obj("Line B1", "ComOutage", elements=[line("Line B1", GB)], number=3, outserv=0),
               Obj("Skipped", "ComOutage", elements=[line("Line B2", GB)], number=4, outserv=1),
               Obj("Empty", "ComOutage", number=5, outserv=0)]
    command = Obj("Contingency Analysis", "ComSimoutage", children=outages)
    return Obj("Study", "IntCase", children=[command])


def test_contingencies_are_read_with_their_equipment_and_grids():
    info = gl.read_contingencies(_study_case())

    assert info["command"] == "Contingency Analysis"
    by_name = {item["name"]: item for item in info["contingencies"]}
    assert by_name["Tie A-B"]["grids"] == ["Grid A", "Grid B"]
    assert by_name["Skipped"]["analysed"] is False and by_name["Empty"]["elements"] == []
    assert gl.read_contingencies(Obj("Other study", "IntCase")) is None


def test_contingency_scope_keeps_contingencies_whose_equipment_lies_in_the_grids():
    info = gl.read_contingencies(_study_case())

    scope = gl.contingency_scope(info, ("Grid A",))
    assert scope["in"] == ["Line A1"] and scope["partly"] == ["Tie A-B"] and scope["outside"] == ["Line B1"]
    assert scope["unknown"] == ["Empty"] and scope["not_analysed"] == ["Skipped"]
    # The n-1 grid filter is independent of the report filter: None means every grid.
    assert gl.contingency_scope(info, None, ("Grid B",))["in"] == gl.contingency_scope(info, ())["in"]
    assert len(gl.contingency_scope(info, ())["in"]) == 3, "no grid: every readable contingency"
    text = gl.contingency_scope_text(info, ("Grid A",))
    assert text.startswith("1 of 5 contingencies of 'Contingency Analysis' in scope (Grid A)")
    assert "1 partly outside" in text and text.endswith("Applied to the n-1 run: the contingencies outside are 'Not analysed' for the run.")
    assert gl.contingency_scope_text(None, None).startswith("no contingency analysis")


def test_editor_selects_grids_at_once_and_warns_about_missing_or_inactive_ones():
    config = gl.empty_case_config()
    edit = gl.CaseEditor([], config, PERIOD, grids=[("Grid A", True), ("Grid C", False)],
                         contingencies=gl.read_contingencies(_study_case()))

    assert edit.set_grids("monitoring_grids", ["Grid A", "Grid C", "Gone"]) is None
    assert edit.selected_grids("monitoring_grids") == ("Gone", "Grid A", "Grid C")
    assert edit.selected_grids("contingency_grids") is None
    warnings = [text for _, text in edit.grid_problems()]
    assert any("'Gone'" in text and "no longer exists" in text for text in warnings)
    assert any("'Grid C'" in text and "not active" in text for text in warnings)
    assert edit.grid_choices() == ["Gone", "Grid A", "Grid C"]
    assert "Report filter: Gone, Grid A, Grid C" in edit.calculation_preview()
    assert "Filters: Calculate now: the report filter acts on the evaluation only" in edit.calculation_preview()
    assert "Contingencies: 3 of 5 contingencies" in edit.calculation_preview(), "the report filter does not filter n-1"
    assert edit.set_grids("contingency_grids", ["Grid B"]) is None
    assert edit.settings_overrides()["contingency_grids"] == ("Grid B",)
    assert edit.set_grids("monitoring_grids", []) is None and "monitoring_grids" not in edit.settings_overrides()
    # Scalar settings applied afterwards keep the grid selection.
    assert edit.set_settings({"line_limit": "110"}) == []
    assert edit.settings_overrides() == {"contingency_grids": ("Grid B",), "line_limit": 110.0}


def test_the_report_names_the_network_scope():
    gl.activate_settings({"monitoring_grids": ["Grid A"]})
    payload = gl.empty_payload()
    gl._model_quality(payload, [], {"contingency_scope": "1 of 5 contingencies ... Applied to the n-1 run."})

    rows = {row["check_id"]: row for row in payload["ScriptedModelQuality"]}
    assert "Assessed equipment: elements in the grid Grid A" in rows["network_scope"]["message"]
    assert "Applied to the n-1 run" in rows["network_scope"]["message"]


def test_the_summary_grid_of_a_study_case_is_not_offered():
    study = Obj("Study", "IntCase")
    summary = Obj("Summary Grid", "ElmNet")
    summary.GetParent = lambda: study
    folder = Obj("Network Data", "IntPrjfolder")
    GA.GetParent = GB.GetParent = lambda: folder

    class App:
        def GetCalcRelevantObjects(self, pattern):
            return [GA, summary] if pattern == "*.ElmNet" else []

        def GetProjectFolder(self, key):
            return Obj("Network Data", "IntPrjfolder", children=[GA, GB]) if key == "netdat" else None

    try:
        assert gl.project_grids(App()) == [("Grid A", True), ("Grid B", False)]
        assert gl.is_summary_grid(summary) and not gl.is_summary_grid(GA)
    finally:
        del GA.GetParent, GB.GetParent


# ---------------------------------------------------------------------------
# n-1 filters: grids and outaged elements
# ---------------------------------------------------------------------------
def _equipment():
    study = _study_case()
    command = study.GetContents("*.ComSimoutage")[0]
    return gl.contingency_equipment(command)


def test_n1_filters_leave_out_contingencies_by_grid_and_by_element():
    equipment = _equipment()
    keys = {gl.object_name(outage): gl.object_key(outage) for outage, _ in equipment}
    found = gl.excluded_contingencies(equipment, grids=("Grid A",), elements=())
    assert found == {keys["Line B1"]: "outside the n-1 grids", keys["Skipped"]: "outside the n-1 grids"}
    tie_part = next(gl.object_key(item) for outage, items in equipment for item in items if item.loc_name == "Tie part B")
    found = gl.excluded_contingencies(equipment, grids=(), elements=(tie_part,))
    # Only contingencies outaging a selected element stay; "Empty" has no readable equipment and stays too.
    assert found == {keys[name]: "outages no selected element" for name in ("Line A1", "Line B1", "Skipped")}
    assert gl.excluded_contingencies(equipment, grids=(), elements=()) == {}


def test_element_choices_come_from_the_contingencies_and_the_editor_keeps_them():
    info = gl.read_contingencies(_study_case())
    choices = gl.contingency_element_choices(None, info)
    assert [name for _, name, _, _ in choices] == ["Line A1", "Line B1", "Line B2", "Tie A-B", "Tie part B"]
    edit = gl.CaseEditor([], gl.empty_case_config(), PERIOD, contingencies=info, elements=choices, kept=["261024-122303"])
    key = choices[1][0]
    assert edit.set_elements([key]) is None and edit.selected_elements() == (key,)
    assert edit.element_text(key) == "Line B1 (ElmLne, Grid B)"
    assert "Outaged elements only: Line B1 (ElmLne, Grid B)." in edit.contingency_preview()
    assert edit.set_elements([key, key]).endswith("an element is selected twice")
    assert edit.set_evaluate_stamp("261024-122303") is None
    assert edit.filter_note().startswith("Re-evaluate the kept run of ")
    assert "cannot be added without calculating again" in edit.filter_note()
