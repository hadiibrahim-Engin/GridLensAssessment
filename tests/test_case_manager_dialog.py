"""The case manager window with real Tk: what a click does (skipped without Tk or a display).

gui_NN refers to the functional checks 1-20 of the GUI specification; the
editing rules behind each click are tested without a window in test_planner.py.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gridlens_dialog", ROOT / "powerfactory" / "gridlens_report.py")
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)

HOUR = 3600.0
PERIOD = (0.0, 30 * 24 * HOUR)


def _widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _widgets(child)


def _texts(root):
    found = []
    for widget in _widgets(root):
        try:
            found.append(str(widget.cget("text")))
        except Exception:
            pass
    return found


def _button(root, label):
    return next(widget for widget in _widgets(root) if _safe_text(widget) == label)


def _safe_text(widget):
    try:
        return widget.cget("text")
    except Exception:
        return None


def _run(monkeypatch, records, config, steps, tmp_path=None):
    """Open the real dialog, run `steps(dialog, root)` inside its loop and return (outcome, observations)."""
    seen = {}

    def mainloop(self):
        dialog = self.report_callback_exception.__self__
        self.update()
        steps(dialog, self, seen)
        try:
            still_open = bool(self.winfo_exists())
        except tk.TclError:
            still_open = False  # Start or Cancel closed the window
        if still_open:
            dialog.cancel()
    monkeypatch.setattr(tk.Tk, "mainloop", mainloop)
    path = str((tmp_path or Path("/nonexistent")) / "cases.json")
    return gl.run_case_manager(records, config, PERIOD, path, "operator", "test period"), seen


def _select_case(dialog, root, case_id):
    dialog.case_tree.selection_set(case_id)
    root.update()


def _members(dialog):
    return [dialog.member_tree.item(item, "values")[0] for item in dialog.member_tree.get_children()]


@pytest.fixture
def records():
    try:
        tk.Tk().destroy()
    except Exception:
        pytest.skip("Tk cannot open a window here")
    names = ["FS1", "FS2", "FS3", "FS4"]
    return [{"key": "P\\{}".format(name), "id": name, "name": name, "window": (i * 24 * HOUR, (i + 3) * 24 * HOUR),
             "component_keys": ["P\\L{}".format(i)], "equipment_name": "Line L{}0".format(i), "start_time": "", "end_time": "",
             "priority": 1, "originally_ignored": False} for i, name in enumerate(names)]


@pytest.fixture
def config(records):
    data = gl.empty_case_config()
    data["cases"] = [{"id": "A", "name": "Summer", "outages": [records[0]["key"], records[1]["key"]]},
                     {"id": "B", "name": "North-east", "outages": [records[2]["key"]]}]
    return data


def test_gui_01_to_03_clicking_a_case_shows_its_outages_at_once(monkeypatch, records, config):
    def steps(dialog, root, seen):
        seen["first"] = _members(dialog)
        _select_case(dialog, root, "B")
        seen["b"] = _members(dialog)
        seen["title"] = dialog.case_title.cget("text")
        _select_case(dialog, root, "A")
        seen["a"] = _members(dialog)

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["first"] == ["FS1", "FS2"]
    assert seen["b"] == ["FS3"] and seen["title"] == "North-east"
    assert seen["a"] == ["FS1", "FS2"]


def test_gui_04_and_05_add_and_remove_update_the_table_immediately(monkeypatch, records, config):
    def steps(dialog, root, seen):
        dialog.available_tree.selection_set(records[2]["key"])
        _button(root, "Add to case").invoke()
        seen["added"] = _members(dialog)
        seen["mark"] = dialog.available_tree.item(records[2]["key"], "values")[0]
        dialog.member_tree.selection_set(records[0]["key"])
        _button(root, "Remove from case").invoke()
        seen["removed"] = _members(dialog)
        seen["case_count"] = dialog.case_tree.item("A", "values")[1]
        dialog.start()

    outcome, seen = _run(monkeypatch, records, config, steps)

    assert seen["added"] == ["FS1", "FS2", "FS3"] and seen["mark"] == gl.MARK_IN_CASE
    assert seen["removed"] == ["FS2", "FS3"] and seen["case_count"] == "2"
    assert outcome["cases"][0]["outages"] == [records[1]["key"], records[2]["key"]]
    assert config["cases"][0]["outages"] == [records[0]["key"], records[1]["key"]], "the input stays untouched"


def _shown(table, column=1):
    return [table.tree.item(item, "values")[column] for item in table.tree.get_children()]


def test_gui_11_every_table_filters_per_column_and_clears(monkeypatch, records, config):
    def steps(dialog, root, seen):
        table = dialog.available_table
        table.values[2].set("l30")
        table.render()
        seen["equipment"] = _shown(table)
        table.clear_filters()
        table.values[0].set("in case")
        table.render()
        seen["assigned"] = _shown(table)
        seen["count"] = table.count.cget("text")
        table.values[0].set("free")
        table.render()
        seen["free"] = _shown(table)
        table.clear_filters()
        seen["all"] = len(table.tree.get_children())
        cases = dialog.case_table
        cases.values[0].set("north")
        cases.render()
        seen["cases"] = list(cases.tree.get_children())

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["equipment"] == ["FS4"]
    assert seen["assigned"] == ["FS1", "FS2"] and seen["count"] == "2 of 4 shown"
    assert seen["free"] == ["FS3", "FS4"]
    assert seen["all"] == 4
    assert seen["cases"] == ["B"]


def test_filters_stand_exactly_under_their_columns(monkeypatch, records, config):
    def steps(dialog, root, seen):
        root.update()
        for tab, name in ((0, "case_table"), (0, "member_table"), (0, "available_table"), (1, "fixed_table"),
                          (1, "rule_table"), (2, "problem_table")):
            dialog.notebook.select(tab)  # a table on a hidden tab is laid out when its tab is shown
            root.update()
            table = getattr(dialog, name)
            table.layout()
            root.update()
            widths = [table.tree.column(column[0], "width") for column in table.columns]
            starts = [sum(widths[:index]) for index in range(len(widths))]
            seen[name] = ([label.winfo_x() for label in table.labels] == starts,
                          [widget.winfo_x() - 2 for widget in table.inputs] == starts)

    _, seen = _run(monkeypatch, records, config, steps)

    assert all(value == (True, True) for value in seen.values()), seen


def test_header_click_sorts_and_shows_the_direction(monkeypatch, records, config):
    def steps(dialog, root, seen):
        table = dialog.available_table
        table.labels[1].event_generate("<Button-1>")
        root.update()
        seen["ascending"] = _shown(table)
        table.toggle_sort(1)
        seen["descending"] = _shown(table)
        seen["label"] = table.labels[1].cget("text")

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["ascending"] == ["FS1", "FS2", "FS3", "FS4"]
    assert seen["descending"] == ["FS4", "FS3", "FS2", "FS1"]
    assert seen["label"] == "Planned outage \u25bc"


def test_tabs_status_line_and_problem_list(monkeypatch, records, config):
    config["cases"].append({"id": "C", "name": "Empty", "outages": []})

    def steps(dialog, root, seen):
        seen["tabs"] = [dialog.notebook.tab(tab, "text") for tab in dialog.notebook.tabs()]
        seen["status"] = dialog.status_line.cget("text")
        seen["problems"] = [dialog.problem_table.tree.item(item, "values") for item in dialog.problem_table.tree.get_children()]
        dialog.status_line.event_generate("<Button-1>")
        root.update()
        seen["selected_tab"] = dialog.notebook.tab(dialog.notebook.select(), "text")

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["tabs"] == ["Workspace", "Fixed background & rules", "Review & start (1)"]
    assert "2 of 3 cases ready" in seen["status"] and "1 problem or warning" in seen["status"]
    assert seen["problems"] == [("Empty", "Not calculated: no planned outage is assigned.")]
    assert seen["selected_tab"] == "Review & start (1)"


def test_fixed_outages_and_rules_live_on_their_own_tab(monkeypatch, records, config):
    def steps(dialog, root, seen):
        dialog.available_tree.selection_set(records[3]["key"])
        _button(root, "Set as fixed background").invoke()
        seen["fixed"] = _shown(dialog.fixed_table, 0)
        seen["mark"] = dialog.available_tree.item(records[3]["key"], "values")[0]
        dialog.rule_first.set("FS1")
        dialog.rule_kind.set("must not overlap")
        dialog.rule_second.set("FS2")
        _button(root, "Add rule").invoke()
        seen["rules"] = [dialog.rule_tree.item(item, "values") for item in dialog.rule_tree.get_children()]
        seen["status_A"] = dialog.case_tree.item("A", "values")[2]

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["fixed"] == ["FS4"] and seen["mark"] == gl.MARK_FIXED
    assert seen["rules"] == [("FS1", "must not overlap", "FS2")]
    assert seen["status_A"] == "not calculated", "case A breaks the new rule"


def test_gui_13_timeline_draws_every_outage_of_the_case(monkeypatch, records, config):
    def steps(dialog, root, seen):
        root.update()
        dialog.draw_timeline()
        canvas = dialog.canvas
        seen["bars"] = [item for item in canvas.find_all() if canvas.type(item) == "rectangle"]
        seen["labels"] = [canvas.itemcget(item, "text") for item in canvas.find_all() if canvas.type(item) == "text"]

    _, seen = _run(monkeypatch, records, config, steps)

    assert "FS1" in seen["labels"] and "FS2" in seen["labels"]
    assert len(seen["bars"]) >= 3, "two bars and their overlap"


def test_gui_14_to_16_options_n1_disabled_period_shown_no_optimisation(monkeypatch, records, config):
    def steps(dialog, root, seen):
        seen["texts"] = _texts(root)
        seen["n1_state"] = str(_button(root, "n-1 - contingency analysis").cget("state"))
        dialog.n0_var.set(False)
        dialog.apply_assessments = lambda: None  # no message box in the test
        seen["n0"] = dialog.n0_var.get()

    _, seen = _run(monkeypatch, records, config, steps)

    assert "QDS: test period" in seen["texts"]
    assert seen["n1_state"] == "disabled"
    assert not any("ptimi" in text or "onservative" in text for text in seen["texts"])
    assert "n-0 - quasi-dynamic simulation (QDS)" in seen["texts"]


def test_gui_17_cancel_returns_nothing(monkeypatch, records, config):
    outcome, _ = _run(monkeypatch, records, config, lambda dialog, root, seen: _button(root, "Cancel").invoke())

    assert outcome is None


def test_gui_18_and_19_start_hands_over_the_configuration_and_opens_nothing_else(monkeypatch, records, config):
    def steps(dialog, root, seen):
        _button(root, "Start calculation").invoke()
        seen["closed"] = True

    outcome, _ = _run(monkeypatch, records, config, steps)

    assert outcome["assessments"] == ["n-0"] and outcome["mode"] == "conservative"
    assert [case["id"] for case in outcome["cases"]] == ["A", "B"]


def test_gui_20_load_saved_configuration_replaces_the_cases(monkeypatch, records, config, tmp_path):
    saved = gl.empty_case_config()
    saved["cases"] = [{"id": "S", "name": "Saved", "outages": [records[3]["key"]]}]
    gl.save_case_config(str(tmp_path / "cases.json"), saved, "operator")
    monkeypatch.setattr(gl, "CaseManagerDialog", gl.CaseManagerDialog)

    def steps(dialog, root, seen):
        dialog.messagebox.askyesno = lambda *args, **kwargs: True
        _button(root, "Load saved configuration").invoke()
        seen["cases"] = dialog.case_tree.get_children()
        seen["members"] = _members(dialog)

    _, seen = _run(monkeypatch, records, config, steps, tmp_path)

    assert seen["cases"] == ("S",) and seen["members"] == ["FS4"]


def test_new_case_gets_a_standard_name_without_any_extra_window(monkeypatch, records, config):
    def steps(dialog, root, seen):
        windows = len(root.winfo_children())
        _button(root, "New").invoke()
        root.update()
        seen["selected"] = dialog.case_tree.selection()
        seen["row"] = dialog.case_tree.item("C1", "values")
        seen["new_windows"] = [child.winfo_class() for child in root.winfo_children()[windows:]]
        seen["editing"] = dialog.inline_edit
        seen["headings"] = [label.cget("text") for label in dialog.case_table.labels]
        seen["buttons"] = sorted(dialog.case_buttons)

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["selected"] == ("C1",) and seen["row"][0] == "Case 1"
    assert "Toplevel" not in seen["new_windows"] and seen["editing"] is None
    assert seen["headings"] == ["Planning case", "Outages", "Status"], "no ID column"
    assert seen["buttons"] == ["Copy", "Delete", "New"], "no Edit button"


def test_double_click_renames_a_case_in_place(monkeypatch, records, config):
    def steps(dialog, root, seen):
        tree = dialog.case_tree
        _select_case(dialog, root, "B")
        x, y, _, height = tree.bbox("B")
        dialog.on_case_double_click(type("Event", (), {"x": x + 5, "y": y + height // 2})())
        root.update()
        entry = dialog.inline_edit["entry"]
        seen["over_the_cell"] = (entry.winfo_parent() == str(tree), entry.get(), entry.winfo_y() == y)
        entry.delete(0, "end")
        entry.insert(0, "Winter")
        entry.event_generate("<Return>")
        root.update()
        seen["renamed"] = (tree.item("B", "values")[0], dialog.inline_edit, entry.winfo_exists())
        seen["still_open"] = root.winfo_exists()
        dialog.rename_in_place("B")
        dialog.inline_edit["entry"].delete(0, "end")
        dialog.inline_edit["entry"].event_generate("<Escape>")
        root.update()
        seen["escape"] = (tree.item("B", "values")[0], root.winfo_exists())
        dialog.rename_in_place("B")
        dialog.inline_edit["entry"].delete(0, "end")
        dialog.finish_editing()
        seen["empty"] = tree.item("B", "values")[0]

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["over_the_cell"] == (True, "North-east", True)
    assert seen["renamed"] == ("Winter", None, 0) and seen["still_open"]
    assert seen["escape"] == ("Winter", 1), "Escape cancels the edit, not the whole window"
    assert seen["empty"] == "Winter", "an empty name keeps the old one"


def test_double_click_on_the_description_edits_it_in_place(monkeypatch, records, config):
    def steps(dialog, root, seen):
        _select_case(dialog, root, "A")
        seen["placeholder"] = dialog.case_description.cget("text")
        dialog.describe_in_place()
        root.update()
        entry = dialog.inline_edit["entry"]
        entry.insert(0, "two lines in July")
        dialog.case_tree.focus_set()  # a click elsewhere applies
        root.update()
        seen["description"] = (dialog.editor.case("A")["description"], dialog.case_description.cget("text"))

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["placeholder"] == "(double-click to add a description)"
    assert seen["description"] == ("two lines in July", "two lines in July")



def test_ticking_the_box_adds_and_removes_an_outage(monkeypatch, records, config):
    def steps(dialog, root, seen):
        _select_case(dialog, root, "B")
        tree = dialog.available_tree
        key = records[3]["key"]
        tree.see(key)
        root.update()
        x, y, width, height = tree.bbox(key, "#1")
        click = lambda: (tree.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2), root.update())
        click()
        seen["after_tick"] = (_members(dialog), tree.item(key, "values")[0])
        root.after(600, lambda: None)
        time.sleep(0.6)  # a second, separate click; a quick one counts as a double-click
        root.update()
        click()
        seen["after_untick"] = (_members(dialog), tree.item(key, "values")[0])
        event = type("Event", (), {"x": x + width // 2, "y": y + height // 2})()
        dialog.on_available_double_click(event)  # a quick second click on the box ticks too
        root.update()
        seen["double_on_box"] = (_members(dialog), dialog.root.winfo_children()[-1].winfo_class())
        name_x = x + width + 20
        tree.event_generate("<Button-1>", x=name_x, y=y + height // 2)
        root.update()
        seen["plain_click"] = _members(dialog)

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["after_tick"] == (["FS3", "FS4"], gl.MARK_IN_CASE)
    assert seen["after_untick"] == (["FS3"], gl.MARK_FREE)
    assert seen["double_on_box"] == (["FS3", "FS4"], seen["double_on_box"][1]) and seen["double_on_box"][1] != "Toplevel"
    assert seen["plain_click"] == ["FS3", "FS4"], "a click on the name only selects the row"


def test_new_and_copy_stop_at_five_cases(monkeypatch, records, config):
    infos = []

    def steps(dialog, root, seen):
        dialog.messagebox.showinfo = lambda title, text, **_kw: infos.append(text)
        for _ in range(3):
            _button(root, "New").invoke()
        seen["counter"] = dialog.case_limit_label.cget("text")
        seen["new_locked"] = (_button(root, "New").instate(["disabled"]), _button(root, "Copy").instate(["disabled"]))
        dialog.new_case()
        seen["cases"] = len(dialog.case_tree.get_children())

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["counter"] == "5 of 5 cases"
    assert seen["new_locked"] == (True, True)
    assert seen["cases"] == 5 and infos and "At most 5" in infos[0]


def test_refreshes_reuse_widgets_and_render_once(monkeypatch, records, config):
    def steps(dialog, root, seen):
        before = [str(label) for pair in dialog._preview_labels for label in pair]
        dialog.case_tree.selection_set("B")
        root.update()
        seen["same_labels"] = before == [str(label) for pair in dialog._preview_labels for label in pair]
        table = dialog.available_table
        renders = []
        original = table.render
        table.render = lambda: (renders.append(1), original())
        table.values[1].set("FS")  # typing schedules a render
        table.clear_filters()      # renders at once
        seen["pending"] = table._pending
        time.sleep(0.2)  # longer than the 120 ms pause of a typed filter
        root.update()
        seen["renders"] = len(renders)
        dialog.case_table.values[0].set("Summer")
        dialog.case_table.render()
        dialog.messagebox.askyesno = lambda *_args, **_kw: True
        dialog.one_case_per_outage()
        seen["case_filter"] = dialog.case_table.values[0].get()
        seen["shown"] = len(dialog.case_tree.get_children())

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["same_labels"], "the preview updates its labels instead of rebuilding them"
    assert seen["pending"] is None and seen["renders"] == 1
    assert seen["case_filter"] == "" and seen["shown"] == len(records)


def test_workspace_runs_available_outages_then_case_outages_then_cases(monkeypatch, records, config):
    def steps(dialog, root, seen):
        root.update()
        panes = [str(pane) for pane in dialog.panes.panes()]
        owner = lambda widget: next(index for index, pane in enumerate(panes) if str(widget).startswith(pane + "."))
        seen["order"] = [owner(dialog.available_tree), owner(dialog.member_tree), owner(dialog.case_tree)]
        seen["x"] = [tree.winfo_rootx() for tree in (dialog.available_tree, dialog.member_tree, dialog.case_tree)]
        seen["cases_share"] = dialog.case_tree.winfo_width() / max(dialog.panes.winfo_width(), 1)

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["order"] == [0, 1, 2]
    assert seen["x"] == sorted(seen["x"])
    assert seen["cases_share"] < 0.3


def test_hover_explains_the_relations_and_the_controls(monkeypatch, records, config):
    def steps(dialog, root, seen):
        seen["relations"] = {name: dialog.tip_text(dialog.relation_labels[name]) for name in dialog.relation_labels}
        seen["lists"] = {name: dialog.tip_text(box) for name, box in dialog._relation_lists.items()}
        seen["labels"] = [label.cget("text") for label in dialog.relation_labels.values()]
        seen["buttons"] = {label: dialog.tip_text(_button(root, label))
                           for label in ("New", "Copy", "Delete", "Add to case", "Set as fixed background",
                                         "Remove from case", "Start calculation", "Cancel")}
        status = dialog.case_table.labels[2]
        seen["status_header"] = dialog.tip_text(status)
        seen["filter"] = dialog.tip_text(dialog.member_table.inputs[0])
        tooltip = next(tip for tip in dialog.tooltips if tip.widget is dialog.relation_labels["requires"])
        tooltip.show()
        root.update()
        seen["shown"] = tooltip.window is not None and tooltip.window.winfo_ismapped()
        seen["shown_text"] = [_safe_text(child) for child in tooltip.window.winfo_children()]
        tooltip.hide()
        entry = dialog.member_table.inputs[0]
        hint = next(tip for tip in dialog.tooltips if tip.widget is entry)
        entry.focus_force()
        hint.show()
        root.update()
        entry.event_generate("<KeyPress>", keysym="a")
        root.update()
        seen["hidden"] = (tooltip.window is None and hint.window is None, "typing into a filter closes its hint")

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["labels"] == [label + " ⓘ" for _, label in gl.RELATION_LABELS]
    for name in ("includes", "requires", "alternatives"):
        assert seen["relations"][name] == seen["lists"][name] == gl.HELP_TEXTS[name]
    assert "joint plan" in seen["relations"]["includes"] and "one QDS run" in seen["relations"]["includes"]
    assert "NOT EVALUATED" in seen["relations"]["requires"] and "Also contains" in seen["relations"]["requires"]
    assert "either - or" in seen["relations"]["alternatives"] and "both ways" in seen["relations"]["alternatives"]
    assert all(seen["buttons"].values()), seen["buttons"]
    assert "excluded" in seen["status_header"] and "sort" in seen["status_header"]
    assert "contains this text" in seen["filter"]
    assert seen["shown"] and seen["shown_text"] == [gl.HELP_TEXTS["requires"]]
    assert seen["hidden"][0], seen["hidden"][1]


def test_a_dialog_that_cannot_be_built_counts_as_unavailable(monkeypatch, records):
    from tkinter import ttk

    def broken(*_args, **_kwargs):
        raise RuntimeError("theme missing")
    monkeypatch.setattr(ttk, "Treeview", broken)

    with pytest.raises(gl.CaseManagerUnavailable, match="theme missing"):
        gl.run_case_manager(records, gl.empty_case_config(), PERIOD, "unused.json")


def test_errors_in_buttons_are_shown_not_swallowed(monkeypatch, records):
    from tkinter import messagebox
    shown = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, text, **_kw: shown.append(text))

    def steps(dialog, root, seen):
        root.report_callback_exception(ValueError, ValueError("bad input"), None)

    outcome, _ = _run(monkeypatch, records, gl.empty_case_config(), steps)

    assert outcome is None
    assert shown == ["ValueError: bad input"]
