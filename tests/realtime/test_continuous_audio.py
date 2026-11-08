import asyncio
import io
import struct
import wave

import pytest

from shinar.realtime.audio_ipc import encode_message, read_message, lengths, MAX_PAYLOAD
from shinar.realtime.endpoint import EndpointDetector
from shinar.realtime.pcm import DeviceFormat, PcmConverter, PCM48


def utterance(detector):
    events = []
    for _ in range(4):
        events.extend(detector.feed(b"\x10\x01" * 512, 0.9))
    for _ in range(32):
        events.extend(detector.feed(b"\0" * 1024, 0.01))
    return events


@pytest.mark.parametrize("pause", [650, 1000])
def test_endpoint_final_once_and_claim_is_versioned(pause):
    detector = EndpointDetector(pause)
    events = utterance(detector)
    ended = [value for kind, value in events if kind == "ended"]
    assert len(ended) == 1
    value = ended[0]
    with wave.open(io.BytesIO(value.audio)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.readframes(2048).startswith(b"\x10\x01")
    assert not detector.claim(value.id, value.revision + 1)
    assert detector.claim(value.id, value.revision)
    assert not detector.claim(value.id, value.revision)


def test_continuation_invalidates_old_final_without_losing_audio():
    detector = EndpointDetector()
    first = next(v for k, v in utterance(detector) if k == "ended")
    events = utterance(detector)
    second = next(v for k, v in events if k == "ended")
    assert first.id == second.id and second.revision == first.revision + 1
    assert len(second.audio) > len(first.audio)
    assert not detector.claim(first.id, first.revision)
    assert detector.claim(second.id, second.revision)


def test_silence_noise_and_invalid_windows_do_not_submit():
    detector = EndpointDetector()
    assert not [e for _ in range(100) for e in detector.feed(b"\0" * 1024, 0.1)]
    with pytest.raises(ValueError):
        detector.feed(b"\0", 0.9)
    detector.MAX_SAMPLES = 512 * 5
    events = [e for _ in range(6) for e in detector.feed(b"\1\0" * 512, 0.9)]
    assert any(k == "limit" for k, _ in events) and not any(k == "ended" for k, _ in events)


def test_short_utterance_is_not_rejected_by_a_minimum_duration():
    detector = EndpointDetector()
    for _ in range(3):
        detector.feed(b"\x10\x01" * 512, 0.9)
    events = [e for _ in range(25) for e in detector.feed(b"\0" * 1024, 0)]
    assert len([v for k, v in events if k == "ended"]) == 1


def test_pending_final_does_not_accumulate_unbounded_silence():
    detector = EndpointDetector()
    value = next(v for k, v in utterance(detector) if k == "ended")
    retained_size = len(detector.pcm)
    events = [e for _ in range(16000 * 70 // 512) for e in detector.feed(b"\0" * 1024, 0)]
    assert len(detector.pcm) == retained_size and not events
    assert detector.claim(value.id, value.revision)


def test_pause_keeps_speech_but_never_turns_the_muted_interval_into_an_endpoint():
    detector = EndpointDetector()
    for _ in range(4):
        detector.feed(b"\x10\x01" * 512, 0.9)
    before = bytes(detector.pcm)
    paused = detector.pause()
    assert paused and paused.audio.endswith(before)
    # The engine does not feed paused audio. Silence after resume also waits for
    # another onset, rather than automatically submitting the unfinished phrase.
    for _ in range(3000):
        assert not detector.feed(b"\0" * 1024, 0.01)
    assert bytes(detector.pcm) == before
    assert not detector.claim(paused.id, paused.revision - 1)
    events = utterance(detector)
    ended = next(v for k, v in events if k == "ended")
    assert ended.id == paused.id and ended.revision > paused.revision
    with wave.open(io.BytesIO(ended.audio)) as wav:
        assert wav.readframes(wav.getnframes()).startswith(before)
    assert detector.claim(ended.id, ended.revision)


def test_pause_restores_an_uncommitted_claim_and_shares_the_original_length_limit():
    detector = EndpointDetector()
    first = next(v for k, v in utterance(detector) if k == "ended")
    assert detector.claim(first.id, first.revision)
    detector.restore(first.id, first.revision, first.audio)
    paused = detector.pause()
    assert paused.id == first.id and paused.audio == first.audio
    detector.MAX_SAMPLES = len(detector.pcm) // 2 + 512
    events = [e for _ in range(4) for e in detector.feed(b"\1\0" * 512, .9)]
    assert any(k == "limit" for k, _ in events)
    assert not any(k == "ended" for k, _ in events)
    with pytest.raises((ValueError, wave.Error, EOFError)):
        detector.restore("invalid", 1, b"not audio")


def test_audio_worker_pause_retains_rtc_tail_and_old_microphone_generation_is_closed():
    from types import SimpleNamespace
    from shinar.realtime.audio_worker import AudioSessionWorker
    from shinar.realtime.protocol import TurnRef

    async def run():
        events, controls = [], []
        async def emit(header, payload):
            events.append((header, payload))
        worker = AudioSessionWorker(emit)
        worker.voice_session = "s"
        worker.mic_ref = TurnRef("s", "microphone", 1)
        worker.endpoint = EndpointDetector()
        for _ in range(4):
            worker.endpoint.feed(b"\1\0" * 512, .9)
        original = bytes(worker.endpoint.pcm)
        worker.muted = False
        worker.vad = worker.near_vad = SimpleNamespace(reset=lambda: None)
        async def drain(ref, **kwargs):
            controls.append("drain")
        async def finish(ref):
            controls.append("finish")
            worker.endpoint.feed(b"\2\0" * 512, .9)  # Last subscribed RTC frame.
        async def cancel(ref):
            controls.append("cancel")
        async def start(ref):
            controls.append("start")
        worker.desktop = SimpleNamespace(drain_audio=drain, finish_audio=finish,
                                         cancel_outgoing=cancel, start_turn=start)
        worker.engine = SimpleNamespace(receiver=SimpleNamespace(cancel=lambda ref: None))
        await worker.handle({"kind": "pause", "voice_session": "s", "pause_id": "p",
                             "operation": "op"}, b"")
        header, audio = next((h, p) for h, p in events if h["kind"] == "input_paused")
        assert header["pause_id"] == "p" and audio.endswith(original + b"\2\0" * 512)
        assert controls == ["drain", "finish", "cancel"] and worker.muted
        assert worker.endpoint.pending and events[-1][0]["has_input"]
        old = worker.mic_ref
        await worker.handle({"kind": "resume", "voice_session": "s", "preserve_input": True}, b"")
        assert not worker.muted and worker.mic_ref.generation == old.generation + 1
        assert bytes(worker.endpoint.pcm) == original + b"\2\0" * 512
        # A delayed frame from the pre-pause track must not mutate the buffer.
        worker.receive_input(old, SimpleNamespace(data=b"stale"))
        assert bytes(worker.endpoint.pcm) == original + b"\2\0" * 512
        await worker.mute(preserve=True)
        await worker.handle({"kind": "discard_input", "voice_session": "s"}, b"")
        assert not worker.endpoint.id and not worker.endpoint.pcm and worker.muted

    asyncio.run(run())


def test_device_format_conversion_is_chunk_independent_and_clips():
    import numpy as np

    fmt = DeviceFormat(48000, 2, "float32")
    raw = np.array([[1.5, 1.5], [-1.5, -1.5], [0.5, 0.5], [float("nan"), 0]], dtype="<f4").tobytes()
    whole = PcmConverter(fmt, PCM48, None).push(raw)
    parts = PcmConverter(fmt, PCM48, None)
    chunked = b"".join(parts.push(raw[i : i + 3]) for i in range(0, len(raw), 3)) + parts.flush()
    assert whole == chunked
    assert np.frombuffer(whole, dtype="<i2").tolist() == [32767, -32768, 16384, 0]
    reverse = PcmConverter(PCM48, DeviceFormat(48000, 2, "int16"), None).push(whole)
    assert len(reverse) == len(whole) * 2


def test_actual_resampler_keeps_state_across_device_chunks():
    rtc = pytest.importorskip("livekit.rtc")
    import numpy as np

    raw = (np.sin(np.arange(4410) * 0.05) * 20000).astype("<i2").tobytes()
    source = DeviceFormat(44100, 1, "int16")
    one, many = PcmConverter(source, PCM48, rtc), PcmConverter(source, PCM48, rtc)
    expected = one.push(raw) + one.flush()
    actual = b"".join(many.push(raw[i : i + 320]) for i in range(0, len(raw), 320)) + many.flush()
    assert len(actual) == len(expected) and abs(len(actual) // 2 - 4800) < 10
    # The native converter dithers PCM16; chunking must not change timing or signal.
    assert (
        np.max(
            np.abs(
                np.frombuffer(actual, dtype="<i2").astype(int)
                - np.frombuffer(expected, dtype="<i2").astype(int)
            )
        )
        <= 2
    )


def test_ipc_checks_length_before_reading_payload_and_survives_split_prefix():
    async def run():
        reader = asyncio.StreamReader()
        packet = encode_message({"kind": "capture", "voice_session": "one"}, b"\0\1")
        for byte in packet:
            reader.feed_data(bytes([byte]))
        header, payload = await read_message(reader)
        assert header["kind"] == "capture" and payload == b"\0\1"
        with pytest.raises(ValueError):
            lengths(struct.pack("!II", 20, MAX_PAYLOAD + 1))

    asyncio.run(run())


# Asset readiness is separate from the presence of SDKs in the development environment.
def test_ready_assets_reject_same_size_corruption(tmp_path, monkeypatch):
    import hashlib
    import shinar.realtime.continuous_assets as assets
    import shinar.realtime.local_server as server
    from shinar.local_speech.catalog import Artifact

    vad = tmp_path / "vad.onnx"
    vad.write_bytes(b"vad")
    artifact = Artifact(
        path="vad.onnx",
        url="https://example.org/vad",
        size=3,
        sha256=hashlib.sha256(b"vad").hexdigest(),
    )
    monkeypatch.setattr(
        assets, "VAD_PACKAGE", assets.VAD_PACKAGE.model_copy(update={"files": [artifact]})
    )
    monkeypatch.setattr(assets, "vad_path", lambda root: vad)
    monkeypatch.setattr(server, "ARCHIVE_NAME", "server.zip")
    monkeypatch.setattr(server, "ARCHIVE_SHA256", hashlib.sha256(b"rtc").hexdigest())
    folder = tmp_path / "sfu"
    folder.mkdir()
    (folder / "server.zip").write_bytes(b"rtc")
    assert assets.prepared_assets(tmp_path)
    vad.write_bytes(b"bad")
    assert not assets.prepared_assets(tmp_path)


def test_natural_output_end_drains_accepted_pcm_and_rejects_late_rtc_silence():
    from types import SimpleNamespace
    from shinar.realtime.audio_worker import AudioSessionWorker
    from shinar.realtime.protocol import TurnRef, TurnReceiver, TurnEvent, PcmFrame

    async def run():
        events = []

        async def emit(header, payload):
            events.append((header, payload))

        worker = AudioSessionWorker(emit)
        worker.voice_session = "s"
        ref = TurnRef("s", "turn", 1)
        worker.output_ref, worker.output_generation, worker.output_accepting = ref, "1", True
        worker.output_credit = 8
        worker.output_converter = PcmConverter(PCM48, PCM48, None)
        receiver = TurnReceiver("s")
        receiver.accept(TurnEvent(ref, "start", 0))
        worker.desktop = SimpleNamespace(receiver=receiver)

        async def drain(ref):
            pass

        async def finish(ref):
            # Native unpublish may deliver late callbacks before returning.
            assert not worker.output_accepting
            for _ in range(200):
                worker.receive_output(ref, PcmFrame(bytes(1920)))

        worker.engine = SimpleNamespace(drain_audio=drain, finish_audio=finish)
        worker.receive_output(ref, PcmFrame(b"\1\0" * 960))
        delivery = asyncio.create_task(worker.deliver_output())
        try:
            await worker.handle({"kind": "output_done", "voice_session": "s"}, b"")
            for _ in range(200):
                worker.receive_output(ref, PcmFrame(bytes(1920)))
            assert [h["kind"] for h, _ in events] == ["playback", "output_drained"]
            assert not worker.output_queue and worker.output_samples == 0
            assert not receiver.accept_audio("old-track")
        finally:
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)

    asyncio.run(run())


def test_dead_audio_reader_fails_requests_immediately_instead_of_hanging_shutdown():
    from shinar.realtime.audio_process import AudioSessionProcess

    async def run():
        process = AudioSessionProcess("s", lambda *args: None)
        process.reader = asyncio.create_task(asyncio.sleep(0))
        await process.reader
        with pytest.raises(RuntimeError, match="audio_worker_disconnected"):
            await process.request("cancel_output")
        assert not process.pending

    asyncio.run(run())
