"""Explicit offline-model / real-RTC integration, without UI or paid model calls."""
# ruff: noqa: E402 -- allow running this checkout script without installing the package

import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import uuid
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shinar.application.learning_workbench import LearningWorkbench
from shinar.application.voice_session import VoiceSessionCoordinator
from shinar.core.domain import LanguageEnum
from shinar.infrastructure import SQLiteStore
from shinar.local_speech.profiles import LocalSpeechProfile
from shinar.local_speech.service import LocalSpeechService
from shinar.providers.mock import MockLearningLLMProvider


class ScriptedDialogue(MockLearningLLMProvider):
    def __init__(self, language: str):
        self.language, self.calls = language, 0

    async def stream_reply(self, **kwargs):
        self.calls += 1
        text = {
            "zh": "我理解你的观点。我们继续聊吧。",
            "en": "That makes sense. Tell me more.",
            "ja": "なるほど。もう少し教えてください。",
        }[self.language]
        for char in text:
            yield char
            await asyncio.sleep(0.001)


class ValidationFailure(Exception):
    def __init__(self, report: dict) -> None:
        self.report = report


def profile(value: dict) -> LocalSpeechProfile:
    return LocalSpeechProfile(**value)


async def run_case(case: dict, folder: Path, *, real_rtc: bool) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    provider = ScriptedDialogue(case["language"])
    service = LocalSpeechService(folder / "speech")
    for task in ("stt", "tts"):
        service.register_prepared(profile(case[task]))
    work = LearningWorkbench(
        provider, event_store=SQLiteStore(folder / (uuid.uuid4().hex + ".sqlite3"))
    )
    language = {
        "zh": LanguageEnum.CHINESE,
        "en": LanguageEnum.ENGLISH,
        "ja": LanguageEnum.JAPANESE,
    }[case["language"]]
    await work.load_material(
        title="Public speech fixture",
        content="Mira waited at the bridge. Ren left.",
        source_language=LanguageEnum.ENGLISH,
        target_language=language,
        native_language=LanguageEnum.CHINESE,
        learner_level="A2",
    )
    await work.start_session()
    output_segments = []

    async def capture(segment):
        output_segments.append(segment)
        (folder / f"segment-{segment.index}.wav").write_bytes(segment.audio)
        if segment.attribution:
            (folder / "ATTRIBUTION.txt").write_text(segment.attribution + "\n", encoding="utf-8")

    voice = VoiceSessionCoordinator(
        work, stt=service.provider("stt"), tts=service.provider("tts"), on_audio=capture
    )
    server = sender = receiver = ingress = output = None
    received_frames = []
    submitted_at = None
    first_received_ms = None
    report = {
        "case": case["name"],
        "language": case["language"],
        "paid_model_calls": False,
        "real_local_models": True,
        "real_rtc": real_rtc,
    }
    try:
        report["phase"] = "stt"
        audio = Path(case["wav"]).read_bytes()
        draft = await voice.recognize(audio)
        report["cold_stt"] = service.last_metrics["stt"]
        hot = []
        for _ in range(3):
            draft = await voice.recognize(audio)
            hot.append(service.last_metrics["stt"]["compute_ms"])
        report["hot_stt_compute_ms"] = hot
        assert sum(hot) / len(hot) <= 500, "stt_average_latency_failed"
        assert provider.calls == 0
        if real_rtc:
            report["phase"] = "rtc_connect"
            from livekit import api
            from shinar.realtime import TurnRef
            from shinar.realtime.livekit_transport import LiveKitTransport
            from shinar.realtime.local_server import (
                LocalServer,
                ensure_server,
                owned_rfc1918_addresses,
            )
            from shinar.realtime.voice_io import RtcWavInput, RtcSpeechOutput, send_wav

            address = case.get("rtc_address") or next(
                iter(sorted(owned_rfc1918_addresses())), "127.0.0.1"
            )
            server = LocalServer(
                ensure_server(ROOT / "build/livekit-probe"), ROOT / "build/livekit-probe"
            )
            server.rtc_address = address
            server.__enter__()
            session = "integration-" + uuid.uuid4().hex
            stun = (f"stun:{address}:{server.stun_port}",)
            sender = LiveKitTransport(session, "client", ice_server_urls=stun)

            def receive_audio(ref, frame):
                nonlocal first_received_ms
                received_frames.append(frame)
                if submitted_at is not None and first_received_ms is None and any(frame.data):
                    first_received_ms = (perf_counter() - submitted_at) * 1000

            receiver = LiveKitTransport(
                session, "engine", ice_server_urls=stun, on_audio=receive_audio
            )

            def token(identity):
                return (
                    api.AccessToken(server.key, server.secret)
                    .with_identity(identity)
                    .with_ttl(timedelta(minutes=5))
                    .with_grants(api.VideoGrants(room_join=True, room=session))
                    .to_jwt()
                )

            await receiver.connect(server.url, token("client"))
            await sender.connect(server.url, token("engine"))
            await asyncio.gather(sender.wait_for_peer(), receiver.wait_for_peer())
            ingress = RtcWavInput(sender.room, "client")
            report["phase"] = "upload"
            await send_wav(receiver.room, "engine", audio, "integration-request")
            upload = await ingress.receive()
            assert hashlib.sha256(upload.audio).digest() == hashlib.sha256(audio).digest()
            report["wav_upload_exact"] = True
            draft = await voice.recognize(upload.audio)
            output = RtcSpeechOutput(sender, TurnRef(session, upload.request_id, 1))
            await output.start()

            async def rtc_capture(segment):
                await capture(segment)
                await output.on_audio(segment)

            voice.on_audio = rtc_capture
            voice.on_text_delta = output.on_text_delta
        report["phase"] = "dialogue_tts"
        submitted_at = perf_counter()
        result = await voice.submit_confirmed(draft)
        assert result.text_status == "completed", "dialogue_failed"
        assert result.speech_status == "completed", result.error_code
        assert provider.calls == 1 and output_segments
        report.update(
            turn_id=result.turn_id,
            text_status=result.text_status,
            speech_status=result.speech_status,
            segments=len(output_segments),
            timings_ms=result.timings_ms,
            last_tts=service.last_metrics["tts"],
        )
        report["actual_model_devices"] = {
            name: metrics.get("device") for name, metrics in service.last_metrics.items()
        }
        if real_rtc:
            report["phase"] = "output_finish"
            await output.finish(text_completed=True)
            report["phase"] = "receive_output"
            async with asyncio.timeout(8):
                while not received_frames or receiver.receiver.completed_text is None:
                    await asyncio.sleep(0.02)
            assert any(any(frame.data) for frame in received_frames)
            assert receiver.receiver.completed_text == result.assistant_message.content
            report.update(
                received_pcm_frames=len(received_frames),
                nonzero_pcm=True,
                rtc_text_exact=True,
                transmitted_samples=output.sent_samples,
                first_nonzero_rtc_pcm_ms=first_received_ms,
            )
        else:
            # Replay is speech-only and must never regenerate the answer.
            voice.on_audio = None
            replay = await voice.retry_speech(result.turn_id)
            assert replay.speech_status == "completed" and provider.calls == 1
        # Exercise validation inside the actual resident workers, not a mock port.
        for task in ("stt", "tts"):
            backend = await service.provider(task).bind(case["language"])
            process_id = service.worker_pid(task)
            assert process_id is not None
            try:
                if task == "stt":
                    await backend.transcribe(b"invalid WAV")
                else:
                    await backend.synthesize("")
            except ValueError:
                from shinar.local_speech.processes import pid_exists

                assert not pid_exists(process_id), "failed_worker_cleanup"
                report[f"{task}_invalid_input_rejected_and_released"] = True
            else:
                raise AssertionError("invalid_input_accepted")
        assert provider.calls == 1
        report["passed"] = True
        report["phase"] = "complete"
    except Exception as exc:
        report.update(passed=False, error_type=type(exc).__name__)
        if isinstance(exc, AssertionError) and re.fullmatch(r"[a-z_]+", str(exc)):
            report["error_code"] = str(exc)
        if receiver:
            report["receiver_metrics"] = receiver.metrics
            report["receiver_rejected_events"] = receiver.receiver.rejected_events
            report["receiver_rejected_frames"] = receiver.receiver.rejected_frames
            report["received_pcm_frames"] = len(received_frames)
            report["received_text_characters"] = len(receiver.receiver.draft)
            report["received_text_completed"] = receiver.receiver.completed_text is not None
        raise ValidationFailure(report) from exc
    finally:
        if output:
            await output.aclose()
        if ingress:
            await ingress.aclose()
        if sender or receiver:
            await asyncio.gather(*(peer.close() for peer in (sender, receiver) if peer))
        await voice.aclose()
        owned_pids = service.pids
        await service.close()
        await work.aclose()
        if server:
            server.__exit__(None, None, None)
            report["rtc_server_cleanup"] = server.cleaned
        from shinar.local_speech.processes import pid_exists

        report["model_process_cleanup"] = all(not pid_exists(pid) for pid in owned_pids)
        assert report["model_process_cleanup"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--rtc", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    logging.getLogger("livekit").disabled = True
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / "build"):
        parser.error("output must be inside build")
    cases = json.loads(Path(args.config).read_text(encoding="utf-8"))
    case = next(item for item in cases if item["name"] == args.case)
    if not re.fullmatch(r"[a-z0-9_-]+", args.case):
        parser.error("invalid case name")
    try:
        report = asyncio.run(run_case(case, output.parent / args.case, real_rtc=args.rtc))
    except ValidationFailure as exc:
        report = exc.report
    except Exception as exc:
        report = {"case": args.case, "passed": False, "error_type": type(exc).__name__}
        # Only fixed assertion codes, never provider text or raw model errors.
        if isinstance(exc, AssertionError) and re.fullmatch(r"[a-z_]+", str(exc)):
            report["error_code"] = str(exc)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
