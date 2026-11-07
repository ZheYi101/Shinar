"""Per-user AI connection settings; Windows secrets are protected by DPAPI."""

from __future__ import annotations

import base64
import ctypes
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse


def _crypt(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise ValueError("ai_api_secret_storage_unavailable")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    raw = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming, outgoing = Blob(len(data), raw), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError("ai_api_secret_unreadable" if decrypt else "ai_api_secret_storage_failed")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


@dataclass(frozen=True)
class AIConnection:
    base_url: str
    reasoning_model: str
    dialogue_model: str
    api_key: str = field(repr=False)

    @classmethod
    def validated(cls, base_url: str, reasoning: str, dialogue: str, key: str) -> AIConnection:
        base_url, reasoning, dialogue, key = (s.strip() for s in (base_url, reasoning, dialogue, key))
        try:
            parsed = urlparse(base_url)
            valid = (
                parsed.scheme in {"https", "http"} and parsed.hostname and parsed.port != 0
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and not any(c.isspace() for c in base_url)
            )
        except ValueError:
            valid = False
        if not valid or len(base_url) > 2048:
            raise ValueError("ai_api_invalid_url")
        if not key or len(key) > 8192 or any(ord(c) < 32 for c in key):
            raise ValueError("ai_api_missing_key")
        if not reasoning or any(ord(c) < 32 for c in reasoning + dialogue) or max(len(reasoning), len(dialogue)) > 256:
            raise ValueError("ai_api_missing_model")
        base_url = base_url.rstrip("/")
        if parsed.path.rstrip("/") in {"", "/api"}:
            base_url += "/v1"
        return cls(base_url, reasoning, dialogue or reasoning, key)


class AIConfigurationStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AIConnection | None:
        if not self.path.exists():
            return None
        try:
            if self.path.stat().st_size > 128 * 1024:
                raise ValueError("ai_api_config_unreadable")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("version") != 1 or value.get("protection") != "windows-dpapi-user":
                raise ValueError("ai_api_config_unreadable")
            secret = _crypt(base64.b64decode(value["protected_key"], validate=True), decrypt=True)
            return AIConnection.validated(
                value["base_url"], value["reasoning_model"], value["dialogue_model"], secret.decode("utf-8")
            )
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise ValueError("ai_api_config_unreadable") from error

    def save(self, connection: AIConnection) -> None:
        # Encrypt before replacing anything; a failure preserves the prior settings.
        secret = _crypt(connection.api_key.encode("utf-8"))
        payload = {"version": 1, "protection": "windows-dpapi-user",
                   "base_url": connection.base_url, "reasoning_model": connection.reasoning_model,
                   "dialogue_model": connection.dialogue_model,
                   "protected_key": base64.b64encode(secret).decode("ascii")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".ai-settings-", delete=False) as output:
                name = Path(output.name)
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            name.replace(self.path)
        finally:
            if name is not None:
                name.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
