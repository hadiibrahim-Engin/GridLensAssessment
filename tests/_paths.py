"""Where the delivered files are, so that the tests need nothing else.

At the end of the project only the tests, gridlens_report.py and
MASTER_GRIDLENS.mrt remain. The two files are looked up in powerfactory/
next to tests/ and, if they are not there, directly next to tests/.
Development tools (tools/) are optional: their tests skip without them.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def delivered(name):
    for folder in (ROOT / "powerfactory", ROOT):
        if (folder / name).is_file():
            return folder / name
    return ROOT / "powerfactory" / name


def tool(name):
    """A development tool, or None when it is not part of this checkout."""
    path = ROOT / "tools" / name
    return path if path.is_file() else None
