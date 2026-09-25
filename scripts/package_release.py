"""Build a source-only handoff ZIP with a per-file checksum manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "pyproject.toml",
    "requirements.txt", "requirements.lock", "requirements-dev.lock",
    "start-panel.cmd", "Dockerfile", "compose.yaml", ".env.example",
    ".gitignore", ".dockerignore",
)
SOURCE_DIRS = ("src", "web", "content", "tests", "scripts", "docs", "deploy", ".github")
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def source_files(root: Path = ROOT) -> list[Path]:
    files = [root / name for name in ROOT_FILES]
    for name in SOURCE_DIRS:
        files.extend(path for path in (root / name).rglob("*") if path.is_file())
    selected = []
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path.name)
        relative = path.relative_to(root)
        if IGNORED_PARTS.intersection(relative.parts) or any(part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo", ".log", ".bak", ".lockfile", ".lnk"}:
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source symlink/outside path not allowed: {relative}")
        selected.append(path)
    return sorted(set(selected), key=lambda path: path.relative_to(root).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / "options-panel-2.0.0.zip"
    files = source_files()
    manifest = {"version": "2.0.0", "created_at": datetime.now(timezone.utc).isoformat(), "files": []}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            manifest["files"].append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            bundle.writestr("options-panel/" + relative, data)
        bundle.writestr("options-panel/FILE-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    (args.output / "FILE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Packaged {len(files)} source files: {archive}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
