"""Owned RTC/DSP subprocess. No Qt, learning database, LLM or speech model credentials."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta
import io
from pathlib import Path
import sys
from time import monotonic
import wave

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lingualoop.realtime.audio_ipc import encode_message, read_file_message
from lingualoop.realtime.endpoint import EndpointDetector, SileroVad
from lingualoop.realtime.pcm import DeviceFormat, PcmConverter, PCM16, PCM48


class AudioSessionWorker:
    def __init__(self, emit):
        self.emit = emit
        self.voice_session = ""
        self.desktop = self.engine = self.server = None
        self.output_generation = ""
        self.output_accepting = False
        self.muted = True
        self.closed = False
        self.tasks = set()
        self.capture_queue = asyncio.Queue(maxsize=20)  # <= 200 ms of canonical capture.
        self.output_queue = deque()
        self.output_samples = 0
        self.output_credit = 0
        self.output_event = asyncio.Event()
        self.input_pending = bytearray()
        self.near_pending = bytearray()
        self.capture_pending = bytearray()
        self.near_active = False
        self.near_onset = 0
        self.last_capture = monotonic()
        self.last_input = monotonic()
        self.capture_frames = self.input_windows = 0
        self.max_vad_probability = 0.0

    async def event(self, kind, payload=b"", **fields):
        await self.emit({"kind": kind, "voice_session": self.voice_session, **fields}, payload)

    def spawn(self, operation):
        task = asyncio.create_task(operation)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self, config):
        from livekit import rtc, api
        from lingualoop.realtime.livekit_transport import LiveKitTransport
        from lingualoop.realtime.local_server import (
            LocalServer,
            ensure_server,
            owned_rfc1918_addresses,
        )
        from lingualoop.realtime.protocol import TurnRef

        self.rtc = rtc
        self.endpoint = EndpointDetector(config["pause_ms"])
        self.vad = SileroVad(Path(config["vad"]))
        self.near_vad = SileroVad(Path(config["vad"]))
        self.apm = rtc.AudioProcessingModule(
            echo_cancellation=True, noise_suppression=True, high_pass_filter=True
        )
        self.apm.set_stream_delay_ms(80)
        self.capture_format = DeviceFormat(**config["input_format"])
        self.output_format = DeviceFormat(**config["output_format"])
        self.capture_converter = PcmConverter(self.capture_format, PCM48, rtc)
        self.render_converter = PcmConverter(self.output_format, PCM48, rtc)
        self.output_converter = PcmConverter(PCM48, self.output_format, rtc)
        self.near_converter = PcmConverter(PCM48, PCM16, rtc)
        self.input_converter = PcmConverter(PCM48, PCM16, rtc)
        cache = Path(config["cache"])
        executable = await asyncio.to_thread(ensure_server, cache)
        self.server = LocalServer(executable, cache)
        self.server.rtc_address = config.get("rtc_address") or next(
            iter(sorted(owned_rfc1918_addresses())), "127.0.0.1"
        )
        await asyncio.to_thread(self.server.__enter__)
        stun = (f"stun:{self.server.rtc_address}:{self.server.stun_port}",)
        self.desktop = LiveKitTransport(
            self.voice_session, "engine", ice_server_urls=stun, on_audio=self.receive_output
        )
        self.engine = LiveKitTransport(
            self.voice_session, "desktop", ice_server_urls=stun, on_audio=self.receive_input
        )

        def token(identity):
            return (
                api.AccessToken(self.server.key, self.server.secret)
                .with_identity(identity)
                .with_ttl(timedelta(minutes=5))
                .with_grants(api.VideoGrants(room_join=True, room=self.voice_session))
                .to_jwt()
            )

        await self.engine.connect(self.server.url, token("engine"))
        await self.desktop.connect(self.server.url, token("desktop"))
        await asyncio.gather(self.desktop.wait_for_peer(), self.engine.wait_for_peer())
        for peer in (self.desktop, self.engine):
            peer.room.on("disconnected", lambda *_: self.connection_lost())
        self.mic_ref = TurnRef(self.voice_session, "microphone", 1)
        await self.desktop.start_turn(self.mic_ref)
        self.spawn(self.send_capture())
        self.spawn(self.deliver_output())
        self.spawn(self.watchdog())
        return {
            "rtc_address": self.server.rtc_address,
            "worker_pid": __import__("os").getpid(),
            "sfu_pid": self.server.pid,
        }

    def connection_lost(self):
        if not self.closed:
            self.muted = True
            self.output_generation = ""
            self.spawn(self.event("disconnected"))

    async def watchdog(self):
        while not self.closed:
            await asyncio.sleep(0.2)
            if not self.muted and (
                monotonic() - self.last_capture > 0.8 or monotonic() - self.last_input > 1.2
            ):
                self.muted = True
                self.endpoint.reset()
                await self.event("input_gap")

    async def capture(self, payload, header):
        if self.muted:
            return
        self.last_capture = monotonic()
        self.capture_pending.extend(self.capture_converter.push(payload))
        while len(self.capture_pending) >= 960:
            pcm = bytes(self.capture_pending[:960])
            del self.capture_pending[:960]
            frame = self.rtc.AudioFrame(bytearray(pcm), 48000, 1, 480)
            delay = max(0, min(500, int(header.get("capture_delay_ms", 0) + self.render_delay_ms)))
            self.apm.set_stream_delay_ms(delay)
            self.apm.process_stream(frame)
            self.capture_frames += 1
            processed = bytes(frame.data)
            self.near_pending.extend(self.near_converter.push(processed))
            while len(self.near_pending) >= 1024:
                window = bytes(self.near_pending[:1024])
                del self.near_pending[:1024]
                probability = self.near_vad.probability(window)
                self.near_onset = self.near_onset + 1 if probability >= 0.5 else 0
                if self.near_onset >= 5 and not self.near_active:
                    self.near_active = True
                    await self.event("near_speech", mic_generation=self.mic_ref.generation)
                if probability < 0.35:
                    self.near_active = False
            try:
                self.capture_queue.put_nowait((self.mic_ref, processed))
            except asyncio.QueueFull:
                self.muted = True
                self.endpoint.reset()
                await self.event("input_gap")
                return

    render_delay_ms = 60.0

    async def rendered(self, payload, header):
        # Only bytes accepted by the actual device, after application gain, are referenced.
        if header.get("generation") != self.output_generation:
            return
        self.render_delay_ms = max(0, min(500, float(header.get("delay_ms", 60))))
        self.render_pending.extend(self.render_converter.push(payload))
        while len(self.render_pending) >= 960:
            pcm = bytes(self.render_pending[:960])
            del self.render_pending[:960]
            self.apm.process_reverse_stream(self.rtc.AudioFrame(bytearray(pcm), 48000, 1, 480))

    async def send_capture(self):
        from lingualoop.realtime.protocol import PcmFrame

        while not self.closed:
            ref, pcm = await self.capture_queue.get()
            if not self.muted and ref == self.mic_ref:
                await self.desktop.send_audio(ref, PcmFrame(pcm))

    def receive_input(self, ref, frame):
        if self.closed or self.muted or ref != self.mic_ref:
            return
        self.last_input = monotonic()
        self.input_pending.extend(self.input_converter.push(frame.data))
        while len(self.input_pending) >= 1024:
            pcm = bytes(self.input_pending[:1024])
            del self.input_pending[:1024]
            probability = self.vad.probability(pcm)
            self.input_windows += 1
            self.max_vad_probability = max(self.max_vad_probability, probability)
            for kind, value in self.endpoint.feed(pcm, probability):
                if kind == "ended":
                    self.spawn(
                        self.event(
                            "utterance",
                            value.audio,
                            utterance=value.id,
                            revision=value.revision,
                            mic_generation=ref.generation,
                            ended_samples=value.ended_samples,
                        )
                    )
                elif kind == "started":
                    self.spawn(
                        self.event(
                            "input_started",
                            utterance=value[0],
                            revision=value[1],
                            mic_generation=ref.generation,
                        )
                    )
                else:
                    self.muted = True
                    self.spawn(self.event("input_limit"))

    def receive_output(self, ref, frame):
        if (
            self.closed
            or not self.output_accepting
            or ref != self.output_ref
            or str(ref.generation) != self.output_generation
        ):
            return
        if self.output_samples + len(frame.data) // 2 > 48000 * 3:
            self.output_accepting = False
            self.output_generation = ""
            self.output_queue.clear()
            self.output_samples = 0
            self.spawn(self.event("output_overflow"))
            return
        self.output_queue.append((self.output_generation, frame.data))
        self.output_samples += len(frame.data) // 2
        self.output_event.set()

    async def deliver_output(self):
        while not self.closed:
            await self.output_event.wait()
            self.output_event.clear()
            while self.output_queue and self.output_credit > 0:
                generation, data = self.output_queue.popleft()
                self.output_samples -= len(data) // 2
                if generation != self.output_generation:
                    continue
                self.output_credit -= 1
                raw = self.output_converter.push(data)
                await self.event("playback", raw, generation=generation)

    async def begin_output(self, header):
        from lingualoop.realtime.protocol import TurnRef

        self.output_generation = str(header["generation"])
        self.output_accepting = True
        self.output_queue.clear()
        self.output_samples = 0
        self.output_credit = 8
        self.render_pending = bytearray()
        self.output_converter = PcmConverter(PCM48, self.output_format, self.rtc)
        self.render_converter = PcmConverter(self.output_format, PCM48, self.rtc)
        self.output_ref = TurnRef(self.voice_session, header["turn"], int(self.output_generation))
        await self.engine.start_turn(self.output_ref)

    async def send_segment(self, header, payload):
        from lingualoop.realtime.protocol import PcmFrame

        generation = str(header["generation"])
        if generation != self.output_generation:
            return
        with wave.open(io.BytesIO(payload), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
                raise ValueError("invalid_tts_audio")
            rate, data = wav.getframerate(), wav.readframes(wav.getnframes())
        converter = PcmConverter(DeviceFormat(rate, 1, "int16"), PCM48, self.rtc)
        pcm = converter.push(data) + converter.flush()
        for offset in range(0, len(pcm), 1920):
            if generation != self.output_generation:
                return
            await self.engine.send_audio(self.output_ref, PcmFrame(pcm[offset : offset + 1920]))

    async def cancel_output(self):
        self.output_accepting = False
        self.output_generation = ""
        self.output_queue.clear()
        self.output_samples = 0
        if getattr(self, "output_ref", None):
            await self.desktop.request_cancel(self.output_ref)
            # Also close the local sending side before any subsequent sentence.
            await self.engine.cancel_outgoing(self.output_ref)

    async def mute(self):
        self.muted = True
        self.endpoint.reset()
        self.vad.reset()
        self.near_vad.reset()
        self.near_onset = 0
        self.near_active = False
        self.input_pending.clear()
        self.near_pending.clear()
        self.capture_pending.clear()
        while not self.capture_queue.empty():
            self.capture_queue.get_nowait()
        self.engine.receiver.cancel(self.mic_ref)
        await self.desktop.cancel_outgoing(self.mic_ref)

    async def handle(self, header, payload):
        kind = header["kind"]
        result = {}
        if kind == "start":
            self.voice_session = header["voice_session"]
            result = await self.start(header["config"])
        elif header.get("voice_session") != self.voice_session:
            raise ValueError("stale_voice_session")
        elif kind == "capture":
            await self.capture(payload, header)
        elif kind == "rendered":
            await self.rendered(payload, header)
        elif kind == "credit":
            self.output_credit = min(8, self.output_credit + 1)
            self.output_event.set()
        elif kind == "mute":
            await self.mute()
        elif kind == "resume":
            from lingualoop.realtime.protocol import TurnRef

            await self.mute()
            self.mic_ref = TurnRef(self.voice_session, "microphone", self.mic_ref.generation + 1)
            await self.desktop.start_turn(self.mic_ref)
            self.last_capture = self.last_input = monotonic()
            self.muted = False
            result = {"mic_generation": self.mic_ref.generation}
        elif kind == "claim":
            healthy = monotonic() - self.last_capture < 0.8 and monotonic() - self.last_input < 1.2
            reason = (
                "muted" if self.muted else "near_speech" if self.near_active else "version_changed"
            )
            accepted = (
                healthy
                and not self.muted
                and not self.near_active
                and self.endpoint.claim(header["utterance"], header["revision"])
            )
            result = {"accepted": accepted, "reason": "accepted" if accepted else reason}
        elif kind == "stats":
            result = {
                "capture_frames": self.capture_frames,
                "input_windows": self.input_windows,
                "max_vad_probability": self.max_vad_probability,
                "muted": self.muted,
                "endpoint_pending": self.endpoint.pending,
                "near_active": self.near_active,
                "desktop": dict(self.desktop.metrics),
                "engine": dict(self.engine.metrics),
            }
        elif kind == "output_begin":
            await self.begin_output(header)
        elif kind == "segment":
            await self.send_segment(header, payload)
        elif kind == "output_done":
            generation = self.output_generation
            if generation:
                ref = self.output_ref
                await self.engine.drain_audio(ref)
                # Let the audio stream deliver its final packet; then report software drain.
                await asyncio.sleep(0.15)
                if generation != self.output_generation:
                    return
                # A published RTC track can keep delivering silence after its
                # source queue drains. Seal receive BEFORE closing that track;
                # already queued PCM must still reach the device in order.
                self.output_accepting = False
                self.desktop.receiver.cancel(ref)
                await self.engine.finish_audio(ref)
                while self.output_queue and generation == self.output_generation:
                    await asyncio.sleep(0.02)
                if generation == self.output_generation:
                    await self.event("output_drained", generation=generation)
        elif kind == "cancel_output":
            await self.cancel_output()
        elif kind == "close":
            await self.close()
        else:
            raise ValueError("unknown_audio_operation")
        if header.get("operation"):
            await self.event("ack", operation=header["operation"], **result)

    async def close(self):
        self.closed = True
        self.muted = True
        errors = []
        for task in list(self.tasks):
            if task is not asyncio.current_task():
                task.cancel()
        await asyncio.gather(
            *(t for t in self.tasks if t is not asyncio.current_task()), return_exceptions=True
        )
        for peer in (self.desktop, self.engine):
            if peer:
                try:
                    async with asyncio.timeout(2):
                        await peer.close()
                except Exception:
                    errors.append("peer_close_failed")
        if self.server:
            await asyncio.to_thread(self.server.__exit__, None, None, None)
        return errors


async def main():
    lock = asyncio.Lock()

    async def emit(header, payload=b""):
        async with lock:
            packet = encode_message(header, payload)

            def write():
                sys.stdout.buffer.write(packet)
                sys.stdout.buffer.flush()

            await asyncio.to_thread(write)

    worker = AudioSessionWorker(emit)
    commands = set()

    async def dispatch(header, payload):
        try:
            await worker.handle(header, payload)
        except Exception as error:
            await worker.event(
                "operation_failed",
                operation=header.get("operation", ""),
                error="audio_operation_failed",
                error_type=type(error).__name__,
            )

    try:
        while not worker.closed:
            header, payload = await asyncio.to_thread(read_file_message, sys.stdin.buffer)
            if header["kind"] in {"segment", "output_done"}:
                task = asyncio.create_task(dispatch(header, payload))
                commands.add(task)
                task.add_done_callback(commands.discard)
            else:
                await dispatch(header, payload)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        for task in commands:
            task.cancel()
        await asyncio.gather(*commands, return_exceptions=True)
        if not worker.closed:
            await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
