import subprocess
import sys

import pytest

from lingualoop.local_speech.benchmark import benchmark, percentile, summarize
from lingualoop.local_speech import RUNTIME_VERSION
from lingualoop.local_speech.catalog import load_catalog
from lingualoop.local_speech.downloads import ModelStore
from lingualoop.local_speech.hardware import admission
from lingualoop.local_speech.library import matching_reports, model_rows
from lingualoop.local_speech.storage import atomic_json


def hardware():
    return {
        "platform": "Windows",
        "architecture": "AMD64",
        "cpu": "test cpu",
        "logical_cpus": 8,
        "available_ram_bytes": 12 * 1024**3,
        "disk_free_bytes": 20 * 1024**3,
    }


def test_admission_uses_available_memory_and_no_unverified_candidates():
    package = load_catalog()[0]
    assert admission(package, hardware())[0]
    assert not admission(package, dict(hardware(), available_ram_bytes=1024**3))[0]
    assert not admission(package, dict(hardware(), available_ram_bytes=None))[0]
    assert not admission(load_catalog()[3], hardware())[0]


def test_percentile_keeps_slow_turn_and_summary_distinguishes_concurrent():
    rows = [{"first_pcm_ms": n} for n in [100, 110, 120, 130, 950]]
    assert percentile([r["first_pcm_ms"] for r in rows]) == 950
    metrics = summarize(
        {"sequential": {"tts": rows}, "concurrent": {"tts": [{"first_pcm_ms": 1200}]}}
    )
    assert metrics["sequential_tts_first_pcm_ms_p95"] == 950
    assert metrics["concurrent_tts_first_pcm_ms_p95"] == 1200


def test_model_recommendation_requires_matching_measurement(tmp_path, monkeypatch):
    catalog, store = load_catalog(), ModelStore(tmp_path)
    monkeypatch.setattr(store, "installed", lambda _: True)
    first = model_rows(store, catalog, "ja", "conversation", hardware())
    assert not any(r["recommended"] for r in first)
    model = catalog[0]
    report = {
        "schema": 1,
        "language": "zh",
        "model_fingerprints": {model.id: model.fingerprint},
        "hardware": hardware(),
        "repeats": 5,
        "metrics": {
            "runtime_version": RUNTIME_VERSION,
            "provider": "cpu",
            "threads_per_model": 2,
            "sequential": {
                "stt": [{"compute_ms": 200, "finalization_compute_ms": 200, "nonempty": True}]
            },
        },
    }
    atomic_json(tmp_path / "reports/test.json", report)
    assert any(
        r["recommended"] for r in model_rows(store, catalog, "zh", "conversation", hardware())
    )
    report["model_fingerprints"][model.id] = "stale"
    atomic_json(tmp_path / "reports/test.json", report)
    assert not any(
        r["recommended"] for r in model_rows(store, catalog, "zh", "conversation", hardware())
    )


def test_slow_tts_is_never_recommended_for_realtime(tmp_path, monkeypatch):
    catalog, store = load_catalog(), ModelStore(tmp_path)
    package = catalog[2]
    monkeypatch.setattr(store, "installed", lambda _: True)
    report = {
        "schema": 1,
        "language": "en",
        "model_fingerprints": {package.id: package.fingerprint},
        "hardware": hardware(),
        "repeats": 5,
        "metrics": {
            "runtime_version": RUNTIME_VERSION,
            "provider": "cpu",
            "threads_per_model": 2,
            "sequential": {"tts": [{"first_pcm_ms": 2000}]},
        },
    }
    atomic_json(tmp_path / "reports/slow.json", report)
    row = next(
        r
        for r in model_rows(store, catalog, "en", "conversation", hardware())
        if r["id"] == package.id
    )
    assert row["measured"] and not row["recommended"] and not row["withinRealtimeBudget"]


def test_benchmark_timeout_kills_child_and_releases_lock(tmp_path, monkeypatch):
    import lingualoop.local_speech.benchmark as module

    store, package = ModelStore(tmp_path), load_catalog()[2]
    monkeypatch.setattr(module, "detect_hardware", lambda _: hardware())
    monkeypatch.setattr(store, "installed", lambda _: True)
    original, children = subprocess.Popen, []

    def child(*args, **kwargs):
        if args and args[0][0] == "taskkill":
            return original(*args, **kwargs)
        process = original(
            [sys.executable, "-c", "import sys,time;sys.stdin.readline();time.sleep(30)"], **kwargs
        )
        children.append(process)
        return process

    monkeypatch.setattr(module.subprocess, "Popen", child)
    with pytest.raises(RuntimeError, match="超时"):
        benchmark(store, [package], "en", timeout=0.1)
    assert children[0].poll() is not None
    from lingualoop.local_speech.downloads import package_lock

    with package_lock(tmp_path, package):
        pass


def test_benchmark_rejects_missing_audio_and_unsupported_language(tmp_path, monkeypatch):
    import lingualoop.local_speech.benchmark as module

    monkeypatch.setattr(module, "detect_hardware", lambda _: hardware())
    with pytest.raises(ValueError, match="WAV"):
        benchmark(ModelStore(tmp_path), [load_catalog()[0]], "ja")
    with pytest.raises(ValueError, match="语言"):
        benchmark(ModelStore(tmp_path), [load_catalog()[2]], "ja")


def test_decoder_revision_invalidates_paired_measurements_and_selection(tmp_path, monkeypatch):
    catalog, store = load_catalog(), ModelStore(tmp_path)
    stt = next(p for p in catalog if p.adapter == "zipformer")
    tts = next(p for p in catalog if p.adapter == "kokoro")
    monkeypatch.setattr(store, "installed", lambda _: True)
    report = {
        "schema": 1,
        "language": "zh",
        "model_fingerprints": {p.id: p.fingerprint for p in (stt, tts)},
        "hardware": hardware(),
        "repeats": 5,
        "metrics": {
            "runtime_version": RUNTIME_VERSION,
            "provider": "cpu",
            "threads_per_model": 2,
            "sequential": {"stt": [{"compute_ms": 20, "nonempty": True}]},
        },
    }
    report_path = tmp_path / "reports/paired.json"
    atomic_json(report_path, report)
    assert not matching_reports(store, stt, "zh", hardware())
    assert not matching_reports(store, tts, "zh", hardware())
    report["adapter_revisions"] = {stt.id: 2, tts.id: 1}
    atomic_json(report_path, report)
    assert matching_reports(store, stt, "zh", hardware())
    assert matching_reports(store, tts, "zh", hardware())
    selection = {"id": stt.id, "fingerprint": stt.fingerprint, "runtime_version": RUNTIME_VERSION}
    selection_path = tmp_path / "selections.json"
    atomic_json(selection_path, {"zh:conversation:stt": selection})
    row = lambda: next(
        r for r in model_rows(store, catalog, "zh", "conversation", hardware()) if r["id"] == stt.id
    )
    assert row()["installed"] and not row()["selected"]
    selection["adapter_revision"] = 2
    atomic_json(selection_path, {"zh:conversation:stt": selection})
    assert row()["selected"]


def test_zipformer_factory_uses_fp32_decoder_from_mixed_package(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    directory = Path(__file__).resolve().parents[2] / "src/lingualoop/local_speech"
    spec = importlib.util.spec_from_file_location(
        "local_runtime_factory_test", directory / "runtime_worker.py"
    )
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    for name in (
        "encoder-test.int8.onnx",
        "decoder-test.int8.onnx",
        "decoder-test.onnx",
        "joiner-test.int8.onnx",
    ):
        (tmp_path / name).touch()
    monkeypatch.setitem(
        sys.modules,
        "sherpa_onnx",
        SimpleNamespace(OnlineRecognizer=SimpleNamespace(from_transducer=lambda **kwargs: kwargs)),
    )
    loaded = worker.load_model({"path": str(tmp_path), "adapter": "zipformer", "language": "zh"}, 2)
    assert Path(loaded["decoder"]).name == "decoder-test.onnx"
    assert Path(loaded["encoder"]).name == "encoder-test.int8.onnx"
    (tmp_path / "decoder-test.onnx").unlink()
    with pytest.raises(ValueError, match="不完整"):
        worker.load_model({"path": str(tmp_path), "adapter": "zipformer"}, 2)
