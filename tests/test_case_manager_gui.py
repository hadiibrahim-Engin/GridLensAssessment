"""Exercise the standalone dialog's actual callbacks without a desktop session."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "FS_CaseManager_GUI_Test_PowerFactory2026.py"
SPEC = importlib.util.spec_from_file_location("case_manager_gui", SCRIPT)
gui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gui)


class Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, parent=None, *, kind="Widget", **options):
        self.kind, self.options = kind, options
        self.children, self.bindings, self.cells = [], {}, {}
        self.destroyed = False
        self.root = parent.root if parent else self
        if parent:
            parent.children.append(self)

    def pack(self, **options):
        pass

    def grid(self, **options):
        self.cells = options

    def configure(self, **options):
        self.options.update(options)

    def bind(self, name, callback):
        self.bindings[name] = callback

    def winfo_children(self):
        return [child for child in self.children if not child.destroyed]

    def destroy(self):
        self.destroyed = True
        for child in self.children:
            child.destroy()

    def grid_rowconfigure(self, *args, **options):
        pass

    grid_columnconfigure = grid_rowconfigure

    def create_window(self, *args, **options):
        return 1

    def itemconfigure(self, *args, **options):
        pass

    def bbox(self, *args):
        return (0, 0, 1000, 1000)

    def yview(self, *args):
        pass

    xview = yview

    def set(self, *args):
        pass

    def winfo_reqwidth(self):
        return 900

    def winfo_width(self):
        return 740

    def update_idletasks(self):
        pass

    def invoke(self):
        if self.kind == "Checkbutton":
            flag = self.options["variable"]
            flag.set(not flag.get())
        elif self.kind == "Radiobutton":
            self.options["variable"].set(self.options["value"])
        self.options["command"]()


class Root(Widget):
    def __init__(self, scenario):
        super().__init__(kind="Root")
        self.scenario = scenario
        self.quitted = False

    def title(self, *args):
        pass

    geometry = minsize = title

    def protocol(self, name, callback):
        self.bind(name, callback)

    def after(self, *args):
        pass

    def lift(self):
        pass

    def quit(self):
        self.quitted = True

    def mainloop(self):
        self.scenario(self)


def widgets(root):
    if not root.destroyed:
        yield root
        for child in root.children:
            yield from widgets(child)


def named(root, text):
    return next(widget for widget in widgets(root) if widget.options.get("text") == text)


def checkbox(root, row, column):
    return next(widget for widget in widgets(root)
                if widget.kind == "Checkbutton"
                and widget.cells.get("row") == row
                and widget.cells.get("column") == column)


def run_dialog(scenario, *, answers=(), outages=None):
    roots = []

    def create_root():
        root = Root(scenario)
        roots.append(root)
        return root

    def factory(kind):
        return lambda parent=None, **options: Widget(parent, kind=kind, **options)

    tk = SimpleNamespace(Tk=create_root, StringVar=Variable, BooleanVar=Variable,
                         Canvas=factory("Canvas"))
    ttk = SimpleNamespace(**{kind: factory(kind) for kind in (
        "Frame", "Label", "LabelFrame", "Scrollbar", "Checkbutton", "Separator",
        "Button", "Radiobutton", "Combobox")})
    replies = iter(answers)
    dialogs = SimpleNamespace(askstring=lambda *args, **options: next(replies))
    result = gui.launch_dialog(tk, ttk, dialogs, None,
                               gui.DEMO_OUTAGES if outages is None else outages, "DEMO")
    assert roots[0].destroyed
    return result


def test_matrix_is_default_and_new_case_adds_an_independent_column():
    def scenario(root):
        assert named(root, "Matrix").options["variable"].get() == "matrix"
        checkbox(root, 1, 2).invoke()
        named(root, "+ Case").invoke()
        assert checkbox(root, 1, 2).options["variable"].get()
        assert not checkbox(root, 1, 3).options["variable"].get()
        checkbox(root, 2, 3).invoke()
        checkbox(root, 3, 2).invoke()
        named(root, "OK (test only)").invoke()

    result = run_dialog(scenario, answers=["Case B"])
    assert result == {"confirmed": True, "cases": {
        "Case A": ["demo-FS-001", "demo-FS-003"], "Case B": ["demo-FS-002"]}, "source": "DEMO"}


def test_view_switch_retains_assignments_and_uses_the_selected_case():
    def scenario(root):
        checkbox(root, 1, 2).invoke()
        named(root, "+ Case").invoke()
        checkbox(root, 2, 3).invoke()
        named(root, "Single case").invoke()
        assert not checkbox(root, 1, 2).options["variable"].get()
        assert checkbox(root, 2, 2).options["variable"].get()
        checkbox(root, 4, 2).invoke()
        selector = next(w for w in widgets(root) if w.kind == "Combobox")
        selector.options["textvariable"].set("Case A")
        selector.bindings["<<ComboboxSelected>>"](None)
        assert checkbox(root, 1, 2).options["variable"].get()
        named(root, "Matrix").invoke()
        assert checkbox(root, 4, 3).options["variable"].get()
        named(root, "OK (test only)").invoke()

    result = run_dialog(scenario, answers=["Case B"])
    assert result["cases"] == {"Case A": ["demo-FS-001"], "Case B": ["demo-FS-002", "demo-FS-004"]}


def test_delete_case_keeps_other_columns_and_refuses_to_delete_the_last():
    def scenario(root):
        checkbox(root, 1, 2).invoke()
        named(root, "+ Case").invoke()
        checkbox(root, 2, 3).invoke()
        named(root, "Delete case").invoke()
        assert not any(w.kind == "Checkbutton" and w.cells.get("column") == 3 for w in widgets(root))
        named(root, "Delete case").invoke()
        assert checkbox(root, 1, 2).options["variable"].get()
        named(root, "OK (test only)").invoke()

    assert run_dialog(scenario, answers=["Case B"])["cases"] == {"Case A": ["demo-FS-001"]}


@pytest.mark.parametrize("action", ["button", "escape", "window"])
def test_cancel_discards_all_assignments(action):
    def scenario(root):
        checkbox(root, 1, 2).invoke()
        if action == "button":
            named(root, "Cancel").invoke()
        elif action == "escape":
            root.bindings["<Escape>"](None)
        else:
            root.bindings["WM_DELETE_WINDOW"]()

    assert run_dialog(scenario) == {"confirmed": False, "cases": {}, "source": "DEMO"}


def test_blank_duplicate_and_cancelled_names_do_not_create_columns():
    def scenario(root):
        named(root, "+ Case").invoke()
        named(root, "+ Case").invoke()
        named(root, "OK (test only)").invoke()

    assert run_dialog(scenario, answers=[" ", "Case A", "Case B", None])["cases"] == {"Case A": [], "Case B": []}


def test_identical_outage_names_keep_independent_identities():
    records = [{"id": "path/a", "name": "Same name", "period": "Week 1"},
               {"id": "path/b", "name": "Same name", "period": "Week 1"}]

    def scenario(root):
        checkbox(root, 2, 2).invoke()
        named(root, "OK (test only)").invoke()

    assert run_dialog(scenario, outages=records)["cases"] == {"Case A": ["path/b"]}


def test_empty_outage_list_can_be_confirmed():
    def scenario(root):
        named(root, "No outages available.")
        named(root, "OK (test only)").invoke()

    assert run_dialog(scenario, outages=[])["cases"] == {"Case A": []}


def test_toggling_a_matrix_cell_updates_counts_without_replacing_the_cell():
    def scenario(root):
        cell = checkbox(root, 1, 2)
        cell.invoke()
        assert checkbox(root, 1, 2) is cell
        texts = [w.options["textvariable"].get() for w in widgets(root)
                 if w.kind == "Label" and "textvariable" in w.options]
        assert "1 selected" in texts
        assert "4 outages | 1 cases | 1 assignments" in texts
        named(root, "OK (test only)").invoke()

    assert run_dialog(scenario)["cases"] == {"Case A": ["demo-FS-001"]}
