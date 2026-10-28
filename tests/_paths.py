"""Where the delivered files are, so that the tests need nothing else.

At the end of the project only the tests, the scripts in outage-assessment/
(main.py, main_qt.py) and the two reports as pages remain:
designer-pages/MASTER_GRIDLENS and designer-pages/MASTER_GRIDLENS_DETAIL, each
one .dct dictionary and one .pg file per page (Stimulsoft "Save Page"). The
report itself is assembled in the Stimulsoft designer: dictionary first, then
Open Page in file order. The scripts are looked up in outage-assessment/ and
the reports in designer-pages/; if they are not there, directly next to
tests/. Development tools and probes (ui/) are optional: their tests skip
without them.
"""

import re
import os
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ("MASTER_GRIDLENS", "MASTER_GRIDLENS_DETAIL")
RUNTIME = os.environ.get("GRIDLENS_TEST_RUNTIME", "tk")
if RUNTIME not in ("tk", "qt"):
    raise ValueError("GRIDLENS_TEST_RUNTIME must be tk or qt")


def delivered(name):
    if name == "main.py" and RUNTIME == "qt":
        name = "main_qt.py"
    for folder in (ROOT / "outage-assessment", ROOT):
        if (folder / name).is_file():
            return folder / name
    return ROOT / "outage-assessment" / name


def report_folder(name):
    """The folder of one report: its .dct dictionary and its .pg pages."""
    for folder in (ROOT / "designer-pages", ROOT):
        if (folder / name).is_dir():
            return folder / name
    return ROOT / "designer-pages" / name


def report_files(name):
    """(dictionary, [pages in file order]) of one report."""
    folder = report_folder(name)
    return next(folder.glob("*.dct")), sorted(folder.glob("*.pg"), key=lambda path: path.name)


def report_tree(name):
    """One report as the designer assembles it: <Report><Dictionary>…</Dictionary><Pages><PageX>…</PageX>…</Pages></Report>.

    Every page element is named after its file (00_Cover.pg -> PageCover); refs restart in every file.
    """
    dictionary, pages = report_files(name)
    root = ET.Element("Report")
    ET.SubElement(root, "Dictionary").extend(list(ET.parse(dictionary).getroot()))
    container = ET.SubElement(root, "Pages")
    for path in pages:
        page = ET.parse(path).getroot()
        page.tag = "Page" + re.sub(r"^\d+_", "", path.stem)
        container.append(page)
    return root


def report_text(name):
    """The raw text of every file of one report (dictionary and pages)."""
    dictionary, pages = report_files(name)
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in [dictionary] + pages)


def tool(name):
    """A development tool, or None when it is not part of this checkout."""
    path = ROOT / "ui" / name
    return path if path.is_file() else None
