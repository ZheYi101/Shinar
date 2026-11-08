"""Measure real resident workers across different interpreter/runtime families."""

import asyncio
import base64
from datetime import datetime, timezone
import time

from . import adapter_revision
from .benchmark import summarize
from .compute import runtime_version
from .downloads import DownloadCancelled
from .model_profile import measurement_identity
from .service import LocalSpeechService
from .storage import atomic_json


def benchmark_profiles(
    store, packages, language, profiles, *, wav, repeats, threads, cancel, timeout, hardware
):
    return asyncio.run(_benchmark_profiles(store, packages, language, profiles, wav,
                                          repeats, threads, cancel, timeout, hardware))


async def _benchmark_profiles(store, packages, language, profiles, wav, repeats, threads, cancel, timeout, hardware):
    service = LocalSpeechService(store.root)
    started = time.perf_counter()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_dir = store.root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = "--".join(p.id for p in packages) + "--" + language + "--" + stamp
    preview = report_dir / (stem + ".wav")
    audio = __import__("pathlib").Path(wav).read_bytes()
    text = {
        "en": "The train arrived early. I did not miss it.",
        "ja": "駅に着きました。電車には遅れませんでした。",
        "zh": "列车提前到了，我没有错过。",
    }[language]
    peak = 0

    async def one(package, save=False):
        nonlocal peak
        profile = profiles[package.id]
        result = (
            await service.execute(profile, audio=audio)
            if package.task == "stt"
            else await service.execute(profile, text=text)
        )
        if save and "audio" in result:
            preview.write_bytes(base64.b64decode(result["audio"], validate=True))
        try:
            import psutil

            peak = max(peak, sum(psutil.Process(pid).memory_info().rss for pid in service.pids))
        except (ImportError, OSError):
            pass
        return {k: v for k, v in result.items() if k not in {"audio", "text", "hypothesis"}}

    async def measure():
        cold, warmup = {}, {}
        sequential = {"stt": [], "tts": []}
        concurrent = {"stt": [], "tts": []}
        for p in packages:
            warmup[p.task] = await one(p, save=True)
            cold[p.id] = warmup[p.task].get("load_ms", 0)
        for _ in range(repeats):
            for p in packages:
                sequential[p.task].append(await one(p))
        for _ in range(repeats):
            rows = await asyncio.gather(*(one(p) for p in packages))
            for p, row in zip(packages, rows):
                concurrent[p.task].append(row)
        return dict(
            sequential=sequential,
            concurrent=concurrent,
            warmup=warmup,
            cold_load_ms=cold,
            peak_process_rss_bytes=peak,
            peak_memory_kind="sampled_worker_sum",
            runtime_versions={p.id: runtime_version(p) for p in packages},
            devices={p.id: profiles[p.id].spec["provider"] for p in packages},
            gpu_index=next(
                (
                    profiles[p.id].spec["gpu_index"]
                    for p in packages
                    if profiles[p.id].spec["provider"] == "cuda"
                ),
                None,
            ),
            threads_per_model=threads,
            wall_ms=(time.perf_counter() - started) * 1000,
            scope="resident_compute_only; no microphone or audible playback",
        )

    task = asyncio.create_task(measure())
    try:
        deadline = time.monotonic() + timeout
        while not task.done():
            if cancel and cancel.is_set():
                raise DownloadCancelled("speech_benchmark_cancelled")
            if time.monotonic() >= deadline:
                raise RuntimeError("speech_benchmark_timeout")
            await asyncio.sleep(0.05)
        metrics = await task
        report = _paired_report(store, packages, language, profiles, hardware, metrics, repeats, preview)
        atomic_json(report_dir / (stem + ".json"), report)
        return report
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service.close()




def _paired_report(store, packages, language, profiles, hardware, metrics, repeats, preview):
    report = dict(
        schema=1,
        timestamp=datetime.now(timezone.utc).isoformat(),
        language=language,
        hardware=hardware,
        model_fingerprints={p.id: p.fingerprint for p in packages},
        adapter_revisions={p.id: adapter_revision(p.adapter) for p in packages},
        model_identities={
            p.id: measurement_identity(
                store.root,
                p,
                profiles[p.id].spec["provider"],
                profiles[p.id].spec.get("voice_id"),
            )
            for p in packages
        },
        metrics=metrics,
        summary=summarize(metrics),
        repeats=repeats,
        preview=str(preview),
        accuracy_evaluated=False,
        live_chain_evaluated=False,
    )
    return report
