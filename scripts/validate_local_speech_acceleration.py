"""Offline developer smoke using the fixed evaluation assets, never the user's cache."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path

import httpx

from shinar.local_speech import adapter_revision
from shinar.local_speech.benchmark import benchmark
from shinar.local_speech.catalog import load_catalog
from shinar.local_speech.compute import ComputeSettings, save_compute, runtime_version
from shinar.local_speech.downloads import ModelStore
from shinar.local_speech.resources import resource_snapshot
from shinar.local_speech.runtime import probe_runtime
from shinar.local_speech.service import LocalSpeechService
from shinar.local_speech.storage import atomic_json


class FileStream(httpx.SyncByteStream):
    def __init__(self, path: Path):
        self.path = path

    def __iter__(self):
        with self.path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                yield chunk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument(
        "--python", type=Path, required=True, help="Already prepared fixed-version interpreter"
    )
    parser.add_argument(
        "--cpu-python", type=Path, required=True, help="CPU sherpa-onnx/core 1.13.8 interpreter"
    )
    parser.add_argument("--cuda-dll-dir", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("build/local-speech-settings-validation")
    )
    args = parser.parse_args()
    root, evaluation = args.output.resolve(), args.evaluation_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.cuda_dll_dir:
        os.environ["SHINAR_CUDA_DLL_DIR"] = str(args.cuda_dll_dir.resolve())
    python = str(args.python.resolve())
    cpu_python = str(args.cpu_python.resolve())
    probes = {"cuda": probe_runtime(python, "cuda"), "cpu": probe_runtime(cpu_python, "cpu")}
    packages = {p.id: p for p in load_catalog()}
    requested = [
        packages[k]
        for k in ("sensevoice-fp32-20240717", "reazonspeech-k2-v2-int8", "piper-lessac-medium")
    ]
    sources = {}
    followup = evaluation / "strict/followup-2026-10-29"
    for package in requested:
        for asset in package.files:
            if package.adapter == "sensevoice-ort":
                path = (
                    followup / "models/sv2024/model.onnx"
                    if asset.path == "model.onnx"
                    else evaluation
                    / "strict/candidate_models/sensevoice-original-20240717/tokens.txt"
                )
            elif package.adapter == "reazon":
                path = followup / "models/reazon" / asset.path
            else:
                path = evaluation / "vits-piper-en_US-lessac-medium.tar.bz2"
            if not path.is_file():
                raise ValueError("Missing fixed evaluation asset: " + path.name)
            sources[asset.url] = path

    def respond(request):
        path = sources[str(request.url)]
        return httpx.Response(
            200, headers={"Content-Length": str(path.stat().st_size)}, stream=FileStream(path)
        )

    store = ModelStore(root / "smoke-cache")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        for package in requested:
            if not store.installed(package):
                store.install(package, client=client)
            store.verify(package)
    corpus = evaluation / "strict/corpus"
    reports, selections = {}, {}
    for package, language, device in (
        (requested[0], "ja", "cuda"),
        (requested[1], "ja", "cpu"),
        (requested[2], "en", "cpu"),
    ):
        wav = next((corpus / language).glob("*.wav")) if package.task == "stt" else None
        report = benchmark(
            store,
            [package],
            language,
            wav=wav,
            repeats=3,
            python=python if device == "cuda" else cpu_python,
            devices={package.id: device},
        )
        reports[package.id] = report
        selections[f"{language}:conversation:{package.task}"] = {
            "id": package.id,
            "fingerprint": package.fingerprint,
            "runtime_version": runtime_version(package),
            "adapter_revision": adapter_revision(package.adapter),
        }
    atomic_json(store.root / "selections.json", selections)
    selections["ja:conversation:stt"] = {
        "id": requested[0].id,
        "fingerprint": requested[0].fingerprint,
        "runtime_version": runtime_version(requested[0]),
        "adapter_revision": adapter_revision(requested[0].adapter),
    }
    atomic_json(store.root / "selections.json", selections)
    import shinar.local_speech.service as service_module

    service_module.runtime_python = lambda root, device: python if device == "cuda" else cpu_python
    service_module.runtime_status = lambda *args: {
        "prepared": True
    }  # explicitly probed runtimes above
    messages = []
    service = LocalSpeechService(store.root, status=messages.append)

    async def run():
        save_compute(store.root, ComputeSettings(local_stt=True, local_tts=True))
        audio = base64.b64encode(next((corpus / "ja").glob("*.wav")).read_bytes()).decode()
        before = resource_snapshot([])
        first = await service._request("stt", "ja", audio=audio)
        warm = await service._request("stt", "ja", audio=audio)
        synthesis = await service.synthesize("I was not responsible for that decision.", "en")
        (root / "piper-lessac-live-route.wav").write_bytes(synthesis)
        resident = resource_snapshot(service.pids, service.gpu_pids)
        pids = service.pids
        await service.release()
        released = resource_snapshot(service.pids)
        assert not service.pids and first["device"] == warm["device"] == "cuda"
        assert first["cold"] and not warm["cold"] and len(synthesis) > 44
        # Zero idle policy must leave no resident child after returning audio.
        save_compute(store.root, ComputeSettings(local_tts=True, idle_seconds=0))
        await service.synthesize("The model is released after this sentence.", "en")
        assert not service.pids
        await service.close()
        return {
            "gpu_first": {k: v for k, v in first.items() if k != "text"},
            "gpu_warm": {k: v for k, v in warm.items() if k != "text"},
            "pids_during": pids,
            "resources_before": before,
            "resources_resident": resident,
            "resources_released": released,
            "manual_and_immediate_release_verified": True,
        }

    result = {
        "runtime_probes": probes,
        "reports": reports,
        "service": asyncio.run(run()),
        "messages": messages,
        "fresh_gpu_dependency_download_verified": False,
        "cpu_python": cpu_python,
        "scope": "Existing runtimes and evaluation assets; not live mic/RTC/audible validation",
    }
    atomic_json(root / "runtime-report.json", result)
    print(
        json.dumps(
            {
                "report": str(root / "runtime-report.json"),
                "gpu_warm_compute_ms": result["service"]["gpu_warm"]["compute_ms"],
            }
        )
    )


if __name__ == "__main__":
    main()
