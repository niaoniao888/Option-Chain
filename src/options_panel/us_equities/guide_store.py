from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


MAX_SECTIONS = 20
MAX_TOPICS_PER_SECTION = 60
MAX_TOTAL_TOPICS = 300
MAX_ID_LENGTH = 64
MAX_TITLE_LENGTH = 100
MAX_BODY_LENGTH = 6000
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_SECTIONS = [{"id": "personal", "title": "个人笔记", "topics": [
    {"id": "notes", "title": "我的观察", "body": "在这里记录自己的筛选口径、观察和复盘。"},
]}]


class GuideError(ValueError):
    pass


class GuideConflictError(GuideError):
    pass


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _plain_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise GuideError(f"{field} 必须是文本")
    if value != value.strip() or not value:
        raise GuideError(f"{field} 不能为空或包含首尾空白")
    if len(value) > maximum:
        raise GuideError(f"{field} 超过 {maximum} 个字符")
    # Inequalities are valid text. The UI renders these fields with textContent,
    # so even HTML-shaped text is displayed literally, never interpreted as HTML.
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise GuideError(f"{field} 包含不可见控制字符")
    return value


def validate_sections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_SECTIONS:
        raise GuideError(f"sections 必须是 1 至 {MAX_SECTIONS} 个分类的数组")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    total_topics = 0
    for section_index, section in enumerate(value):
        if not isinstance(section, dict) or set(section) != {"id", "title", "topics"}:
            raise GuideError(f"sections[{section_index}] 结构无效")
        section_id = _plain_text(section["id"], f"sections[{section_index}].id", MAX_ID_LENGTH)
        if not ID_PATTERN.fullmatch(section_id):
            raise GuideError(f"sections[{section_index}].id 格式无效")
        if section_id in seen:
            raise GuideError(f"id 重复：{section_id}")
        seen.add(section_id)
        title = _plain_text(section["title"], f"sections[{section_index}].title", MAX_TITLE_LENGTH)
        topics = section["topics"]
        if not isinstance(topics, list) or not topics or len(topics) > MAX_TOPICS_PER_SECTION:
            raise GuideError(f"sections[{section_index}].topics 数量无效")
        normalized_topics: list[dict[str, str]] = []
        for topic_index, topic in enumerate(topics):
            if not isinstance(topic, dict) or set(topic) != {"id", "title", "body"}:
                raise GuideError(f"sections[{section_index}].topics[{topic_index}] 结构无效")
            prefix = f"sections[{section_index}].topics[{topic_index}]"
            topic_id = _plain_text(topic["id"], f"{prefix}.id", MAX_ID_LENGTH)
            if not ID_PATTERN.fullmatch(topic_id):
                raise GuideError(f"{prefix}.id 格式无效")
            if topic_id in seen:
                raise GuideError(f"id 重复：{topic_id}")
            seen.add(topic_id)
            normalized_topics.append({
                "id": topic_id,
                "title": _plain_text(topic["title"], f"{prefix}.title", MAX_TITLE_LENGTH),
                "body": _plain_text(topic["body"], f"{prefix}.body", MAX_BODY_LENGTH),
            })
        total_topics += len(normalized_topics)
        if total_topics > MAX_TOTAL_TOPICS:
            raise GuideError(f"条目总数不能超过 {MAX_TOTAL_TOPICS}")
        normalized.append({"id": section_id, "title": title, "topics": normalized_topics})
    return normalized


def _revision(updated_at: str, sections: list[dict[str, Any]]) -> str:
    content = json.dumps(
        {"updated_at": updated_at, "sections": sections},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def make_document(sections: Any, updated_at: str | None = None) -> dict[str, Any]:
    normalized = validate_sections(sections)
    timestamp = updated_at or datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if not isinstance(timestamp, str) or not timestamp:
        raise GuideError("updated_at 无效")
    return {"revision": _revision(timestamp, normalized), "updated_at": timestamp, "sections": normalized}


class GuideStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

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

    @staticmethod
    def _decode(data: bytes) -> dict[str, Any]:
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GuideError("说明文件不是有效 JSON") from exc
        if not isinstance(raw, dict) or set(raw) != {"revision", "updated_at", "sections"}:
            raise GuideError("说明文件结构无效")
        document = make_document(raw["sections"], raw["updated_at"])
        if raw["revision"] != document["revision"]:
            raise GuideError("说明文件版本校验失败")
        return document

    def _load_unlocked(self) -> dict[str, Any]:
        errors: list[Exception] = []
        for candidate in (self.path, self.backup_path):
            try:
                return self._decode(candidate.read_bytes())
            except (OSError, GuideError) as exc:
                errors.append(exc)
        if all(isinstance(error, OSError) for error in errors):
            return make_document(DEFAULT_SECTIONS, "built-in")
        raise GuideError(f"说明内容不可用：{errors[-1]}")

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
    def _encode(document: dict[str, Any]) -> bytes:
        return (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")

    def get(self) -> dict[str, Any]:
        with self._locked():
            return self._load_unlocked()

    def update(self, sections: Any, expected_revision: str) -> dict[str, Any]:
        if not isinstance(expected_revision, str) or not expected_revision:
            raise GuideError("If-Match 不能为空")
        normalized = validate_sections(sections)
        with self._locked():
            current = self._load_unlocked()
            if expected_revision != current["revision"]:
                raise GuideConflictError("说明内容已被其他窗口更新")
            updated = make_document(normalized)
            self._atomic_write(self.backup_path, self._encode(current))
            self._atomic_write(self.path, self._encode(updated))
            return updated

