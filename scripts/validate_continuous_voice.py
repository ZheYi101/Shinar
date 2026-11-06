"""Real local models + RTC + VAD, synthetic devices and Mock dialogue; zero paid calls."""
# ruff: noqa: E402

import argparse
import asyncio
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4
import wave
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lingualoop.application.continuous_voice import ContinuousConversation
from lingualoop.application.learning_workbench import LearningWorkbench
from lingualoop.core.domain import LanguageEnum
from lingualoop.infrastructure import SQLiteStore
from lingualoop.local_speech.profiles import LocalSpeechProfile
from lingualoop.local_speech.service import LocalSpeechService
from lingualoop.providers.mock import MockLearningLLMProvider
from lingualoop.realtime.audio_process import AudioSessionProcess
from lingualoop.realtime.continuous_assets import vad_path
from lingualoop.realtime.pcm import DeviceFormat, PCM48, PcmConverter


class StreamingDialogue(MockLearningLLMProvider):
    def __init__(self, language, played):
        self.language, self.played, self.calls = language, played, 0

    async def stream_reply(self, **kwargs):
        self.calls += 1
        first, second = {
            "zh": ("我明白你的意思。", "我们继续聊吧。"),
            "en": ("That makes sense. ", "Tell me more."),
            "ja": ("なるほど。", "もう少し教えてください。"),
        }[self.language]
        yield first
        # Deliberately slow Mock stream proves audio can precede completed text.
        async with asyncio.timeout(60):
            await self.played.wait()
        await asyncio.sleep(0.1)
        yield second


async def wait_until(predicate, timeout=90):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def run_case(case, runtime, output, speech_cache=None):
    from livekit import rtc

    service = LocalSpeechService(speech_cache or output / "speech")
    if speech_cache is None:
        for task in ("stt", "tts"):
            service.register_prepared(LocalSpeechProfile(**case[task]))
    played = asyncio.Event()
    provider = StreamingDialogue(case["language"], played)
    work = LearningWorkbench(provider, event_store=SQLiteStore(output / "learning.sqlite3"))
    target = {"zh": LanguageEnum.CHINESE, "en": LanguageEnum.ENGLISH, "ja": LanguageEnum.JAPANESE}[
        case["language"]
    ]
    await work.load_material(
        title="Continuous voice fixture",
        content="Mira waited. Ren left.",
        source_language=LanguageEnum.ENGLISH,
        target_language=target,
        native_language=LanguageEnum.CHINESE,
        learner_level="A2",
    )
    await work.start_session()
    tasks, results, failures, text_done = set(), [], [], []
    first_playback = None
    transport_counts = Counter()
    phase = "prepare"
    runner = process = None
    started = perf_counter()

    def spawn(operation):
        task = asyncio.create_task(operation)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    def application_event(kind, generation, value):
        if kind in {
            "recognizing",
            "confirmed",
            "result",
            "recognition_failed",
            "reply_failed",
            "claim_rejected",
        }:
            print(
                json.dumps(
                    {
                        "case": case["name"],
                        "event": kind,
                        "reason": value if kind == "claim_rejected" else None,
                    }
                ),
                flush=True,
            )
        if kind == "result":
            result, timings = value
            results.append(
                {
                    "text_status": result.text_status,
                    "speech_status": result.speech_status,
                    "segments": result.segment_count,
                    "timings_ms": timings,
                }
            )
        elif kind == "text_completed":
            text_done.append(perf_counter())
        elif kind in {"recognition_failed", "reply_failed"}:
            failures.append(kind)
            report["failure_details"] = value

    async def playback(header, data):
        nonlocal first_playback
        first_playback = first_playback or perf_counter()
        played.set()
        await process.send("rendered", data, generation=header["generation"], delay_ms=60)
        await process.send("credit")

    def transport_event(header, data):
        kind = header["kind"]
        transport_counts[kind] += 1
        if kind == "playback":
            spawn(playback(header, data))
        elif kind == "input_started":
            spawn(runner.input_started(header["utterance"], header["revision"]))
        elif kind == "near_speech":
            spawn(runner.interrupt("user_interruption"))
        elif kind == "output_drained":
            runner.audio_started = False
            if runner.turn_id:
                work.record_speech_delivery(runner.turn_id, "completed")
        elif kind == "utterance":
            spawn(
                runner.receive(
                    header, data, None, service.provider("stt"), service.provider("tts"), True
                )
            )
        elif kind in {
            "disconnected",
            "input_gap",
            "input_limit",
            "output_overflow",
            "operation_failed",
        }:
            failures.append(kind)

    from lingualoop.local_speech.installation import managed_status

    runtime_status = managed_status(runtime, "rtc-cpu")
    if speech_cache and not runtime_status.get("prepared"):
        raise RuntimeError("Prepare continuous components in audio settings first")
    process = AudioSessionProcess(
        uuid4().hex,
        transport_event,
        python=runtime_status.get("python") if runtime_status.get("prepared") else None,
    )
    runner = ContinuousConversation(work, process, application_event)
    report = {
        "case": case["name"],
        "real_rtc": True,
        "real_local_models": True,
        "synthetic_devices": True,
        "human_acceptance": False,
        "paid_model_calls": 0,
        "selection_mode": "normal_settings" if speech_cache else "explicit_prepared_profile",
    }
    try:
        stt, tts = (
            await service.provider("stt").bind(case["language"]),
            await service.provider("tts").bind(case["language"]),
        )
        await stt.prepare()
        await tts.prepare()
        report["prepare_metrics"] = dict(service.last_metrics)
        phrase = {
            "zh": "我觉得她改变了主意",
            "en": "I think she changed her mind",
            "ja": "彼女は考えを変えたと思います",
        }[case["language"]]
        audio = await tts.synthesize(phrase)
        with wave.open(io.BytesIO(audio)) as wav:
            source = DeviceFormat(wav.getframerate(), wav.getnchannels(), "int16")
            converter = PcmConverter(source, PCM48, rtc)
            pcm = converter.push(wav.readframes(wav.getnframes())) + converter.flush()
        fmt = asdict(PCM48)
        phase = "connect"
        report["connection"] = await process.start(
            {
                "cache": str(runtime / "sfu"),
                "vad": str(vad_path(runtime)),
                "pause_ms": 650,
                "input_format": fmt,
                "output_format": fmt,
            }
        )
        await process.request("resume")
        phase = "three_turns"
        for i in range(3):
            played.clear()
            before = len(results)

            # Silence continues while STT/TTS run, exactly as an open microphone.
            async def microphone():
                for offset in range(0, len(pcm), 1920):
                    data = pcm[offset : offset + 1920]
                    await process.send("capture", data.ljust(1920, b"\0"), capture_delay_ms=20)
                    await asyncio.sleep(0.02)
                while True:
                    await process.send("capture", b"\0" * 1920, capture_delay_ms=20)
                    await asyncio.sleep(0.02)

            mic = asyncio.create_task(microphone())
            try:
                await wait_until(lambda: len(results) > before or failures)
                await wait_until(lambda: runner.reply_task is None or failures)
            finally:
                mic.cancel()
                await asyncio.gather(mic, return_exceptions=True)
            if failures:
                raise RuntimeError("continuous_case_failed")
            if any(
                r["text_status"] != "completed" or r["speech_status"] != "completed"
                for r in results
            ):
                raise RuntimeError("continuous_reply_failed")
            if i < 2:
                await process.request("mute")
                await process.request("resume")
        report.update(
            turns=len(results),
            mock_dialogue_calls=provider.calls,
            results=results,
            first_playback_before_text_complete=bool(text_done and first_playback < text_done[0]),
            local_compute=dict(service.last_metrics),
            failures=failures,
            total_ms=(perf_counter() - started) * 1000,
            passed=all(
                r["text_status"] == "completed" and r["speech_status"] == "completed"
                for r in results
            ),
        )
        assert (
            len(results) >= 3 and report["passed"] and report["first_playback_before_text_complete"]
        )
    except Exception as exc:
        report.update(
            passed=False,
            phase=phase,
            error_type=type(exc).__name__,
            failures=failures,
            results=results,
            total_ms=(perf_counter() - started) * 1000,
        )
        try:
            report["audio_stats"] = await process.request("stats")
        except Exception:
            pass
    finally:
        report["transport_counts"] = dict(transport_counts)
        (output / "result-before-cleanup.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await runner.close()
        await process.close()
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()
        await work.aclose()
        report["audio_process_exit"] = process.process.returncode if process.process else None
        report["model_processes_remaining"] = service.pids
    return report


async def main(args):
    config = (
        (json.loads(args.profiles.read_text(encoding="utf-8")))
        if args.profiles
        else [{"name": name, "language": name} for name in args.cases]
    )
    root = (ROOT / "build" / "continuous-voice" / ("integration-" + uuid4().hex)).resolve()
    root.mkdir(parents=True)
    reports = []
    for name in args.cases:
        case = next(c for c in config if c["name"] == name)
        folder = root / name
        folder.mkdir()
        report = await run_case(
            case,
            args.runtime_root.resolve(),
            folder,
            args.speech_cache.resolve() if args.speech_cache else None,
        )
        reports.append(report)
        (root / "report.json").write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "case": name,
                    "passed": report.get("passed"),
                    "phase": report.get("phase"),
                    "report": str(root / "report.json"),
                }
            ),
            flush=True,
        )
    return 0 if all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--profiles", type=Path)
    source.add_argument(
        "--speech-cache",
        type=Path,
        help="Use ordinary GUI selections and measured reports; no register_prepared",
    )
    parser.add_argument(
        "--runtime-root", type=Path, default=ROOT / "build/continuous-voice/runtime"
    )
    parser.add_argument("--cases", nargs="+", default=["zh", "en", "ja"])
    raise SystemExit(asyncio.run(main(parser.parse_args())))
