"""Build source-only ZIP and Linux tar.gz handoff archives with SHA manifests."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md", "pyproject.toml",
    "package.json", "package-lock.json", "playwright.config.js", "requirements.txt",
    "requirements.lock", "requirements-dev.lock", "start-panel.cmd", "start-admin.cmd",
    "Dockerfile", "compose.yaml", ".env.example", ".gitignore", ".dockerignore", ".gitattributes",
)
SOURCE_DIRS = ("src", "web", "content", "tests", "scripts", "docs", "deploy", ".github")
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
IGNORED_ROOTS = {"runtime", "dist", "backups", "archive2.0"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".log", ".bak", ".lockfile", ".lnk", ".zip", ".gz"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def metadata() -> tuple[str, str]:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    commit = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout.strip().lower()
    if not commit or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("无法取得有效 Git commit")
    return version, commit


def source_files(root: Path = ROOT, *, tracked_only: bool = False) -> list[Path]:
    tracked = None
    if tracked_only:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
        tracked = {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}
    files = [root / name for name in ROOT_FILES]
    for name in SOURCE_DIRS:
        files.extend(path for path in (root / name).rglob("*") if path.is_file())
    selected = []
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path.name)
        relative = path.relative_to(root)
        lower_parts = {part.lower() for part in relative.parts}
        if (relative.parts[0].lower() in IGNORED_ROOTS or IGNORED_PARTS.intersection(lower_parts)
                or any(part.endswith(".egg-info") for part in lower_parts)):
            continue
        if path.suffix.lower() in IGNORED_SUFFIXES:
            continue
        if path.suffix.lower() in SENSITIVE_SUFFIXES:
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source symlink/outside path not allowed: {relative}")
        if tracked is not None and relative.as_posix() not in tracked:
            continue
        selected.append(path)
    return sorted(set(selected), key=lambda item: item.relative_to(root).as_posix())


def file_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n") if path.suffix == ".sh" else data


def require_clean_release_source() -> None:
    paths = [*ROOT_FILES, *SOURCE_DIRS]
    result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
                            cwd=ROOT, check=True, capture_output=True, text=True)
    if result.stdout.strip():
        raise RuntimeError("发布源码存在未提交改动或未跟踪文件；请先完成审查并提交，再生成版本包")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        require_clean_release_source()
    except RuntimeError as exc:
        parser.error(str(exc))
    version, commit = metadata()
    commit_time = subprocess.run(["git", "show", "-s", "--format=%cI", "HEAD"], cwd=ROOT,
                                 check=True, capture_output=True, text=True).stdout.strip()
    stem = f"options-panel-{version}-g{commit}"
    files = source_files(tracked_only=True)
    manifest = {"version": version, "git_commit": commit, "commit_time": commit_time, "files": []}
    payloads = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        data = file_bytes(path); mode = 0o755 if path.suffix == ".sh" else 0o644
        manifest["files"].append({"path": relative, "bytes": len(data), "mode": oct(mode),
                                  "sha256": hashlib.sha256(data).hexdigest()})
        payloads.append((relative, data, mode))
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    zip_path = args.output / f"{stem}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative, data, mode in payloads:
            info = zipfile.ZipInfo(f"options-panel/{relative}"); info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
        bundle.writestr("options-panel/FILE-MANIFEST.json", manifest_bytes)

    tar_path = args.output / f"{stem}-linux.tar.gz"
    with tar_path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
            for relative, data, mode in payloads + [("FILE-MANIFEST.json", manifest_bytes, 0o644)]:
                info = tarfile.TarInfo(f"options-panel/{relative}")
                info.size = len(data); info.mode = mode; info.mtime = 0; info.uid = info.gid = 0
                info.uname = info.gname = "root"
                bundle.addfile(info, io.BytesIO(data))

    manifest_path = args.output / f"{stem}-FILE-MANIFEST.json"; manifest_path.write_bytes(manifest_bytes)
    checksum_path = args.output / f"{stem}-SHA256SUMS.txt"
    checksum_path.write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                     for path in (zip_path, tar_path, manifest_path)),
                             encoding="ascii", newline="\n")
    print(f"Packaged {len(files)} source files for version {version}, commit {commit}")
    print(tar_path); print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
