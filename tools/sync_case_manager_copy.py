"""Copy the case manager of gridlens_report.py into the standalone GUI test tool.

Development tool, not part of the delivery. The PowerFactory GUI test
(tools/FS_CaseManager_GUI_Test_PowerFactory2026.py) is a separate script: it
does not import gridlens_report.py. It carries a verbatim copy of the case
manager window and of everything that window needs (reading the planned
outages, checking a configuration, the preview), so that it shows exactly the
window GridLens shows. Whoever changes the case manager in gridlens_report.py
runs this script; tests/test_case_manager_gui.py fails while the copy is out of
date.

    python3 tools/sync_case_manager_copy.py           # rewrite the copy
    python3 tools/sync_case_manager_copy.py --check   # exit code 1 when out of date
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "powerfactory" / "gridlens_report.py"
TOOL = ROOT / "tools" / "FS_CaseManager_GUI_Test_PowerFactory2026.py"

# What the test tool calls; everything these use is copied with them.
ROOTS = ("run_case_manager", "CaseEditor", "qds_period", "qds_period_text", "classify_planned_outages", "RunLogger",
         "assign_definitions", "object_key", "case_config_path", "load_case_config", "empty_case_config",
         "_format_pf_time", "_friendly_exception", "CaseManagerUnavailable", "PUBLISHER_VERSION")
BEGIN = "# >>> copy of powerfactory/gridlens_report.py, written by tools/sync_case_manager_copy.py - do not edit >>>"
END = "# <<< end of the copy <<<"


def _names(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return [node.name]
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    found = []
    for target in targets:
        elements = target.elts if isinstance(target, ast.Tuple) else [target]
        found += [element.id for element in elements if isinstance(element, ast.Name)]
    return found


def _used(node):
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)} | \
        {item.attr for item in ast.walk(node) if isinstance(item, ast.Attribute)}


def _tool_imports(tool_text):
    """Names the tool imports itself, above the copy; the copy does not import them again."""
    header = ast.parse(tool_text[:tool_text.index(BEGIN)])
    return {alias.asname or alias.name.split(".")[0] for node in header.body if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names}


def copied_block(source_text=None, tool_text=None):
    """The block the test tool must contain: the needed imports and definitions, in source order.

    The tool imports what its own code uses in its header, so its code never
    depends on which imports the copied definitions happen to need.
    """
    text = source_text if source_text is not None else SOURCE.read_text(encoding="utf-8")
    present = _tool_imports(tool_text if tool_text is not None else TOOL.read_text(encoding="utf-8"))
    tree = ast.parse(text)
    definitions = {}
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            imports.append(node)
        for name in _names(node):
            definitions[name] = node
    needed, todo = set(), list(ROOTS)
    while todo:
        name = todo.pop()
        if name in needed or name not in definitions:
            continue
        needed.add(name)
        todo += [item for item in _used(definitions[name]) if item in definitions and item not in needed]
    nodes = [node for node in tree.body if any(name in needed for name in _names(node))]
    used = set().union(*(_used(node) for node in nodes))
    lines = [BEGIN, "# GridLens {}: {} definitions.".format(_version(definitions, text), len(nodes))]
    for node in imports:
        bound = [alias.asname or alias.name.split(".")[0] for alias in node.names]
        if any(name in used for name in bound) and not all(name in present for name in bound):
            lines.append(ast.get_source_segment(text, node))
    for node in nodes:
        lines += ["", "", ast.get_source_segment(text, node)]
    lines += ["", "", END]
    return "\n".join(lines) + "\n"


def _version(definitions, text):
    node = definitions.get("PUBLISHER_VERSION")
    return ast.literal_eval(node.value) if node is not None else "?"


def current_block(tool_text=None):
    text = tool_text if tool_text is not None else TOOL.read_text(encoding="utf-8")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[start:end] + "\n"


def write():
    text = TOOL.read_text(encoding="utf-8")
    start, end = text.index(BEGIN), text.index(END) + len(END) + 1
    TOOL.write_text(text[:start] + copied_block() + text[end:], encoding="utf-8")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        fresh = current_block() == copied_block()
        print("the copy is up to date" if fresh else "the copy is out of date: run python3 tools/sync_case_manager_copy.py")
        sys.exit(0 if fresh else 1)
    write()
    print("copied the case manager of {} into {}".format(SOURCE.name, TOOL.name))
