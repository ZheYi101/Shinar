"""Current product paths and read compatibility for the former product name."""

import os
from pathlib import Path
import sys


def getenv(name: str, default: str | None = None) -> str | None:
    """An explicitly set SHINAR value wins, including an intentional empty value."""
    if name in os.environ:
        return os.environ[name]
    if name.startswith("SHINAR_"):
        return os.environ.get("LINGUALOOP_" + name[len("SHINAR_"):], default)
    return os.environ.get(name, default)


def canonical_environment(environment: dict[str, str]) -> dict[str, str]:
    result = dict(environment)
    for key, value in environment.items():
        if key.startswith("LINGUALOOP_"):
            result.setdefault("SHINAR_" + key[len("LINGUALOOP_"):], value)
    return result


def data_directory() -> Path:
    override = getenv("SHINAR_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    current, legacy = base / "Shinar", base / "LinguaLoop"
    current_state = any((current / name).is_file() for name in ("shinar.sqlite3", "ai-services.json", ".env"))
    old_state = any((legacy / name).is_file() for name in ("lingualoop.sqlite3", "ai-services.json", ".env"))
    return legacy if old_state and not current_state else current


def database_file(root: Path) -> Path:
    current, legacy = root / "shinar.sqlite3", root / "lingualoop.sqlite3"
    return legacy if legacy.is_file() and not current.exists() else current


def speech_directory() -> Path:
    override = getenv("SHINAR_SPEECH_DIR")
    if override:
        return Path(override).expanduser().absolute()
    data = getenv("SHINAR_DATA_DIR")
    if data:
        return Path(data).expanduser().absolute() / "speech"
    from shinar.configuration_location import load_speech_location

    saved = load_speech_location()
    if saved is not None:
        return saved
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    current, legacy = base / "Shinar/speech", base / "LinguaLoop/speech"
    return legacy if legacy.is_dir() and not current.exists() else current
