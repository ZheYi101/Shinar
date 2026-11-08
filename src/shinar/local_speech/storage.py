from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from shinar.configuration import speech_directory


def default_cache_root() -> Path:
    return speech_directory()


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if default is None or isinstance(value, type(default)) else default
    except (FileNotFoundError, ValueError, OSError):
        return default
