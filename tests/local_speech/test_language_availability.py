import asyncio
from pathlib import Path

import pytest

from lingualoop.local_speech import adapter_revision
from lingualoop.local_speech.benchmark import benchmark
from lingualoop.local_speech.catalog import ModelPackage, load_catalog
from lingualoop.local_speech.compute import runtime_version
from lingualoop.local_speech.downloads import ModelStore
from lingualoop.local_speech.library import model_rows
from lingualoop.local_speech.service import LocalSpeechService
from lingualoop.local_speech.storage import atomic_json

# Captured before adding the product language restriction, for cache compatibility.
LEGACY_MELO_FINGERPRINT = "1c4d84f48872f6e98b0b646d18fee2c80853cf9df0336414041f8e2422e5146f"


@pytest.mark.parametrize("scenario", ["conversation", "reading"])
def test_melo_onnx_keeps_chinese_installation_and_selection_but_hides_english(
    tmp_path: Path, scenario: str
) -> None:
    package = next(p for p in load_catalog() if p.id == "melo-zhen-onnx")
    store = ModelStore(tmp_path)
    model_path = store.model_path(package)
    for name in package.required_files:
        path = model_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    atomic_json(
        model_path / ".installed.json",
        {
            "fingerprint": LEGACY_MELO_FINGERPRINT,
            "files": {name: {"size": 7} for name in package.required_files},
        },
    )
    hardware = {
        "platform": "Windows",
        "architecture": "AMD64",
        "cpu": "test cpu",
        "logical_cpus": 8,
        "available_ram_bytes": 12 * 1024**3,
        "disk_free_bytes": 20 * 1024**3,
    }
    atomic_json(
        tmp_path / "reports/chinese.json",
        {
            "schema": 1,
            "language": "zh",
            "hardware": hardware,
            "model_fingerprints": {package.id: LEGACY_MELO_FINGERPRINT},
            "repeats": 5,
            "metrics": {
                "runtime_version": runtime_version(package),
                "provider": "cpu",
                "threads_per_model": 2,
                "sequential": {"tts": [{"first_pcm_ms": 100}] * 5},
            },
        },
    )
    selection_path = tmp_path / "selections.json"
    atomic_json(
        selection_path,
        {
            f"{language}:{scenario}:tts": {
                "id": package.id,
                "fingerprint": LEGACY_MELO_FINGERPRINT,
                "runtime_version": runtime_version(package),
                "adapter_revision": adapter_revision(package.adapter),
            }
            for language in ("zh", "en")
        },
    )
    saved_selection = selection_path.read_bytes()

    assert model_rows(store, [package], "en", scenario, hardware) == []
    chinese = model_rows(store, [package], "zh", scenario, hardware)
    assert len(chinese) == 1
    assert chinese[0]["installed"] and chinese[0]["measured"] and chinese[0]["selected"]
    assert selection_path.read_bytes() == saved_selection


def test_melo_onnx_old_english_choice_and_benchmark_are_rejected(tmp_path: Path) -> None:
    package = next(p for p in load_catalog() if p.id == "melo-zhen-onnx")
    atomic_json(
        tmp_path / "selections.json",
        {"en:conversation:tts": {"id": package.id, "fingerprint": package.fingerprint}},
    )
    with pytest.raises(ValueError, match="speech_model_selection_stale"):
        asyncio.run(LocalSpeechService(tmp_path).resolve("tts", "en"))
    with pytest.raises(ValueError, match="模型不支持所选语言"):
        benchmark(ModelStore(tmp_path), [package], "en")


def test_melo_english_models_remain_available_and_invalid_restrictions_are_rejected() -> None:
    packages = {p.id: p for p in load_catalog()}
    assert packages["melo-zhen-onnx"].available_languages == ["zh"]
    for identifier in ("melo-english-en", "melo-english-v3"):
        assert packages[identifier].available_languages == ["en"]
    invalid = packages["melo-zhen-onnx"].model_dump()
    invalid["disabled_languages"] = ["ja"]
    with pytest.raises(ValueError, match="禁用语言"):
        ModelPackage.model_validate(invalid)
