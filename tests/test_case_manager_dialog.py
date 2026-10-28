"""The case manager window with real Tk: what a click does (skipped without Tk or a display).

gui_NN refers to the functional checks 1-20 of the GUI specification; the
editing rules behind each click are tested without a window in test_planner.py.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest
from _paths import delivered

pytestmark = pytest.mark.gui

tk = pytest.importorskip("tkinter")

SPEC = importlib.util.spec_from_file_location("gridlens_dialog", delivered("main.py"))
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


def _assert_inside(root, widgets):
    for widget in widgets:
        x = widget.winfo_rootx() - root.winfo_rootx()
        y = widget.winfo_rooty() - root.winfo_rooty()
        assert 0 <= x and x + widget.winfo_width() <= root.winfo_width(), (str(widget), x, widget.winfo_width())
        assert 0 <= y and y + widget.winfo_height() <= root.winfo_height(), (str(widget), y, widget.winfo_height())


def _focus(root, widget):
    """Wait for native window activation before injecting a keyboard event."""
    root.lift()
    widget.focus_force()
    deadline = time.monotonic() + 1.0
    root.update()
    while root.focus_get() is not widget and time.monotonic() < deadline:
        root.after(10)
        root.update()
    assert root.focus_get() is widget


def _run(monkeypatch, records, config, steps, tmp_path=None):
    """Open the real dialog, run `steps(dialog, root)` inside its loop and return (outcome, observations)."""
    seen = {}

    def mainloop(self):
        dialog = self.report_callback_exception.__self__
        self.update()
        _focus(self, self)
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
        seen["case_count"] = dialog.case_tree.item("A", "values")[2]
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
        cases.values[1].set("north")
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
                          (1, "rule_table"), (0, "problem_table")):
            dialog.notebook.select(tab)  # a table on a hidden tab is laid out when its tab is shown
            if tab == 1:
                dialog.settings_book.select(dialog.fixed_page)
            root.update()
            table = getattr(dialog, name)
            table.layout()
            root.update()
            widths = [table.tree.column(column[0], "width") for column in table.columns]
            offset = table.tree.column('#0', 'width') if 'tree' in table.tree.cget('show') else 0
            starts = [offset + sum(widths[:index]) for index in range(len(widths))]
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

    assert seen["tabs"] == ["Case Manager (1)", "Settings"], "exactly two main tabs, no results tab"
    assert "2 of 3 cases ready" in seen["status"] and "1 problem or warning" in seen["status"]
    assert "default settings" in seen["status"]
    assert seen["problems"] == [("Empty", "Not calculated: no planned outage is assigned.")]
    assert seen["selected_tab"] == "Case Manager (1)"


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
        seen["status_A"] = dialog.case_tree.item("A", "values")[3]

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["fixed"] == ["FS4"] and seen["mark"] == gl.MARK_FIXED
    assert seen["rules"] == [("FS1", "must not overlap", "FS2")]
    assert seen["status_A"] == "not calculated", "case A breaks the new rule"


def test_fixed_tab_explains_shared_outages_rules_and_optional_use_without_hover(monkeypatch, records, config):
    def steps(dialog, root, seen):
        dialog.notebook.select(1)
        dialog.settings_book.select(dialog.fixed_page)
        root.update()
        seen["visible"] = [_safe_text(widget) for widget in _widgets(root) if widget.winfo_ismapped()]
        dialog.notebook.select(0)
        root.update()
        seen["case_help"] = [_safe_text(widget) for widget in _widgets(root) if widget.winfo_ismapped()]

    _, seen = _run(monkeypatch, records, config, steps)

    text = "\n".join(value for value in seen["visible"] if isinstance(value, str))
    assert "leave both sections empty" in text
    assert "reference and every case" in text and "own time window" in text
    assert "Reference: T1" in text and "Case A: T1 + line North" in text and "Case B: T1 + line South" in text
    assert "reported but not calculated" in text and "never create cases or change outage dates" in text
    assert "must not overlap: their time windows must not overlap" in text
    assert "second starts after the first ends" in text
    assert "both belong to the case and their windows overlap" in text
    assert any("Excluded cases stay saved" in str(text) for text in seen["case_help"])


@pytest.mark.parametrize("size", [(1000, 620), (1280, 800)])
def test_explanations_and_rule_controls_fit_the_window(monkeypatch, records, config, size):
    def steps(dialog, root, seen):
        root.geometry('{}x{}'.format(*size))
        dialog.notebook.select(1)
        dialog.settings_book.select(dialog.fixed_page)
        root.update()
        widgets = [dialog.rule_first, dialog.rule_kind, dialog.rule_second,
                   _button(root, 'Add rule'), _button(root, 'Remove rule'),
                   _button(root, 'Remove from fixed background'), _button(root, 'Start calculation'), dialog.status_line]
        widgets += [widget for widget in _widgets(root) if widget.winfo_class() == 'TLabel' and widget.winfo_ismapped() and
                    _safe_text(widget) and str(widget.cget('style')) in ('Inset.TLabel', 'InsetTitle.TLabel')]
        # The settings page scrolls when its natural height exceeds the viewport.
        # Every control must be reachable without compressing the result tables.
        seen['bounds'] = []
        for widget in widgets:
            content = widget
            while content is not root and not hasattr(content, '_viewport'):
                content = content.master
            if content is not root:
                viewport = content._viewport
                y = widget.winfo_rooty() - content.winfo_rooty()
                viewport.yview_moveto(max(0, y) / max(1, content.winfo_height()))
                root.update()
            seen['bounds'].append((str(widget), widget.winfo_rootx() - root.winfo_rootx(),
                                   widget.winfo_rooty() - root.winfo_rooty(), widget.winfo_width(), widget.winfo_height()))
        seen['labels_fit'] = all(widget.winfo_height() >= widget.winfo_reqheight() for widget in widgets
                                if widget.winfo_class() == 'TLabel')
        seen['window'] = (root.winfo_width(), root.winfo_height())
        seen['table_height'] = dialog.rule_tree.winfo_height()
        dialog.notebook.select(0)
        dialog.toggle_preview(True)
        root.update()
        seen['preview_bounds'] = (dialog.case_preview.winfo_rooty() - root.winfo_rooty(),
                                  dialog.case_preview.winfo_height())

    _, seen = _run(monkeypatch, records, config, steps)

    width, height = seen['window']
    assert all(0 <= x and 0 <= y and x + w <= width and y + h <= height
               for _, x, y, w, h in seen['bounds']), seen
    assert seen['labels_fit'], seen
    assert seen['table_height'] >= 26, seen
    top, preview_height = seen['preview_bounds']
    assert top >= 0 and preview_height >= 26 and top + preview_height <= height, seen


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
    assert not any(character.isdigit() for label in seen["labels"] if label not in ("FS1", "FS2", "FS3", "FS4")
                   for character in label), "no dates and no numbers on the timeline"
    assert all(label in ("FS1", "FS2", "FS3", "FS4") for label in seen["labels"]), seen["labels"]


def test_gui_14_to_16_only_n1_options_period_shown_no_optimisation(monkeypatch, records, config):
    def steps(dialog, root, seen):
        seen["texts"] = _texts(root)
        n1 = _button(root, "n-1 - reference contingency analysis")
        prime = _button(root, "(n-1)' - contingency analysis with planned-outage scenarios")
        seen["states"] = (str(n1.cget("state")), str(prime.cget("state")))
        seen["tips"] = (dialog.tip_text(n1), dialog.tip_text(prime))

    _, seen = _run(monkeypatch, records, config, steps)

    assert "QDS: test period" in seen["texts"]
    assert seen["states"] == ("normal", "normal")
    assert all(gl.N1_NOTE in tip for tip in seen["tips"][:2]) and "Needs n-1" in seen["tips"][1]
    assert not any("ptimi" in text or "onservative" in text for text in seen["texts"])
    assert "n-0 - reference QDS" not in seen["texts"], "n-0 is always calculated: no control"


def test_gui_17_cancel_returns_nothing(monkeypatch, records, config):
    outcome, _ = _run(monkeypatch, records, config, lambda dialog, root, seen: _button(root, "Cancel").invoke())

    assert outcome is None


def test_gui_18_and_19_start_hands_over_the_configuration_and_opens_nothing_else(monkeypatch, records, config):
    def steps(dialog, root, seen):
        _button(root, "Start calculation").invoke()
        seen["closed"] = True

    outcome, _ = _run(monkeypatch, records, config, steps)

    assert outcome["assessments"] == ["n-0"] and "mode" not in outcome and outcome["settings"] == {}
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

    assert seen["selected"] == ("C1",) and seen["row"][1] == "Case 1"
    assert "Toplevel" not in seen["new_windows"] and seen["editing"] is None
    assert seen["headings"] == ["Run", "Planning case", "Outages", "Status"], "no ID column"
    assert seen["buttons"] == ["Copy", "Delete", "New"], "no Edit button"


def test_double_click_renames_a_case_in_place(monkeypatch, records, config):
    def steps(dialog, root, seen):
        tree = dialog.case_tree
        _select_case(dialog, root, "B")
        x, y, _, height = tree.bbox("B", "name")
        dialog.on_case_double_click(type("Event", (), {"x": x + 5, "y": y + height // 2})())
        root.update()
        entry = dialog.inline_edit["entry"]
        seen["over_the_cell"] = (entry.winfo_parent() == str(tree), entry.get(), entry.winfo_y() == y)
        entry.delete(0, "end")
        entry.insert(0, "Winter")
        _focus(root, entry)
        entry.event_generate("<Return>")
        root.update()
        seen["renamed"] = (tree.item("B", "values")[1], dialog.inline_edit, entry.winfo_exists())
        seen["still_open"] = root.winfo_exists()
        dialog.rename_in_place("B")
        dialog.inline_edit["entry"].delete(0, "end")
        _focus(root, dialog.inline_edit['entry'])
        dialog.inline_edit["entry"].event_generate("<Escape>")
        root.update()
        seen["escape"] = (tree.item("B", "values")[1], root.winfo_exists())
        dialog.rename_in_place("B")
        dialog.inline_edit["entry"].delete(0, "end")
        dialog.finish_editing()
        seen["empty"] = tree.item("B", "values")[1]

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
        dialog.case_table.values[1].set("Summer")
        dialog.case_table.render()
        dialog.messagebox.askyesno = lambda *_args, **_kw: True
        dialog.one_case_per_outage()
        seen["case_filter"] = dialog.case_table.values[1].get()
        seen["shown"] = len(dialog.case_tree.get_children())

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["same_labels"], "the preview updates its labels instead of rebuilding them"
    assert seen["pending"] is None and seen["renders"] == 1
    assert seen["case_filter"] == "" and seen["shown"] == len(records)


def test_large_outage_table_updates_one_checkbox_without_rebuilding_or_scrolling(monkeypatch, records, config):
    many = records + [dict(records[3], key="P\\Extra{}".format(i), id="Extra{}".format(i),
                           name="Extra{}".format(i)) for i in range(1000)]

    def steps(dialog, root, seen):
        tree = dialog.available_tree
        key = many[504]["key"]
        tree.selection_set(key)
        tree.see(key)
        root.update()
        scroll = tree.yview()
        operations = {"insert": 0, "delete": 0, "item": 0}
        for name in operations:
            original = getattr(tree, name)

            def counted(*args, name=name, original=original, **kwargs):
                if name != "item" or kwargs:
                    operations[name] += 1
                return original(*args, **kwargs)
            monkeypatch.setattr(tree, name, counted)

        dialog.toggle_outage(key)
        root.update()
        seen["operations"] = dict(operations)
        seen["scroll"] = (scroll, tree.yview())
        seen["selection"] = tree.selection()
        seen["mark"] = tree.item(key, "values")[0]
        _select_case(dialog, root, "B")
        seen["switch_operations"] = dict(operations)
        seen["switched_mark"] = tree.item(key, "values")[0]

    _, seen = _run(monkeypatch, many, config, steps)

    assert seen["operations"] == {"insert": 0, "delete": 0, "item": 1}
    assert seen["scroll"][1] == pytest.approx(seen["scroll"][0])
    assert seen["selection"] == (many[504]["key"],)
    assert seen["mark"] == gl.MARK_IN_CASE and seen["switched_mark"] == gl.MARK_FREE
    assert seen["switch_operations"]["insert"] == seen["switch_operations"]["delete"] == 0


def test_filtered_rows_reattach_with_current_values_and_removed_rows_stay_gone(monkeypatch, records, config):
    def steps(dialog, root, seen):
        table, tree = dialog.available_table, dialog.available_tree
        key = records[3]["key"]
        tree.selection_set(key)
        tree.focus(key)
        table.toggle_sort(1)
        table.values[0].set("in case")
        table.render()
        seen["filtered"] = tree.get_children()
        seen["selection"] = tree.selection()
        seen["focus"] = tree.focus()
        dialog.toggle_outage(key)
        seen["added"] = tree.get_children()
        seen["mark"] = tree.item(key, "values")[0]
        dialog.toggle_outage(key)
        seen["hidden_again"] = key not in tree.get_children()
        table.clear_filters()
        seen["restored"] = (len(tree.get_children()), tree.item(key, "values")[0])
        table.values[0].set("in case")
        table.render()
        table.set_rows([row for row in table.rows if row[0] != key])
        table.clear_filters()
        seen["deleted"] = (tree.exists(key), key in tree.get_children())
        seen["sorted"] = [tree.item(item, "values")[1] for item in tree.get_children()]

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["filtered"] == (records[0]["key"], records[1]["key"])
    assert seen["selection"] == ()
    assert seen["focus"] == "", "keyboard actions must not target a filtered-out row"
    assert seen["added"] == (records[0]["key"], records[1]["key"], records[3]["key"])
    assert seen["mark"] == gl.MARK_IN_CASE and seen["hidden_again"]
    assert seen["restored"] == (len(records), gl.MARK_FREE)
    assert seen["deleted"] == (False, False)
    assert seen["sorted"] == sorted(seen["sorted"])


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


def test_hover_explains_the_controls_without_case_relations(monkeypatch, records, config):
    def steps(dialog, root, seen):
        seen["texts"] = _texts(root)
        seen["buttons"] = {label: dialog.tip_text(_button(root, label))
                           for label in ("New", "Copy", "Delete", "Add to case", "Set as fixed background",
                                         "Remove from case", "Start calculation", "Cancel")}
        status = dialog.case_table.labels[3]
        seen["status_header"] = dialog.tip_text(status)
        seen["filter"] = dialog.tip_text(dialog.member_table.inputs[0])
        tooltip = next(tip for tip in dialog.tooltips if tip.widget is _button(root, "Copy"))
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

    assert not any(label in text for text in seen["texts"]
                   for label in ("Relations to other cases", "Also contains", "Only valid with", "Alternative to"))
    assert all(seen["buttons"].values()), seen["buttons"]
    assert "excluded" in seen["status_header"] and "sort" in seen["status_header"]
    assert "contains this text" in seen["filter"]
    assert seen["shown"] and seen["shown_text"] == [gl.HELP_TEXTS["Copy"]]
    assert seen["hidden"][0], seen["hidden"][1]


def test_keyboard_deletes_and_shortcuts(monkeypatch, records, config, tmp_path):
    def steps(dialog, root, seen):
        dialog.messagebox.askyesno = lambda *_args, **_kw: True
        dialog.messagebox.showinfo = lambda *_args, **_kw: None
        press = lambda widget, key: (_focus(root, widget), widget.event_generate(key), root.update())
        _select_case(dialog, root, "A")
        dialog.member_tree.selection_set(records[0]["key"])
        press(dialog.member_tree, "<Delete>")
        seen["removed"] = _members(dialog)
        dialog.case_tree.selection_set("B")
        root.update()
        press(dialog.case_tree, "<BackSpace>")
        seen["cases_after_delete"] = list(dialog.case_tree.get_children())
        press(dialog.case_tree, "<Control-n>")
        seen["cases_after_new"] = list(dialog.case_tree.get_children())
        press(dialog.available_tree, "<Control-a>")
        seen["all_selected"] = len(dialog.available_tree.selection()) == len(dialog.available_tree.get_children())
        press(dialog.case_tree, "<Control-f>")
        seen["search_focused"] = root.focus_get() is dialog.available_table.inputs[1]
        press(dialog.case_tree, "<Control-s>")
        seen["saved"] = (tmp_path / "cases.json").is_file()

    _, seen = _run(monkeypatch, records, config, steps, tmp_path)

    assert seen["removed"] == ["FS2"], "Delete removes the outage from the case"
    assert seen["cases_after_delete"] == ["A"], "BackSpace deletes the selected case after the question"
    assert len(seen["cases_after_new"]) == 2, "Ctrl+N creates a case"
    assert seen["all_selected"] and seen["search_focused"] and seen["saved"]
    assert all(len(entry) == 3 for entry in gl.KEYBOARD_SHORTCUTS)


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


def test_run_flags_toggle_the_clicked_case_and_update_the_settings_preview(monkeypatch, records, config):
    def steps(dialog, root, seen):
        tree = dialog.case_tree
        seen["initial"] = dialog.case_preview.get('1.0', 'end')
        x, y, width, height = tree.bbox('B', 'enabled')
        tree.event_generate('<Button-1>', x=x + width // 2, y=y + height // 2)
        root.update()
        seen["off"] = (dialog.editor.case('A').get('enabled', True), dialog.editor.case('B')['enabled'],
                       tree.item('B', 'values')[0], tree.item('B', 'values')[3])
        seen["preview_off"] = dialog.case_preview.get('1.0', 'end')
        seen["panel_removed"] = 'Selected case' not in _texts(root)
        tree.focus_force()
        tree.focus('B')
        tree.event_generate('<space>')
        root.update()
        seen["on"] = (dialog.editor.case('B')['enabled'], tree.item('B', 'values')[0])
        seen["preview_on"] = dialog.case_preview.get('1.0', 'end')
        seen["read_only"] = str(dialog.case_preview.cget('state'))
        seen["editing"] = dialog.inline_edit
        dialog.case_table.values[0].set('included')
        dialog.case_table.render()
        seen["filter_before"] = tree.get_children()
        dialog.toggle_case_enabled('B')
        seen["filter_after"] = tree.get_children()

    _, seen = _run(monkeypatch, records, config, steps)

    assert 'Summer (A)' in seen['initial'] and 'North-east (B)' in seen['initial']
    assert 'Assessment: n-0' in seen['initial'] and 'QDS period: test period' in seen['initial']
    assert 'FS1:' in seen['initial'] and 'FS3:' in seen['initial']
    assert seen['off'] == (True, False, '☐', 'excluded')
    assert 'North-east (B)' not in seen['preview_off']
    assert 'Excluded (Run flag off): North-east' in seen['preview_off']
    assert seen['on'] == (True, '☑') and 'North-east (B)' in seen['preview_on']
    assert seen['read_only'] == 'disabled' and seen['editing'] is None and seen['panel_removed']
    assert seen['filter_before'] == ('A', 'B') and seen['filter_after'] == ('A',)


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------
def test_settings_tab_shows_every_setting_with_source_and_hover_text(monkeypatch, records, config):
    config["settings"] = {"line_limit": 110.0}

    def steps(dialog, root, seen):
        dialog.notebook.select(dialog.settings_tab)
        root.update()
        seen["pages"] = [dialog.settings_book.tab(page, "text") for page in dialog.settings_book.tabs()]
        seen["keys"] = set(dialog.setting_vars)
        seen["line_limit"] = (dialog.setting_vars["line_limit"].get(), dialog.setting_sources["line_limit"].cget("text"))
        seen["warning"] = dialog.setting_sources["line_warning"].cget("text")
        seen["read_only"] = {key: dialog.setting_inputs[key].instate(["disabled"]) for key in dialog.setting_vars
                             if not gl.SETTINGS_BY_KEY[key]["editable"]}
        seen["tips"] = {key: dialog.tip_text(dialog.setting_inputs[key]) for key in dialog.setting_vars}
        seen["buttons"] = {label: dialog.tip_text(_button(root, label))
                           for label in ("Restore defaults", "Apply settings", "Save settings")}
        seen["texts"] = _texts(root)

    _, seen = _run(monkeypatch, records, config, steps)

    assert seen["pages"] == ["Network scope", "Limits", "Classification", "Report and run", "Contingency analysis",
                             "QDS time base", "Fixed background & rules"]
    assert seen["keys"] == {key for key, setting in gl.SETTINGS_BY_KEY.items() if setting["kind"] not in ("grids", "elements")}
    assert seen["line_limit"] == ("110", gl.SOURCE_USER) and seen["warning"] == gl.SOURCE_GRIDLENS
    assert seen["read_only"] and all(seen["read_only"].values()), "category B and post-fault fields are read only"
    assert all(len(text) > 40 for text in seen["tips"].values()), seen["tips"]
    assert all(seen["buttons"].values())
    assert any("not yet inside the PowerFactory project" in text for text in seen["texts"])
    assert "QDS start" in seen["texts"] and "Time definition" in seen["texts"]


def test_invalid_setting_is_marked_and_blocks_the_start(monkeypatch, records, config):
    def steps(dialog, root, seen):
        errors = []
        dialog.messagebox.showerror = lambda title, text, **_kw: errors.append(text)
        dialog.setting_vars["line_limit"].set("-5")
        root.update()
        seen["style"] = str(dialog.setting_inputs["line_limit"].cget("style"))
        seen["message"] = dialog.setting_messages["line_limit"].cget("text")
        seen["tab"] = dialog.notebook.tab(dialog.settings_tab, "text")
        _button(root, "Start calculation").invoke()
        seen["errors"] = list(errors)
        seen["open"] = bool(root.winfo_exists())
        seen["selected"] = dialog.notebook.tab(dialog.notebook.select(), "text")

    outcome, seen = _run(monkeypatch, records, config, steps)

    assert outcome is None, "no calculation with invalid settings"
    assert seen["style"] == "Invalid.TEntry" and "greater than 0" in seen["message"]
    assert seen["tab"] == "Settings (!)" and seen["selected"] == "Settings (!)"
    assert seen["errors"] and "greater than 0" in seen["errors"][0]


def test_apply_override_and_restore_defaults(monkeypatch, records, config):
    def steps(dialog, root, seen):
        dialog.setting_vars["transformer_limit"].set("120")
        root.update()
        seen["pending"] = dialog.setting_sources["transformer_limit"].cget("text")
        _button(root, "Apply settings").invoke()
        seen["applied"] = (dialog.editor.settings_overrides(), dialog.setting_sources["transformer_limit"].cget("text"))
        seen["status"] = dialog.status_line.cget("text")
        _button(root, "Restore defaults").invoke()
        seen["restored"] = (dialog.editor.settings_overrides(), dialog.setting_vars["transformer_limit"].get())
        dialog.setting_vars["line_warning"].set("85")
        root.update()
        _button(root, "Start calculation").invoke()  # applies the edited value first

    outcome, seen = _run(monkeypatch, records, config, steps)

    assert seen["pending"] == "edited, not applied"
    assert seen["applied"] == ({"transformer_limit": 120.0}, gl.SOURCE_USER)
    assert "1 settings override" in seen["status"]
    assert seen["restored"] == ({}, "100")
    assert outcome["settings"] == {"line_warning": 85.0}


def test_tooltip_appears_after_the_delay_and_goes_on_leave(monkeypatch, records, config):
    def steps(dialog, root, seen):
        widget = _button(root, "Start calculation")
        tip = next(tip for tip in dialog.tooltips if tip.widget is widget)
        seen["delay"] = tip.DELAY
        tip._schedule()
        root.update()
        seen["before"] = tip.window is None
        time.sleep(tip.DELAY / 1000.0 + 0.15)
        root.update()
        seen["shown"] = tip.window is not None
        widget.event_generate("<Leave>")
        root.update()
        seen["gone"] = tip.window is None
        seen["text"] = tip.text

    _, seen = _run(monkeypatch, records, config, steps)

    assert 400 <= seen["delay"] <= 600
    assert seen["before"] and seen["shown"] and seen["gone"]
    assert "separate step" in seen["text"], "the start tooltip does not promise an automatic PDF"


def test_network_scope_lists_the_grids_of_the_model_for_selection(monkeypatch, records, config):
    grids = [("Grid A", True), ("Grid B", True), ("Grid C", False)]
    contingencies = {"command": "Contingency Analysis", "contingencies": [
        {"name": "Line A1", "number": 1, "analysed": True, "elements": ["Line A1"], "grids": ["Grid A"]},
        {"name": "Line B1", "number": 2, "analysed": True, "elements": ["Line B1"], "grids": ["Grid B"]}]}
    seen = {}

    def mainloop(self):
        dialog = self.report_callback_exception.__self__
        self.update()
        dialog.notebook.select(dialog.settings_tab)
        self.update()
        boxes = dialog.grid_lists
        seen["listed"] = list(boxes["monitoring_grids"].get(0, "end"))
        seen["contingency_state"] = str(boxes["contingency_grids"].cget("state"))
        boxes["monitoring_grids"].selection_set(0)
        boxes["monitoring_grids"].event_generate("<<ListboxSelect>>")
        self.update()
        seen["monitoring"] = dialog.editor.selected_grids("monitoring_grids")
        seen["follows"] = list(boxes["contingency_grids"].curselection())
        seen["preview"] = dialog.contingency_note.cget("text")
        dialog.contingency_mode.set("own")
        dialog.on_contingency_mode()
        boxes["contingency_grids"].selection_clear(0, "end")
        boxes["contingency_grids"].selection_set(1)
        boxes["contingency_grids"].event_generate("<<ListboxSelect>>")
        self.update()
        seen["own"] = dialog.editor.selected_grids("contingency_grids")
        seen["own_preview"] = dialog.contingency_note.cget("text")
        seen["tips"] = [dialog.tip_text(box) for box in boxes.values()]
        seen["problems"] = [dialog.problem_table.tree.item(item, "values") for item in dialog.problem_table.tree.get_children()]
        _button(self, "Start calculation").invoke()

    monkeypatch.setattr(tk.Tk, "mainloop", mainloop)
    outcome = gl.run_case_manager(records, config, PERIOD, "/nonexistent/cases.json", "operator", "test period",
                                  grids=grids, contingencies=contingencies)

    assert seen["listed"] == ["Grid A", "Grid B", "Grid C  (inactive)"], "every grid of the model is offered"
    assert seen["contingency_state"] == "disabled", "every grid by default: no n-1 grid filter"
    # The report filter does not select contingencies.
    assert seen["monitoring"] == ("Grid A",) and seen["follows"] == []
    assert seen["preview"].startswith("2 of 2 contingencies") and "Applied to the n-1 run" in seen["preview"]
    assert seen["own"] == ("Grid B",) and seen["own_preview"].startswith("1 of 2 contingencies")
    assert all("grid" in tip for tip in seen["tips"])
    assert not seen["problems"]
    assert outcome["settings"] == {"monitoring_grids": ("Grid A",), "contingency_grids": ("Grid B",)}


def test_grid_search_preserves_hidden_selections_and_saved_grid_names(monkeypatch, records, config):
    def mainloop(root):
        dialog = root.report_callback_exception.__self__
        root.update()
        dialog.select_grids('monitoring_grids', True)
        dialog.grid_search['monitoring_grids'].set('north')
        root.update()
        box = dialog.grid_lists['monitoring_grids']
        assert list(box.get(0, 'end')) == ['North']
        box.selection_clear(0, 'end')
        dialog.on_grid_select('monitoring_grids')
        assert set(dialog.editor.selected_grids('monitoring_grids')) == {'East', 'South'}
        dialog.grid_search['monitoring_grids'].set('not found')
        root.update()
        assert dialog.grid_empty['monitoring_grids'][0].cget('text') == 'No matching grids'
        assert set(dialog.editor.selected_grids('monitoring_grids')) == {'East', 'South'}
        dialog.grid_search['monitoring_grids'].set('')
        root.update()
        assert list(box.curselection()) == [0, 2]
        assert list(dialog.grid_lists['contingency_grids'].curselection()) == [], 'independent of the report filter'
        dialog.start()
    monkeypatch.setattr(tk.Tk, 'mainloop', mainloop)
    outcome = gl.run_case_manager(records, config, PERIOD, '/nonexistent/cases.json', grids=['East', 'North', 'South'])
    assert set(outcome['settings']['monitoring_grids']) == {'East', 'South'}


@pytest.mark.parametrize('size', [(1000, 620), (1280, 800), (1920, 1080)])
def test_keyboard_zoom_keeps_actions_visible_and_does_not_change_configuration(monkeypatch, records, config, size):
    def steps(dialog, root, seen):
        root.geometry('{}x{}'.format(*size))
        root.update()
        original = gl.json.dumps(dialog.editor.config, sort_keys=True)
        selected = dialog.selected
        baseline = dialog.body_font.actual('size')
        for percent in (75, 125, 200, 100):
            dialog.set_zoom(percent)
            root.update()
            assert dialog.ui_zoom == percent / 100
            assert dialog.body_font.actual('size') == round(baseline * percent / 100)
            _assert_inside(root, [_button(root, text) for text in
                                 ('Save configuration', 'Load saved configuration', 'Cancel', 'Start calculation')])
            assert gl.json.dumps(dialog.editor.config, sort_keys=True) == original
            assert dialog.selected == selected
            assert not dialog.inline_edit
        assert not hasattr(dialog, 'zoom_box'), 'zoom is keyboard-only'
        assert not any(_safe_text(w) in ('Zoom', 'Reset', '+', '−') for w in _widgets(root))
        root.focus_force()
        root.event_generate('<Control-equal>')
        root.update()
        assert dialog.ui_zoom == 1.1
        root.event_generate('<Control-minus>')
        root.update()
        assert dialog.ui_zoom == 1.0
        root.event_generate('<Control-0>')
        root.update()
        assert dialog.ui_zoom == 1.0
    _run(monkeypatch, records, config, steps)


def test_narrow_tables_scroll_headers_and_filters_together(monkeypatch, records, config):
    def steps(dialog, root, seen):
        root.geometry('1000x620')
        root.update()
        dialog.place_dividers()
        root.update()
        table = dialog.available_table
        assert table.horizontal.winfo_ismapped()
        table.tree.xview_moveto(1.0)
        root.update()
        assert table.tree.xview()[0] > 0
        assert table.labels[0].winfo_x() < 0
        assert all(field.winfo_x() - label.winfo_x() == 2 for field, label in zip(table.inputs, table.labels))
        table.values[1].set('FS3')
        table.render()
        assert list(table.tree.get_children()) == [records[2]['key']]
        table.clear_filters()
        assert len(table.tree.get_children()) == len(records)
        assert dialog.canvas.winfo_width() > sum(tree.winfo_width() for tree in (dialog.available_tree, dialog.member_tree))
    _run(monkeypatch, records, config, steps)


@pytest.mark.parametrize('tk_scaling', [4/3, 2.0, 8/3])
def test_zoom_respects_system_scaling_without_clipping_table_text(monkeypatch, records, config, tk_scaling):
    original_init = tk.Tk.__init__
    def init(root, *args, **kwargs):
        original_init(root, *args, **kwargs)
        root.tk.call('tk', 'scaling', tk_scaling)
    monkeypatch.setattr(tk.Tk, '__init__', init)
    def steps(dialog, root, seen):
        for percent in (75, 100, 150, 200):
            dialog.set_zoom(percent)
            root.update()
            style = dialog.ttk.Style(root)
            assert int(style.lookup('Treeview', 'rowheight')) >= dialog.body_font.metrics('linespace')
            assert dialog.available_table.HEADER_HEIGHT >= dialog.bold_font.metrics('linespace')
            assert dialog.available_table.FILTER_HEIGHT - 6 >= dialog.small_font.metrics('linespace')
        dialog.set_zoom(100)
        entry = dialog.available_table.inputs[1]
        entry.focus_force()
        root.update()
        entry.event_generate('<Control-equal>')
        root.update()
        assert dialog.ui_zoom == 1.1
        assert entry.get() == '', 'zoom shortcuts must not insert text into a filter'
    _run(monkeypatch, records, config, steps)
