"""The case manager dialog builds and returns its configuration (skipped without Tk or a display)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gridlens_dialog", ROOT / "powerfactory" / "gridlens_report.py")
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)


def _widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _widgets(child)


def _press(label):
    def mainloop(self):
        buttons = {}
        for widget in _widgets(self):
            try:
                buttons[widget.cget("text")] = widget
            except Exception:
                pass
        buttons[label].invoke()
    return mainloop


@pytest.fixture
def records():
    try:
        tk.Tk().destroy()
    except Exception:
        pytest.skip("Tk cannot open a window here")
    return [{"key": "P\\FS{}".format(i), "id": "FS{}".format(i), "name": "FS{}".format(i), "window": (i * 3600.0, (i + 5) * 3600.0),
             "component_keys": [], "equipment_name": "Line", "start_time": "", "end_time": "", "priority": 1, "originally_ignored": False}
            for i in range(3)]


def test_ok_returns_the_configuration(monkeypatch, records):
    monkeypatch.setattr(tk.Tk, "mainloop", _press("OK - calculate"))
    config = gl.empty_case_config()
    config["cases"] = [{"id": "A", "name": "A", "outages": [records[0]["key"], records[1]["key"]]}]

    returned = gl.run_case_manager(records, config, (0.0, 86400.0), "unused.json")

    assert [case["outages"] for case in returned["cases"]] == [[records[0]["key"], records[1]["key"]]]


def test_cancel_returns_nothing(monkeypatch, records):
    monkeypatch.setattr(tk.Tk, "mainloop", _press("Cancel"))

    assert gl.run_case_manager(records, gl.empty_case_config(), (0.0, 86400.0), "unused.json") is None


def test_a_dialog_that_cannot_be_built_counts_as_unavailable(monkeypatch, records):
    from tkinter import ttk

    def broken(*_args, **_kwargs):
        raise RuntimeError("theme missing")
    monkeypatch.setattr(ttk, "Treeview", broken)

    with pytest.raises(gl.CaseManagerUnavailable, match="theme missing"):
        gl.run_case_manager(records, gl.empty_case_config(), (0.0, 86400.0), "unused.json")


def test_errors_in_buttons_are_shown_not_swallowed(monkeypatch, records):
    from tkinter import messagebox
    shown = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, text, **_kw: shown.append(text))

    def mainloop(self):
        self.report_callback_exception(ValueError, ValueError("bad input"), None)
        for widget in _widgets(self):
            try:
                if widget.cget("text") == "Cancel":
                    widget.invoke()
                    return
            except Exception:
                pass
    monkeypatch.setattr(tk.Tk, "mainloop", mainloop)

    assert gl.run_case_manager(records, gl.empty_case_config(), (0.0, 86400.0), "unused.json") is None
    assert shown == ["ValueError: bad input"]


def test_buttons_reach_the_editor_and_ok_returns_its_configuration(monkeypatch, records):
    def mainloop(self):
        dialog = self.report_callback_exception.__self__
        dialog.editor.add_case("A", "A")
        dialog.refresh_cases("A")
        dialog.tree.focus(records[2]["key"])
        dialog.toggle_member()
        dialog.toggle_fixed()
        dialog.confirm()
    monkeypatch.setattr(tk.Tk, "mainloop", mainloop)

    returned = gl.run_case_manager(records, gl.empty_case_config(), (0.0, 86400.0), "unused.json")

    assert returned["cases"][0]["outages"] == [records[2]["key"]]
    assert returned["background"] == [records[2]["key"]]
