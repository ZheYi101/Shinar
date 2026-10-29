"""Thin optional LiveKit adapter. Business providers and preparation stay outside."""

import asyncio
from collections.abc import Callable
import time
from typing import Any

from .protocol import PcmFrame, TurnEvent, TurnReceiver, TurnRef

TOPIC = "lingualoop.turn.v1"
CONTROL_TOPIC = "lingualoop.control.v1"


class LiveKitTransport:
    def __init__(self, session_id: str, peer_identity: str, *,
                 ice_server_urls: tuple[str, ...] = (),
                 single_peer_connection: bool = True,
                 on_event: Callable[[TurnEvent], None] | None = None,
                 on_audio: Callable[[TurnRef, PcmFrame], None] | None = None) -> None:
        # Lazy import keeps base CLI/desktop usable without the realtime extra.
        try:
            from livekit import rtc
        except ImportError as exc:
            raise RuntimeError("install_lingualoop_realtime_extra") from exc
        self.rtc = rtc
        self.room = rtc.Room()
        self.peer_identity = peer_identity
        self.ice_server_urls = ice_server_urls
        self.single_peer_connection = single_peer_connection
        self.receiver = TurnReceiver(session_id)
        self.on_event = on_event or (lambda event: None)
        self.on_audio = on_audio or (lambda ref, frame: None)
        self.outgoing: TurnRef | None = None
        self._seq = 0
        self._text_done = False
        self._cancelled = False
        self._source: Any = None
        self._publication: Any = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._streams: set[Any] = set()
        self._connected = False
        self._closing = False
        self.metrics: dict[str, float | int] = {"audio_frames_received": 0, "invalid_events": 0,
                                               "task_errors": 0, "cleanup_errors": 0}
        self._register_room(self.room)

    def _register_room(self, room: Any) -> None:
        room.on("data_received", lambda packet: self._on_data(packet) if self.room is room else None)
        room.on("track_subscribed", lambda *args: self._on_track(*args) if self.room is room else None)

    async def connect(self, url: str, token: str) -> None:
        # [] inherits SFU defaults, while [IceServer(urls=[])] is invalid in
        # libwebrtc. Require explicit, nonempty URLs from the integration layer.
        if not self.ice_server_urls or any(not item for item in self.ice_server_urls):
            raise ValueError("explicit_ice_server_urls_required")
        if self._closing:
            # Re-entry needs a fresh native Room and must reject old-room callbacks.
            self.room = self.rtc.Room()
            self._register_room(self.room)
        self._closing = False
        started = time.perf_counter()
        options = self.rtc.RoomOptions(rtc_config=self.rtc.RtcConfiguration(
                                       ice_servers=[self.rtc.IceServer(urls=list(self.ice_server_urls))]),
                                       single_peer_connection=self.single_peer_connection, connect_timeout=10)
        try:
            await self.room.connect(url, token, options=options)
        except BaseException:
            await self.close()
            raise
        self._connected = True
        self.metrics["transport_connected_ms"] = (time.perf_counter() - started) * 1000

    async def wait_for_peer(self, timeout: float = 10) -> None:
        # Room.connect completes before every remote participant is data-ready.
        async with asyncio.timeout(timeout):
            while True:
                peer = self.room.remote_participants.get(self.peer_identity)
                if peer is not None and getattr(peer, "state", 2) == 2:
                    return
                if not self._connected or self._closing:
                    raise RuntimeError("realtime_not_connected")
                await asyncio.sleep(.01)

    def _spawn(self, coro: Any) -> None:
        if self._closing:
            coro.close()
            return
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        def done(completed: asyncio.Task) -> None:
            self._tasks.discard(completed)
            if not completed.cancelled() and completed.exception() is not None:
                self.metrics["task_errors"] += 1
        task.add_done_callback(done)

    def _on_data(self, packet: Any) -> None:
        if self._closing:
            return
        if packet.participant is None or packet.participant.identity != self.peer_identity:
            self.metrics["unattributed_or_foreign_data"] = self.metrics.get("unattributed_or_foreign_data", 0) + 1
            return
        if packet.topic not in {TOPIC, CONTROL_TOPIC}:
            return
        try:
            event = TurnEvent.decode(packet.data)
            key = "received_" + event.kind
            self.metrics[key] = self.metrics.get(key, 0) + 1
            if packet.topic == CONTROL_TOPIC:
                if event.kind == "cancel" and event.ref == self.outgoing:
                    # Set synchronously before scheduling queue cleanup/ack.
                    self._cancelled = True
                    if self._source:
                        self._source.clear_queue()
                    self._spawn(self._ack_cancel(event.ref))
                return
            if self.receiver.accept(event):
                self.on_event(event)
        except (ValueError, TypeError, KeyError):
            self.metrics["invalid_events"] += 1

    def _on_track(self, track: Any, publication: Any, participant: Any) -> None:
        if self._closing:
            return
        if participant.identity == self.peer_identity and track.kind == self.rtc.TrackKind.KIND_AUDIO:
            self._spawn(self._consume_audio(track, publication.sid))

    async def _consume_audio(self, track: Any, sid: str) -> None:
        stream = self.rtc.AudioStream(track, sample_rate=48000, num_channels=1,
                                      frame_size_ms=20, capacity=8)
        self._streams.add(stream)
        try:
            async for event in stream:
                self.metrics["audio_frames_received"] += 1
                if self.receiver.accept_audio(sid):
                    assert self.receiver.current is not None
                    frame = PcmFrame(bytes(event.frame.data))
                    self.on_audio(self.receiver.current, frame)
        finally:
            self._streams.discard(stream)
            await stream.aclose()

    async def _publish(self, event: TurnEvent, *, control: bool = False) -> None:
        if not self._connected:
            raise RuntimeError("realtime_not_connected")
        await self.room.local_participant.publish_data(
            event.encode(), reliable=True, destination_identities=[self.peer_identity],
            topic=CONTROL_TOPIC if control else TOPIC)

    async def _event(self, kind: str, *, text: str = "", track_sid: str = "") -> None:
        assert self.outgoing is not None
        await self._publish(TurnEvent(self.outgoing, kind, self._seq, text, track_sid))
        self._seq += 1

    async def start_turn(self, ref: TurnRef) -> None:
        async with self._lock:
            if ref.session_id != self.receiver.session_id:
                raise ValueError("realtime_session_mismatch")
            if self.outgoing and ref.generation <= self.outgoing.generation:
                raise ValueError("realtime_generation_must_increase")
            await self._release_audio()
            self.outgoing, self._seq = ref, 0
            self._text_done, self._cancelled = False, False
            await self._event("start")

    def _active(self, ref: TurnRef) -> bool:
        return self._connected and self.outgoing == ref and not self._cancelled

    async def send_delta(self, ref: TurnRef, text: str) -> bool:
        async with self._lock:
            if not self._active(ref) or self._text_done:
                return False
            await self._event("text_delta", text=text)
            return True

    async def complete_text(self, ref: TurnRef) -> bool:
        async with self._lock:
            if not self._active(ref) or self._text_done:
                return False
            await self._event("text_done")
            self._text_done = True
            return True

    async def send_audio(self, ref: TurnRef, frame: PcmFrame) -> bool:
        async with self._lock:
            if not self._active(ref):
                return False
            if self._source is None:
                self._source = self.rtc.AudioSource(48000, 1, queue_size_ms=100)
                track = self.rtc.LocalAudioTrack.create_audio_track("assistant-pcm", self._source)
                options = self.rtc.TrackPublishOptions(source=self.rtc.TrackSource.SOURCE_MICROPHONE)
                self._publication = await self.room.local_participant.publish_track(track, options)
                await self._event("audio_bind", track_sid=self._publication.sid)
            if not self._active(ref):
                self._source.clear_queue()
                return False
            await self._source.capture_frame(self.rtc.AudioFrame(frame.data, 48000, 1,
                                                                len(frame.data) // 2))
            # Cancellation can run during capture_frame's await; clear even a late capture.
            if not self._active(ref):
                self._source.clear_queue()
                return False
            return True

    async def request_cancel(self, ref: TurnRef) -> None:
        # No await before the receive presentation gate closes.
        self.receiver.cancel(ref)
        await self._publish(TurnEvent(ref, "cancel", 0), control=True)

    async def drain_audio(self, ref: TurnRef, timeout: float = 10) -> None:
        if not self._active(ref):
            raise RuntimeError("realtime_audio_not_active")
        if self._source:
            async with asyncio.timeout(timeout):
                await self._source.wait_for_playout()

    async def _ack_cancel(self, ref: TurnRef) -> None:
        async with self._lock:
            if self.outgoing == ref:
                await self._release_audio()
                await self._event("cancel_ack")

    async def _release_audio(self) -> None:
        errors = []
        source, publication = self._source, self._publication
        self._source, self._publication = None, None
        if source:
            try:
                source.clear_queue()
            except Exception as exc:
                errors.append(exc)
        if publication:
            try:
                await self.room.local_participant.unpublish_track(publication.sid)
            except Exception as exc:
                errors.append(exc)
        if source:
            try:
                await source.aclose()
            except Exception as exc:
                errors.append(exc)
        if errors:
            self.metrics["cleanup_errors"] += len(errors)
            raise RuntimeError("realtime_audio_cleanup_failed") from None

    async def close(self) -> None:
        # No await before closing the callback gate: disconnect may itself emit
        # late track/data events, and those must never spawn new consumers.
        self._closing = True
        self._connected = False
        self._cancelled = True
        if self.receiver.current:
            self.receiver.cancel(self.receiver.current)
        errors = []
        try:
            async with self._lock:
                await self._release_audio()
        except Exception as exc:
            errors.append(exc)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for stream in list(self._streams):
            try:
                await stream.aclose()
            except Exception as exc:
                self.metrics["cleanup_errors"] += 1
                errors.append(exc)
        self._streams.clear()
        try:
            await self.room.disconnect()
        except Exception as exc:
            self.metrics["cleanup_errors"] += 1
            errors.append(exc)
        finally:
            self._connected = False
        if errors:
            raise RuntimeError("realtime_cleanup_failed") from None
