import asyncio
import sys
from types import SimpleNamespace

import pytest

from lingualoop.realtime import PcmFrame, TurnEvent, TurnRef
from lingualoop.realtime.livekit_transport import CONTROL_TOPIC, TOPIC, LiveKitTransport


class FakeRoom:
    def __init__(self):
        self.callbacks = {}
        self.published = []
        self.disconnected = False
        self.local_participant = self
        self.remote_participants = {}

    def on(self, name, callback):
        self.callbacks[name] = callback

    async def publish_data(self, payload, **kwargs):
        self.published.append((TurnEvent.decode(payload), kwargs))

    async def connect(self, url, token, options):
        self.options = options

    async def unpublish_track(self, sid):
        pass

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def transport(monkeypatch):
    rtc = SimpleNamespace(Room=FakeRoom, AudioFrame=lambda *args: args,
                          RoomOptions=lambda **kwargs: SimpleNamespace(**kwargs),
                          RtcConfiguration=lambda **kwargs: SimpleNamespace(**kwargs),
                          IceServer=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setitem(sys.modules, "livekit", SimpleNamespace(rtc=rtc))
    instance = LiveKitTransport("s", "trusted-worker")
    instance._connected = True
    return instance


def packet(event, *, identity="trusted-worker", topic=TOPIC):
    return SimpleNamespace(data=event.encode(), topic=topic,
                           participant=SimpleNamespace(identity=identity))


def test_adapter_rejects_foreign_sender_and_sender_late_completion(transport):
    async def scenario():
        ref = TurnRef("s", "t", 1)
        transport._on_data(packet(TurnEvent(ref, "start", 0), identity="untrusted"))
        assert transport.receiver.current is None
        await transport.start_turn(ref)
        assert await transport.send_delta(ref, "partial")
        transport._on_data(packet(TurnEvent(ref, "cancel", 0), topic=CONTROL_TOPIC))
        assert not await transport.send_delta(ref, "late")
        assert not await transport.complete_text(ref)
        await asyncio.sleep(0)
        assert transport.room.published[-1][0].kind == "cancel_ack"
        await transport.close()
        assert transport.room.disconnected and not transport._tasks
    asyncio.run(scenario())


def test_connect_requires_explicit_nonempty_ice_urls_and_serializes_them(transport):
    async def scenario():
        for invalid in ((), ("",)):
            transport.ice_server_urls = invalid
            with pytest.raises(ValueError, match="explicit_ice_server_urls_required"):
                await transport.connect("ws://127.0.0.1:17880", "not-a-real-token")
        transport.ice_server_urls = ("stun:127.0.0.1:17882",)
        await transport.connect("ws://127.0.0.1:17880", "not-a-real-token")
        config = transport.room.options.rtc_config
        assert len(config.ice_servers) == 1
        assert config.ice_servers[0].urls == ["stun:127.0.0.1:17882"]
        assert transport.room.options.single_peer_connection is True
        await transport.close()
    asyncio.run(scenario())


def test_peer_discovery_must_be_data_ready_before_output(transport):
    async def scenario():
        transport.room.remote_participants["trusted-worker"] = SimpleNamespace(state=1)
        waiting = asyncio.create_task(transport.wait_for_peer(.3))
        await asyncio.sleep(.02)
        assert not waiting.done()
        transport.room.remote_participants["trusted-worker"].state = 2
        await waiting
        await transport.close()
    asyncio.run(scenario())


def test_reentry_creates_fresh_room_and_rejects_old_room_callbacks(transport):
    async def scenario():
        old = transport.room
        late = old.callbacks["data_received"]
        await transport.close()
        transport.ice_server_urls = ("stun:127.0.0.1:17883",)
        await transport.connect("ws://127.0.0.1:17880", "fake")
        assert transport.room is not old
        event = TurnEvent(TurnRef("s", "new", 1), "start", 0)
        late(packet(event))
        assert transport.receiver.current is None
        transport.room.callbacks["data_received"](packet(event))
        assert transport.receiver.current == event.ref
        await transport.close()
    asyncio.run(scenario())


def test_capture_in_flight_is_cleared_and_cannot_survive_cancel(transport):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        class Source:
            clears = 0
            async def capture_frame(self, frame):
                entered.set()
                await release.wait()
            def clear_queue(self):
                self.clears += 1
            async def aclose(self):
                pass
        source = Source()
        ref = TurnRef("s", "t", 1)
        await transport.start_turn(ref)
        transport._source = source
        sending = asyncio.create_task(transport.send_audio(ref, PcmFrame(bytes(1920))))
        await entered.wait()
        transport._on_data(packet(TurnEvent(ref, "cancel", 0), topic=CONTROL_TOPIC))
        assert source.clears >= 1
        release.set()
        assert await sending is False
        await asyncio.sleep(0)
        assert source.clears >= 2
        await transport.close()
    asyncio.run(scenario())


def test_local_cancel_gates_audio_before_network_await(transport):
    async def scenario():
        ref = TurnRef("s", "t", 1)
        transport.receiver.accept(TurnEvent(ref, "start", 0))
        transport.receiver.accept(TurnEvent(ref, "audio_bind", 1, track_sid="sid"))
        entered, release = asyncio.Event(), asyncio.Event()
        async def held_publish(*args, **kwargs):
            entered.set()
            await release.wait()
        transport.room.publish_data = held_publish
        cancelling = asyncio.create_task(transport.request_cancel(ref))
        await entered.wait()
        assert not transport.receiver.accept_audio("sid")
        release.set()
        await cancelling
        await transport.close()
    asyncio.run(scenario())


def test_cleanup_failure_does_not_skip_other_resources_or_disconnect(transport):
    async def scenario():
        closed = []
        class Source:
            def clear_queue(self):
                closed.append("source_queue")
            async def aclose(self):
                closed.append("source_close")
                raise RuntimeError("native_close_failed")
        class Stream:
            def __init__(self, name, fail=False):
                self.name, self.fail = name, fail
            async def aclose(self):
                closed.append(self.name)
                if self.fail:
                    raise RuntimeError("stream_close_failed")
        transport._source = Source()
        transport._publication = SimpleNamespace(sid="sid")
        transport._streams.update([Stream("stream1", True), Stream("stream2")])
        sleeping = asyncio.create_task(asyncio.sleep(100))
        transport._tasks.add(sleeping)
        with pytest.raises(RuntimeError, match="realtime_cleanup_failed"):
            await transport.close()
        assert {"source_queue", "source_close", "stream1", "stream2"} <= set(closed)
        assert transport.room.disconnected
        assert not transport._connected and not transport._tasks and not transport._streams
        assert sleeping.cancelled() and transport._source is None
        assert transport.metrics["cleanup_errors"] == 2
        await transport.close()
    asyncio.run(scenario())


def test_disconnect_callbacks_cannot_recreate_consumer_or_cancel_task(transport):
    async def scenario():
        spawned = []
        async def consumer(*args):
            spawned.append(True)
            await asyncio.sleep(100)
        transport._consume_audio = consumer
        ref = TurnRef("s", "t", 1)
        await transport.start_turn(ref)
        async def disconnect_with_late_callbacks():
            transport._on_track(SimpleNamespace(kind=1), SimpleNamespace(sid="late"),
                                SimpleNamespace(identity="trusted-worker"))
            transport._on_data(packet(TurnEvent(ref, "cancel", 0), topic=CONTROL_TOPIC))
            await asyncio.sleep(0)
            transport.room.disconnected = True
        transport.room.disconnect = disconnect_with_late_callbacks
        await transport.close()
        assert not spawned and not transport._tasks and not transport._streams
        assert transport.room.disconnected and not transport._connected
    asyncio.run(scenario())
