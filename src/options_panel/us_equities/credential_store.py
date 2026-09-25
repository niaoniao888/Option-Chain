"""Current-user Windows DPAPI storage. Never export credentials to the web UI."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


class CredentialError(RuntimeError):
    """An intentionally redacted error safe to display locally."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def credential_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise CredentialError("未找到当前 Windows 用户的本地数据目录。")
    return Path(root) / "USOptionsDashboard" / "alpaca-credentials.dpapi"


def _crypt(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise CredentialError("凭据加密仅支持 Windows 当前用户。")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; intentionally NOT CRYPTPROTECT_LOCAL_MACHINE.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CredentialError("Windows 用户凭据加密/解密失败，请用保存时的 Windows 用户重新配置。")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        if target.pbData:
            ctypes.memset(target.pbData, 0, target.cbData)
            kernel32.LocalFree(target.pbData)
        ctypes.memset(source_buffer, 0, len(data))


def _valid_pair(key: object, secret: object) -> bool:
    return all(isinstance(value, str) and 1 <= len(value) <= 512
               and not any(char.isspace() or ord(char) < 32 for char in value)
               for value in (key, secret))


def validate_credentials(api_key: object, secret: object) -> None:
    if not _valid_pair(api_key, secret):
        raise CredentialError("API Key 和 Secret 须为 1–512 个字符，且不能包含空白或控制字符。")


def save_credentials(api_key: str, secret: str, validation: dict, *, path: Path | None = None) -> None:
    """Persist only after this configuration attempt passed the sample probe."""
    validate_credentials(api_key, secret)
    if not isinstance(validation, dict) or validation.get("ok") is not True:
        raise CredentialError("免费接口样本尚未验证通过，未保存凭据。")
    payload = json.dumps({"version": 1, "sample_verified": True,
                          "api_key": api_key, "secret": secret}, separators=(",", ":")).encode("utf-8")
    encrypted = _crypt(payload)
    target = path or credential_path()
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".alpaca-", suffix=".tmp", dir=target.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError:
        raise CredentialError("无法保存当前用户的加密配置，原配置保持不变。") from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def load_credentials(*, path: Path | None = None) -> tuple[str, str] | None:
    env_key = os.environ.get("ALPACA_API_KEY")
    env_secret = os.environ.get("ALPACA_API_SECRET")
    if env_key is not None or env_secret is not None:
        if env_key is None or env_secret is None:
            raise CredentialError("ALPACA_API_KEY 与 ALPACA_API_SECRET 必须同时配置。")
        validate_credentials(env_key, env_secret)
        return env_key, env_secret
    if os.name != "nt":
        return None
    target = path or credential_path()
    try:
        with target.open("rb") as stream:
            encrypted = stream.read(65537)
        if not encrypted or len(encrypted) > 65536:
            raise CredentialError("加密配置损坏，请重新配置。")
        record = json.loads(_crypt(encrypted, decrypt=True))
        if (not isinstance(record, dict) or record.get("version") != 1
                or record.get("sample_verified") is not True
                or not _valid_pair(record.get("api_key"), record.get("secret"))):
            raise CredentialError("加密配置格式无效，请重新配置。")
        return record["api_key"], record["secret"]
    except FileNotFoundError:
        return None
    except CredentialError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        raise CredentialError("无法读取当前用户的加密配置，请重新配置。") from None
