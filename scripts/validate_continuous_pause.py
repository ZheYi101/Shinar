"""Real RTC/VAD/STT pause probe, synthetic input, isolated history and Mock dialogue."""

import argparse
import asyncio
from dataclasses import asdict
import io
import json
from pathlib import Path
from uuid import uuid4
import wave

from lingualoop.application import LearningWorkbench
from lingualoop.application.continuous_voice import ContinuousConversation
from lingualoop.core.domain import LanguageEnum
from lingualoop.infrastructure import SQLiteStore
from lingualoop.local_speech.installation import managed_status
from lingualoop.local_speech.samples import benchmark_audio
from lingualoop.local_speech.service import LocalSpeechService
from lingualoop.providers import MockLearningLLMProvider
from lingualoop.realtime.audio_process import AudioSessionProcess
from lingualoop.realtime.continuous_assets import vad_path
from lingualoop.realtime.pcm import DeviceFormat, PCM48, PcmConverter


async def probe(args):
    from livekit import rtc

    args.output.mkdir(parents=True, exist_ok=False)
    status = managed_status(args.runtime_root, "rtc-cpu")
    assert status.get("prepared"), "Prepare continuous components first"
    service = LocalSpeechService(args.speech_cache)
    work = LearningWorkbench(
        MockLearningLLMProvider(), event_store=SQLiteStore(args.output / "learning.sqlite3")
    )
    tasks, paused, finals, faults = set(), [], [], []
    process = runner = microphone = None
    report = dict(real_rtc=True, real_vad=True, real_stt=True, synthetic_input=True,
                  microphone_open=False, paid_model_calls=0, human_acceptance=False)
    allow_submit = False

    def spawn(operation):
        task = asyncio.create_task(operation)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def transport(header, data):
        kind = header["kind"]
        if kind == "input_paused":
            paused.append((header, data))
        elif kind == "input_started":
            spawn(runner.input_started(header["utterance"], header["revision"]))
        elif kind == "utterance":
            finals.append((header, data))
            if allow_submit:
                spawn(runner.receive(header, data, None, stt, None, False))
        elif kind in {"input_gap", "input_limit", "disconnected", "operation_failed"}:
            faults.append(kind)

    async def wait(predicate):
        async with asyncio.timeout(45):
            while not predicate():
                assert not faults, faults
                await asyncio.sleep(.02)

    async def feed(pcm, *, silence=False):
        for offset in range(0, len(pcm), 1920):
            await process.send("capture", pcm[offset:offset + 1920].ljust(1920, b"\0"))
            await asyncio.sleep(.02)
        while silence:
            await process.send("capture", bytes(1920))
            await asyncio.sleep(.02)

    try:
        await work.load_material(
            title="Pause probe", content="Mira waited. Ren left.",
            source_language=LanguageEnum.ENGLISH, target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE, learner_level="A2",
        )
        await work.start_session()
        stt = await service.provider("stt").bind("en")
        await stt.prepare()
        with benchmark_audio("en") as sample, wave.open(str(sample), "rb") as audio:
            converter = PcmConverter(DeviceFormat(16000, 1, "int16"), PCM48, rtc)
            pcm = converter.push(audio.readframes(audio.getnframes())) + converter.flush()
        process = AudioSessionProcess(uuid4().hex, transport, python=status["python"])
        runner = ContinuousConversation(work, process, lambda *event: None)
        fmt = asdict(PCM48)
        await process.start(dict(cache=str(args.runtime_root / "sfu"),
                                 vad=str(vad_path(args.runtime_root)), pause_ms=650,
                                 input_format=fmt, output_format=fmt))
        await process.request("resume")
        cut = 48000 * 2 * 2
        await feed(pcm[:cut])
        runner.input_allowed = False
        await runner.cancel_input()
        result = await process.request("pause", pause_id="pause-probe")
        assert result["has_input"] and len(paused) == 1
        snapshot = paused[0]
        before = len(finals)
        await asyncio.sleep(1.1)
        assert len(finals) == before and len(work.session.messages) == 1
        await process.request("resume", preserve_input=True)
        runner.input_allowed = True
        # Silence on resume must not submit the paused fragment.
        await feed(bytes(48000 * 2))
        assert len(finals) == before and len(work.session.messages) == 1
        allow_submit = True
        microphone = asyncio.create_task(feed(pcm[cut:], silence=True))
        await wait(lambda: len(work.session.messages) == 3 and runner.reply_task is None)
        final = finals[-1]
        assert final[0]["utterance"] == snapshot[0]["utterance"]
        assert final[0]["revision"] > snapshot[0]["revision"]
        with wave.open(io.BytesIO(snapshot[1]), "rb") as audio:
            original = audio.readframes(audio.getnframes())
        with wave.open(io.BytesIO(final[1]), "rb") as audio:
            merged = audio.readframes(audio.getnframes())
        assert merged.startswith(original) and len(merged) > len(original)
        report.update(passed=True, paused_pcm_bytes=len(original), merged_pcm_bytes=len(merged),
                      confirmed_users=sum(m.role.value == "user" for m in work.session.messages),
                      pause_did_not_submit=True, resume_silence_did_not_submit=True,
                      prefix_preserved=True, faults=faults)
    except Exception as error:
        report.update(passed=False, error_type=type(error).__name__, faults=faults)
        raise
    finally:
        if microphone:
            microphone.cancel()
            await asyncio.gather(microphone, return_exceptions=True)
        if runner:
            await runner.close()
        if process:
            await process.close()
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()
        await work.aclose()
        report["audio_process_exit"] = process.process.returncode if process and process.process else None
        report["model_processes_remaining"] = service.pids
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech-cache", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(probe(parser.parse_args()))
