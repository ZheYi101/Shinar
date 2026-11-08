import asyncio
from types import SimpleNamespace

import pytest

from shinar.realtime.local_stun import COOKIE, binding_response
from shinar.realtime.voice_io import RtcWavInput, RtcSpeechOutput, MAX_WAV_BYTES
from shinar.realtime.protocol import TurnRef


def test_stun_binding_response_has_transaction_and_xor_mapped_address():
    import socket
    import struct

    request = struct.pack("!HHI", 1, 0, COOKIE) + b"0123456789ab"
    result = binding_response(request, ("127.0.0.1", 19001))
    assert result[:20] == struct.pack("!HHI", 0x101, 12, COOKIE) + request[8:20]
    kind, length, zero, family, port, address = struct.unpack("!HHBBHI", result[20:])
    assert (kind, length, zero, family) == (0x20, 8, 0, 1)
    assert port ^ (COOKIE >> 16) == 19001
    assert address ^ COOKIE == int.from_bytes(socket.inet_aton("127.0.0.1"), "big")
    for invalid in (b"", request[:-1], b"\xff" * 20, request + b"extra"):
        assert binding_response(invalid, ("127.0.0.1", 19001)) is None


class Room:
    def register_byte_stream_handler(self, topic, handler):
        self.handler = handler

    def unregister_byte_stream_handler(self, topic):
        self.handler = None


class Reader:
    def __init__(self, chunks, *, size=None):
        self.info = SimpleNamespace(
            size=size, mime_type="audio/wav", attributes={"request_id": "one"}
        )
        self.chunks, self.closed = chunks, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    def close(self):
        self.closed = True


def test_upload_rejects_foreign_sender_and_checks_end_of_stream_size():
    async def run():
        room = Room()
        ingress = RtcWavInput(room, "trusted")
        foreign = Reader([b"x"])
        room.handler(foreign, "other")
        assert foreign.closed and not ingress._tasks
        complete = Reader([b"a", b"b"], size=2)
        room.handler(complete, "trusted")
        upload = await ingress.receive()
        assert upload.audio == b"ab" and complete.closed
        await asyncio.sleep(0)
        truncated = Reader([b"a"], size=2)
        room.handler(truncated, "trusted")
        with pytest.raises(ValueError, match="wav_upload_failed"):
            await ingress.receive()
        assert truncated.closed
        await asyncio.sleep(0)
        oversized = Reader([], size=MAX_WAV_BYTES + 1)
        room.handler(oversized, "trusted")
        with pytest.raises(ValueError):
            await ingress.receive()
        await ingress.aclose()

    asyncio.run(run())


def test_close_wakes_pending_upload_consumer():
    async def run():
        ingress = RtcWavInput(Room(), "trusted")
        waiting = asyncio.create_task(ingress.receive())
        await asyncio.sleep(0)
        await ingress.aclose()
        with pytest.raises(RuntimeError, match="closed"):
            await waiting

    asyncio.run(run())


def test_output_close_retrieves_an_already_failed_sender():
    import gc

    async def run():
        loop = asyncio.get_running_loop()
        errors = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: errors.append(context))

        class Broken:
            async def wait_for_peer(self):
                pass

            async def start_turn(self, ref):
                pass

            async def send_delta(self, ref, value):
                raise RuntimeError("channel_failed")

        try:
            output = RtcSpeechOutput(Broken(), TurnRef("session", "turn", 1))
            await output.start()
            output.on_text_delta("Hello.")
            await asyncio.sleep(0)
            await output.aclose()
            del output
            gc.collect()
            await asyncio.sleep(0)
            assert not errors
        finally:
            loop.set_exception_handler(previous)

    asyncio.run(run())
