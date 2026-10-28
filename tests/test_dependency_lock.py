"""Catch drift between editable dev requirements and the hash-verified CI lock."""

from pathlib import Path
import re
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def test_dependency_lock_matches_the_dev_group_and_hashes_every_package():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    def identity(requirement):
        return (canonicalize_name(requirement.name), str(requirement.specifier), str(requirement.marker))

    declared = {identity(Requirement(item)) for item in config["dependency-groups"]["dev"]}
    text = (ROOT / "ci/requirements.lock").read_text()
    entries = text.replace("\\\n", " ").splitlines()
    locked = set()
    for entry in entries:
        if not entry.strip() or entry.lstrip().startswith("#"):
            continue
        requirement, *hashes = entry.split("--hash=sha256:")
        parsed = Requirement(requirement.strip())
        assert hashes and all(re.fullmatch(r"[a-f0-9]{64}", item.strip()) for item in hashes)
        assert all(spec.operator == "==" and "*" not in spec.version for spec in parsed.specifier)
        locked.add(identity(parsed))
    assert locked == declared, "Regenerate ci/requirements.lock from pyproject.toml"
