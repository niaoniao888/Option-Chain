"""Create and safely restore archives of the persistent runtime volume."""
from __future__ import annotations

import argparse
import gzip
import io
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from options_panel.us_equities.guide_store import GuideStore
from options_panel.us_equities.watchlist_store import WatchlistStore

MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_TAR_BYTES = 40 * 1024 * 1024
MAX_CONTENT_BYTES = 32 * 1024 * 1024
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 16
DATA_FILES = {
    "watchlist.json", "watchlist.json.bak",
    "options-guide.json", "options-guide.json.bak",
}


def _members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)):
        raise ValueError("归档包含重复文件名")
    required = {"watchlist.json", "options-guide.json"}
    if not required.issubset(names):
        raise ValueError("归档缺少 watchlist.json 或 options-guide.json")
    if len(members) > MAX_MEMBERS or sum(member.size for member in members) > MAX_CONTENT_BYTES:
        raise ValueError("归档文件数量或解压后大小超过限制")
    for member in members:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or len(path.parts) != 1
                or member.name not in DATA_FILES or not member.isfile()
                or member.issym() or member.islnk() or member.isdev()):
            raise ValueError(f"不安全的归档成员：{member.name}")
    return members


def _validate_document(name: str, data: bytes) -> None:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"数据文件超过大小限制：{name}")
    if name.startswith("watchlist.json"):
        WatchlistStore(Path("unused"))._decode(data)
    elif name.startswith("options-guide.json"):
        GuideStore._decode(data)
    else:
        raise ValueError(f"不允许的数据文件：{name}")


def _backup_stream(source: Path, output) -> None:
    watchlist = WatchlistStore(source / "watchlist.json")
    guide = GuideStore(source / "options-guide.json")
    current = {
        "watchlist.json": watchlist._encode(watchlist.list()),
        "options-guide.json": guide._encode(guide.get()),
    }
    with tarfile.open(fileobj=output, mode="w|gz", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(DATA_FILES):
            child = source / name
            data = current.get(name)
            if data is None and child.is_file() and not child.is_symlink():
                data = child.read_bytes()
            if data is not None:
                _validate_document(name, data)
                info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o600
                archive.addfile(info, io.BytesIO(data))


def backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("wb") as output:
        _backup_stream(source, output)
    os.replace(temporary, destination)


def restore(source: Path, destination: Path) -> None:
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("备份归档超过大小限制")
    with gzip.open(source, "rb") as compressed:
        tar_bytes = compressed.read(MAX_TAR_BYTES + 1)
    if len(tar_bytes) > MAX_TAR_BYTES:
        raise ValueError("归档解压流超过大小限制")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = _members(archive)
        recovery = Path(tempfile.mkdtemp(prefix=".restore-recovery-", dir=destination))
        original_names: set[str] = set()
        preserve_recovery = False
        try:
            for name in sorted(DATA_FILES):
                target = destination / name
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise ValueError(f"恢复目标不是普通文件：{name}")
                if target.exists():
                    shutil.copy2(target, recovery / name)
                    original_names.add(name)
            with tempfile.TemporaryDirectory(prefix=".restore-stage-", dir=destination) as staging_name:
                staging = Path(staging_name)
                archive.extractall(staging, members=members, filter="data")
                staged_root = staging.resolve()
                if any(not path.resolve().is_relative_to(staged_root) for path in staging.rglob("*")):
                    raise ValueError("归档内容越过恢复目录")
                for member in members:
                    _validate_document(member.name, (staging / member.name).read_bytes())
                archived = {member.name for member in members}
                try:
                    for name in sorted(DATA_FILES):
                        target = destination / name
                        if name in archived:
                            os.replace(staging / name, target)
                        elif target.exists():
                            target.unlink()
                except Exception as restore_exc:
                    rollback_errors: list[tuple[str, Exception]] = []
                    for name in sorted(DATA_FILES):
                        target = destination / name
                        try:
                            if name in original_names:
                                rollback_copy = recovery / f".{name}.rollback"
                                shutil.copy2(recovery / name, rollback_copy)
                                try:
                                    os.replace(rollback_copy, target)
                                except OSError:
                                    shutil.copy2(recovery / name, target)
                                    rollback_copy.unlink(missing_ok=True)
                            elif target.exists():
                                target.unlink()
                        except Exception as rollback_exc:
                            rollback_errors.append((name, rollback_exc))
                    if rollback_errors:
                        preserve_recovery = True
                        names = ", ".join(name for name, _error in rollback_errors)
                        raise RuntimeError(
                            f"恢复失败，部分原数据无法自动回滚；恢复副本保留在 {recovery}；受影响文件：{names}"
                        ) from restore_exc
                    raise
        except Exception:
            if not preserve_recovery:
                shutil.rmtree(recovery, ignore_errors=True)
            raise
        else:
            shutil.rmtree(recovery)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    if args.action == "backup":
        if args.destination == "-":
            _backup_stream(Path(args.source), sys.stdout.buffer)
        else:
            backup(Path(args.source), Path(args.destination))
    else:
        if args.source == "-":
            data = sys.stdin.buffer.read(MAX_ARCHIVE_BYTES + 1)
            if len(data) > MAX_ARCHIVE_BYTES:
                raise ValueError("备份归档超过大小限制")
            with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temporary:
                temporary.write(data); temporary.flush()
                restore(Path(temporary.name), Path(args.destination))
        else:
            restore(Path(args.source), Path(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
