import asyncio
from pathlib import Path

import pytest

from shinar.local_speech.catalog import load_catalog
from shinar.local_speech.downloads import ModelStore
from shinar.local_speech.library import model_rows
from shinar.local_speech.service import LocalSpeechService
from shinar.local_speech.storage import atomic_json


def test_retired_sensevoice_branch_is_not_in_catalog() -> None:
    identifiers = {package.id for package in load_catalog()}
    assert "sensevoice-int8-20250909" not in identifiers
    assert {"sensevoice-int8-20240717", "sensevoice-fp32-20240717"} <= identifiers


@pytest.mark.parametrize("language", ["zh", "en", "ja", "ko", "yue"])
@pytest.mark.parametrize("scenario", ["conversation", "import"])
def test_retired_selection_does_not_restore_a_model_row(
    tmp_path: Path, language: str, scenario: str
) -> None:
    selection_path = tmp_path / "selections.json"
    atomic_json(
        selection_path,
        {f"{language}:{scenario}:stt": {"id": "sensevoice-int8-20250909"}},
    )
    saved_selection = selection_path.read_bytes()
    hardware = {
        "platform": "Windows",
        "architecture": "AMD64",
        "cpu": "test cpu",
        "logical_cpus": 8,
        "available_ram_bytes": 12 * 1024**3,
        "disk_free_bytes": 20 * 1024**3,
    }

    rows = model_rows(ModelStore(tmp_path), load_catalog(), language, scenario, hardware)

    assert all(row["id"] != "sensevoice-int8-20250909" for row in rows)
    assert not any(row["selected"] for row in rows)
    assert selection_path.read_bytes() == saved_selection


def test_retired_selection_requires_reselection(tmp_path: Path) -> None:
    atomic_json(
        tmp_path / "selections.json",
        {"en:conversation:stt": {"id": "sensevoice-int8-20250909"}},
    )
    service = LocalSpeechService(tmp_path)

    with pytest.raises(ValueError, match="speech_model_selection_stale"):
        asyncio.run(service.resolve("stt", "en"))
