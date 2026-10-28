"""Package the runtime and current report pages with traceable build metadata.

Uses only the standard library. Run from any directory:
    python ui/build_release.py --output-dir /path/to/artifacts
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ("MASTER_GRIDLENS", "MASTER_GRIDLENS_DETAIL")
SCRIPTS = ("outage-assessment/main.py", "outage-assessment/main_qt.py")
DOCUMENTS = ("README.md", "docs/POWERFACTORY.md", "docs/de/POWERFACTORY.md",
             "docs/RELEASE_CHECKLIST.md")
RUNTIME_FILES = (*SCRIPTS, "outage-assessment/__init__.py")


def publisher_version(source: bytes) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PUBLISHER_VERSION"
            for target in node.targets
        ):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version):
                return version
    raise ValueError("Missing or invalid PUBLISHER_VERSION")


def release_files(root: Path) -> dict[str, bytes]:
    # Explicit delivery allowlist: no local configurations, logs, old templates,
    # development probes, virtual environments or generated results.
    paths = [root / name for name in (*RUNTIME_FILES, *DOCUMENTS)]
    for report in REPORTS:
        folder = root / "designer-pages" / report
        pages = sorted(folder.glob("*.pg"))
        if not pages:
            raise ValueError(f"No report pages found: {report}")
        paths.extend([folder / f"{report}.dct", *pages])
    payload = {}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Release file must be inside the repository: {path}")
        payload[path.relative_to(root).as_posix()] = path.read_bytes()
    return payload


def build_release(root: Path, output_dir: Path, *, commit: str, build_id: str,
                  dirty: bool, require_clean: bool = False) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("A full Git commit hash is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", build_id):
        raise ValueError("Invalid build ID")
    if require_clean and dirty:
        raise ValueError("CI release requires a clean working tree")
    payload = release_files(root)
    versions = {publisher_version(payload[name]) for name in SCRIPTS}
    if len(versions) != 1:
        raise ValueError("Tk and Qt runtime versions differ")
    version = versions.pop()
    manifest = {
        "schema_version": 1,
        "version": version,
        "commit": commit,
        "build_id": build_id,
        "working_tree_dirty": dirty,
        "powerfactory_acceptance": "not_performed_by_ci",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for name, data in sorted(payload.items())
        },
    }
    payload["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"GridLens-{version}-{commit[:12]}-build{build_id}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as bundle:
        for name, data in sorted(payload.items()):
            # Normalize timestamps and permissions so identical inputs produce
            # identical archives with the same compression toolchain.
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, data, compresslevel=9)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        f"{checksum}  {archive.name}\n", encoding="utf-8"
    )
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--build-id", default=os.environ.get("BUILD_BUILDID", "local"))
    parser.add_argument("--require-clean", action="store_true",
                        help="Refuse a release if tracked or untracked files changed")
    args = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True
    ).strip())
    archive = build_release(ROOT, args.output_dir, commit=commit,
                            build_id=args.build_id, dirty=dirty,
                            require_clean=args.require_clean)
    print(f"Created {archive}")


if __name__ == "__main__":
    main()
