"""The stand-alone grid probe must filter exactly like the report."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gl = _load("gridlens_report_for_probe", ROOT / "powerfactory" / "gridlens_report.py")
probe = _load("probe_grid_filter", ROOT / "tools" / "probe_grid_filter.py")


class Obj:
    def __init__(self, name, kind, path=None, **attributes):
        self.loc_name = name
        self._kind = kind
        self._path = path
        self.__dict__.update(attributes)

    def GetClassName(self):
        return self._kind

    def GetFullName(self):
        if self._path is None:
            raise RuntimeError("no path")
        return self._path


D7 = Obj("D7 Westnetz", "ElmNet", "\\P.IntPrj\\D7 Westnetz.ElmNet")
NL = Obj("NL TenneT", "ElmNet", "\\P.IntPrj\\NL TenneT.ElmNet")
CASES = [
    Obj("Ltg 1", "ElmLne", "\\P.IntPrj\\D7 Westnetz.ElmNet\\Ltg 1.ElmLne", cpGrid=D7),
    Obj("D7 named but foreign", "ElmLne", "\\P.IntPrj\\NL TenneT.ElmNet\\x.ElmLne", cpGrid=NL),
    Obj("In a variation", "ElmLne", "\\P.IntPrj\\Variations\\Stage.IntSstage\\v.ElmLne", cpGrid=D7),
    Obj("Only the path", "ElmTerm", "\\P.IntPrj\\D7 Westnetz.ElmNet\\b.ElmTerm"),
    Obj("Orphan", "ElmTerm", "\\P.IntPrj\\b.ElmTerm"),
    Obj("No path at all", "ElmTr2"),
    Obj("Grid given as text", "ElmTr2", "\\P.IntPrj\\t.ElmTr2", cpGrid="D7 Westnetz"),
]


def test_probe_uses_the_report_filter_and_variables():
    assert probe.GRID_NAME_FILTER == gl.GRID_NAME_FILTER
    assert probe.VARIABLES == gl.VARIABLES
    assert probe.CLASS_CATEGORIES == gl.CLASS_CATEGORIES


@pytest.mark.parametrize("element", CASES, ids=lambda element: element.loc_name)
def test_probe_decides_every_element_like_the_report(element):
    assert probe.element_grid_name(element) == gl.element_grid_name(element)
    assert probe.element_in_scope(element) == gl.element_in_scope(element)


@pytest.mark.parametrize("variable", ["c:loading", "m:loading", "m:u", "m:phiu", "m:P:bus1"])
@pytest.mark.parametrize("kind", ["ElmLne", "ElmTr2", "ElmTr3", "ElmTerm", "ElmSym"])
def test_probe_recognises_the_same_result_variables(kind, variable):
    element = Obj("x", kind, "\\x")
    assert probe.result_category(element, variable) == gl.result_category(element, variable)


def test_probe_needs_nothing_but_powerfactory():
    source = (ROOT / "tools" / "probe_grid_filter.py").read_text(encoding="utf-8")
    imports = {line.split()[1] for line in source.splitlines()
               if line.startswith(("import ", "from "))}
    assert imports <= {"time", "powerfactory"}, imports
