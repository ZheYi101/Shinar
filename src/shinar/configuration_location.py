"""Small, atomic preference for the optional speech-resource library location."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4


class SpeechStorageLocationError(RuntimeError):
    """Stable errors prevent unavailable external storage from falling back to C:."""


def location_file(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser().absolute()
    from shinar.configuration import data_directory

    return data_directory().absolute() / "storage-location.json"


def load_speech_location(config_path: Path | None = None) -> Path | None:
    path = location_file(config_path)
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise SpeechStorageLocationError("speech_storage_location_invalid") from error
    if (
        not isinstance(content, dict)
        or content.get("version") != 1
        or not isinstance(content.get("speech_directory"), str)
        or not content["speech_directory"]
    ):
        raise SpeechStorageLocationError("speech_storage_location_invalid")
    folder = Path(content["speech_directory"]).expanduser()
    if not folder.is_absolute():
        raise SpeechStorageLocationError("speech_storage_location_invalid")
    try:
        if not folder.is_dir() or not os.access(folder, os.R_OK | os.W_OK):
            raise SpeechStorageLocationError("speech_storage_location_unavailable")
        next(folder.iterdir(), None)
    except OSError as error:
        raise SpeechStorageLocationError("speech_storage_location_unavailable") from error
    return folder


def save_speech_location(location: Path, config_path: Path | None = None) -> None:
    folder = Path(location).expanduser().absolute()
    if not folder.is_dir():
        raise SpeechStorageLocationError("speech_storage_location_unavailable")
    path = location_file(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump({"version": 1, "speech_directory": str(folder)}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
