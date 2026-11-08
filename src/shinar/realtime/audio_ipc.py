"""Versioned, bounded framing; no pickle, audio files or implicit object execution."""

import asyncio
import json
import struct

MAX_HEADER = 8192
MAX_PAYLOAD = 24 * 1024**2
PREFIX = struct.Struct("!II")


def encode_message(header: dict, payload: bytes = b"") -> bytes:
    raw = json.dumps(header, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not raw or len(raw) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ValueError("audio_ipc_size_limit")
    return PREFIX.pack(len(raw), len(payload)) + raw + payload


def decode_header(raw: bytes) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise ValueError("invalid_audio_ipc_header")
    return value


def lengths(prefix: bytes) -> tuple[int, int]:
    header, payload = PREFIX.unpack(prefix)
    if not 0 < header <= MAX_HEADER or payload > MAX_PAYLOAD:
        raise ValueError("audio_ipc_size_limit")
    return header, payload


async def read_message(reader: asyncio.StreamReader) -> tuple[dict, bytes]:
    header, payload = lengths(await reader.readexactly(PREFIX.size))
    return decode_header(await reader.readexactly(header)), await reader.readexactly(payload)


def read_file_message(stream) -> tuple[dict, bytes]:
    def exact(size):
        out = bytearray()
        while len(out) < size:
            value = stream.read(size - len(out))
            if not value:
                raise EOFError
            out.extend(value)
        return bytes(out)

    header, payload = lengths(exact(PREFIX.size))
    return decode_header(exact(header)), exact(payload)
