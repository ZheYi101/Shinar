"""The Shinar rename must not hide existing libraries, settings or speech assets."""

import os
from pathlib import Path

from shinar.configuration import data_directory, getenv, speech_directory
from shinar.infrastructure.sqlite_store import default_database_path


def isolate(monkeypatch, tmp_path):
    for key in tuple(os.environ):
        if key.startswith(("SHINAR_", "LINGUALOOP_")):
            monkeypatch.delenv(key)
    for key in ("LOCALAPPDATA", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    if os.name != "nt":
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def test_new_environment_values_win_and_empty_values_do_not_revive_old_keys(monkeypatch):
    monkeypatch.setenv("LINGUALOOP_STT_MODEL", "old-model")
    monkeypatch.delenv("SHINAR_STT_MODEL", raising=False)
    assert getenv("SHINAR_STT_MODEL") == "old-model"
    monkeypatch.setenv("SHINAR_STT_MODEL", "new-model")
    assert getenv("SHINAR_STT_MODEL") == "new-model"
    monkeypatch.setenv("SHINAR_STT_MODEL", "")
    assert getenv("SHINAR_STT_MODEL") == ""


def test_fresh_install_uses_shinar_directory_and_database(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    assert default_database_path() == tmp_path / "Shinar/shinar.sqlite3"
    assert speech_directory() == tmp_path / "Shinar/speech"
    assert not (tmp_path / "LinguaLoop").exists()


def test_legacy_library_and_its_epub_asset_directory_stay_together(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    legacy = tmp_path / "LinguaLoop"
    sources = legacy / "lingualoop.sqlite3.assets/sources"
    sources.mkdir(parents=True)
    database = legacy / "lingualoop.sqlite3"
    database.write_bytes(b"existing-library")
    asset = sources / "book.epub"
    asset.write_bytes(b"existing-epub")
    assert default_database_path() == database
    assert database.read_bytes() == b"existing-library"
    assert asset.read_bytes() == b"existing-epub"
    assert not (tmp_path / "Shinar").exists()


def test_new_library_wins_over_a_legacy_library(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    for folder, name in (("LinguaLoop", "lingualoop.sqlite3"), ("Shinar", "shinar.sqlite3")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).touch()
    assert default_database_path() == tmp_path / "Shinar/shinar.sqlite3"


def test_explicit_legacy_data_override_preserves_old_database_filename(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    old = tmp_path / "custom"
    old.mkdir()
    (old / "lingualoop.sqlite3").touch()
    monkeypatch.setenv("LINGUALOOP_DATA_DIR", str(old))
    assert default_database_path() == old / "lingualoop.sqlite3"
    monkeypatch.setenv("SHINAR_DATA_DIR", str(tmp_path / "new"))
    assert default_database_path() == tmp_path / "new/shinar.sqlite3"


def test_existing_speech_downloads_are_reused_without_copying(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    legacy = tmp_path / "LinguaLoop/speech"
    legacy.mkdir(parents=True)
    assert speech_directory() == legacy
    current = tmp_path / "Shinar/speech"
    current.mkdir(parents=True)
    assert speech_directory() == current


def test_saved_ai_configuration_keeps_its_original_data_root(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    legacy = tmp_path / "LinguaLoop"
    legacy.mkdir()
    (legacy / "ai-services.json").write_text("{}", encoding="utf-8")
    assert data_directory() == legacy
    assert not (tmp_path / "Shinar").exists()


def test_packaged_legacy_environment_file_is_found_without_rewriting(monkeypatch, tmp_path):
    from shinar.desktop.packaged import configuration_file

    isolate(monkeypatch, tmp_path)
    old = tmp_path / "LinguaLoop/.env"
    old.parent.mkdir()
    old.write_text("OPENAI_BASE_URL=https://example.invalid", encoding="utf-8")
    assert configuration_file() == old
    monkeypatch.setenv("SHINAR_CONFIG_FILE", str(tmp_path / "override.env"))
    assert configuration_file() == tmp_path / "override.env"


def test_old_speech_environment_remains_usable(monkeypatch):
    from shinar.providers.speech import SpeechSettings

    for field, value in (("BASE_URL", "https://example.invalid/v1"), ("API_KEY", "test-only"),
                         ("MODEL", "old-model"), ("VOICE", "old-voice")):
        monkeypatch.delenv("SHINAR_TTS_" + field, raising=False)
        monkeypatch.setenv("LINGUALOOP_TTS_" + field, value)
    settings = SpeechSettings.from_env("tts")
    assert settings.model == "old-model" and settings.voice == "old-voice"


def test_preferences_fall_back_per_key_and_write_only_to_shinar(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    import shinar.desktop.settings as module

    stores = {name: QSettings(str(tmp_path / f"{name}.ini"), QSettings.Format.IniFormat)
              for name in ("Shinar", "LinguaLoop")}
    stores["LinguaLoop"].setValue("themeMode", "dark")
    stores["LinguaLoop"].setValue("closeBehavior", "background")
    stores["Shinar"].setValue("themeMode", "light")
    monkeypatch.setattr(module, "QSettings", lambda organization, section: stores[organization])
    settings = module.ProductSettings("Desktop")
    assert settings.value("themeMode") == "light"
    assert settings.value("closeBehavior") == "background"
    settings.setValue("closeBehavior", "quit")
    settings.sync()
    assert stores["Shinar"].value("closeBehavior") == "quit"
    assert stores["LinguaLoop"].value("closeBehavior") == "background"


def test_child_environment_normalizes_old_names_without_forwarding_secrets(monkeypatch):
    from shinar.local_speech.runtime import child_environment

    monkeypatch.setenv("LINGUALOOP_CUDA_DLL_DIR", "old-cuda")
    monkeypatch.delenv("SHINAR_CUDA_DLL_DIR", raising=False)
    monkeypatch.setenv("LINGUALOOP_TTS_API_KEY", "must-not-be-forwarded")
    env = child_environment()
    assert env["SHINAR_CUDA_DLL_DIR"] == "old-cuda"
    assert "LINGUALOOP_TTS_API_KEY" not in env and "SHINAR_TTS_API_KEY" not in env
    monkeypatch.setenv("SHINAR_CUDA_DLL_DIR", "new-cuda")
    assert child_environment()["SHINAR_CUDA_DLL_DIR"] == "new-cuda"


def test_distribution_entrypoints_and_primary_package_are_renamed():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "shinar"
    assert project["scripts"] == {"shinar": "shinar.cli:main", "shinar-desktop": "shinar.desktop.app:main"}
    assert (root / "src/shinar/__init__.py").is_file()
    assert not (root / "src/lingualoop").exists()
    assert (root / "packaging/windows/Shinar.iss").is_file()


def test_standalone_model_adapters_do_not_require_the_host_package():
    import ast

    root = Path(__file__).resolve().parents[1] / "src/shinar/local_speech"
    for name in ("runtime_probe.py", "runtime_worker.py", "managed_runtime_probe.py", "sensevoice.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("shinar")
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("shinar") for alias in node.names)
