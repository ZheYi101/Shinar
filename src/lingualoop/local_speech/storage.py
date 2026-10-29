from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4


def default_cache_root() -> Path:
    override = os.getenv("LINGUALOOP_SPEECH_DIR")
    if override:
        return Path(override).expanduser().absolute()
    data = os.getenv("LINGUALOOP_DATA_DIR")
    if data:
        return Path(data).expanduser().absolute() / "speech"
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "LinguaLoop" / "speech"


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
