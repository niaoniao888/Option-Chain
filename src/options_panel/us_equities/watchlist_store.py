from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


class WatchlistConflictError(ValueError):
    pass


def normalize_symbol(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("股票代码必须是非空字符串")
    symbol = value.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError("股票代码仅允许 1–10 位大写字母、数字、点或连字符，且必须以字母开头")
    return symbol


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _revision(symbols: list[str]) -> str:
    payload = json.dumps({"symbols": symbols}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class WatchlistStore:
    def __init__(self, path: Path, default: tuple[str, ...] = ("SPCX",)):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.default = list(default)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _thread_lock(self.lock_path):
            with self.lock_path.open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _decode(self, data: bytes) -> list[str]:
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise ValueError("watchlist 文件格式错误")
        result: list[str] = []
        for value in payload["symbols"]:
            symbol = normalize_symbol(value)
            if symbol not in result:
                result.append(symbol)
        return result

    def _load_unlocked(self) -> list[str]:
        errors: list[Exception] = []
        for candidate in (self.path, self.backup_path):
            try:
                return self._decode(candidate.read_bytes())
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(exc)
        if all(isinstance(error, OSError) for error in errors):
            return list(self.default)
        raise ValueError("watchlist 文件损坏且没有可用备份")

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _encode(symbols: list[str]) -> bytes:
        return (json.dumps({"symbols": symbols}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def get(self) -> dict[str, object]:
        with self._locked():
            symbols = self._load_unlocked()
        return {"symbols": symbols, "revision": _revision(symbols)}

    def list(self) -> list[str]:
        return list(self.get()["symbols"])

    def _change(self, value: object, expected_revision: str | None, *, remove: bool) -> dict[str, object]:
        symbol = normalize_symbol(value)
        with self._locked():
            current = self._load_unlocked()
            current_revision = _revision(current)
            if expected_revision is not None and expected_revision != current_revision:
                raise WatchlistConflictError("自选列表已被其他窗口更新")
            updated = [item for item in current if item != symbol] if remove else (
                current if symbol in current else [*current, symbol]
            )
            if updated != current:
                self._atomic_write(self.backup_path, self._encode(current))
                self._atomic_write(self.path, self._encode(updated))
            return {"symbols": list(updated), "revision": _revision(updated)}

    def add(self, value: object, expected_revision: str | None = None) -> list[str]:
        return list(self._change(value, expected_revision, remove=False)["symbols"])

    def remove(self, value: object, expected_revision: str | None = None) -> list[str]:
        return list(self._change(value, expected_revision, remove=True)["symbols"])

    def add_document(self, value: object, expected_revision: str) -> dict[str, object]:
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("If-Match 不能为空")
        return self._change(value, expected_revision, remove=False)

    def remove_document(self, value: object, expected_revision: str) -> dict[str, object]:
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("If-Match 不能为空")
        return self._change(value, expected_revision, remove=True)

