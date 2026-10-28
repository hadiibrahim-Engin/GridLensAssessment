"""Verify the delivered archive, provenance and integrity checks."""

import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_release", ROOT / "ui/build_release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
COMMIT = "a" * 40


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    files = {
        "README.md": "Installation",
        "outage-assessment/__init__.py": "",
        **{name: "PUBLISHER_VERSION = '8.0.1'\n" for name in release.SCRIPTS},
        "docs/POWERFACTORY.md": "PowerFactory acceptance required",
        "docs/de/POWERFACTORY.md": "PowerFactory-Abnahme erforderlich",
        "docs/RELEASE_CHECKLIST.md": "Release checklist",
        "docs/private-notes.md": "private notes",
        ".env": "LOCAL_SECRET=must_not_ship",
        "templates/archive/old.mrt": "obsolete",
        "output/customer-results.json": "private results",
    }
    for report in release.REPORTS:
        files[f"designer-pages/{report}/{report}.dct"] = "dictionary"
        files[f"designer-pages/{report}/00_Cover.pg"] = "cover"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_archive_contains_delivery_files_with_verifiable_provenance(source, tmp_path):
    archive = release.build_release(source, tmp_path / "out", commit=COMMIT,
                                    build_id="42", dirty=False)
    assert archive.name == f"GridLens-8.0.1-{COMMIT[:12]}-build42.zip"
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["commit"] == COMMIT
        assert manifest["build_id"] == "42"
        assert manifest["working_tree_dirty"] is False
        assert manifest["powerfactory_acceptance"] == "not_performed_by_ci"
        assert set(bundle.namelist()) == set(manifest["files"]) | {"manifest.json"}
        assert not {".env", "templates/archive/old.mrt", "output/customer-results.json", "docs/private-notes.md"} & set(bundle.namelist())
        assert set(release.SCRIPTS) <= set(bundle.namelist())
        for name, record in manifest["files"].items():
            data = bundle.read(name)
            assert hashlib.sha256(data).hexdigest() == record["sha256"]
            assert len(data) == record["size"]
    assert archive.with_suffix(".zip.sha256").read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
    repeated = release.build_release(source, tmp_path / "again", commit=COMMIT,
                                     build_id="42", dirty=False)
    assert repeated.read_bytes() == archive.read_bytes()


@pytest.mark.parametrize("missing", [
    release.SCRIPTS[0],
    f"designer-pages/{release.REPORTS[0]}/{release.REPORTS[0]}.dct",
    f"designer-pages/{release.REPORTS[1]}/00_Cover.pg",
])
def test_incomplete_delivery_fails_before_creating_an_archive(source, tmp_path, missing):
    (source / missing).unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        release.build_release(source, tmp_path / "out", commit=COMMIT,
                              build_id="42", dirty=False)
    assert not (tmp_path / "out").exists()


def test_mismatched_runtime_versions_cannot_be_released_together(source, tmp_path):
    (source / release.SCRIPTS[1]).write_text("PUBLISHER_VERSION = '9.0.0'\n")
    with pytest.raises(ValueError, match="versions differ"):
        release.build_release(source, tmp_path / "out", commit=COMMIT,
                              build_id="42", dirty=False)


def test_ci_release_refuses_changes_since_checkout(source, tmp_path):
    with pytest.raises(ValueError, match="clean working tree"):
        release.build_release(source, tmp_path / "out", commit=COMMIT,
                              build_id="42", dirty=True, require_clean=True)
    assert not (tmp_path / "out").exists()
