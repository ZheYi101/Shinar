"""Stateful format conversion. Imported only by the audio process."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceFormat:
    rate: int
    channels: int
    sample: str

    def __post_init__(self):
        if not 8000 <= self.rate <= 192000 or not 1 <= self.channels <= 8:
            raise ValueError("unsupported_audio_format")
        if self.sample not in {"int16", "int32", "float32", "uint8"}:
            raise ValueError("unsupported_audio_format")

    @property
    def frame_bytes(self) -> int:
        return self.channels * {"int16": 2, "int32": 4, "float32": 4, "uint8": 1}[self.sample]


class PcmConverter:
    def __init__(self, source: DeviceFormat, target: DeviceFormat, rtc):
        import numpy as np

        self.np, self.source, self.target = np, source, target
        self.pending = bytearray()
        self.resampler = (
            rtc.AudioResampler(source.rate, target.rate, num_channels=1)
            if source.rate != target.rate
            else None
        )

    def push(self, data: bytes) -> bytes:
        np, source = self.np, self.source
        self.pending.extend(data)
        size = len(self.pending) // source.frame_bytes * source.frame_bytes
        if not size:
            return b""
        raw = bytes(self.pending[:size])
        del self.pending[:size]
        dtype = {"int16": "<i2", "int32": "<i4", "float32": "<f4", "uint8": "u1"}[source.sample]
        values = np.frombuffer(raw, dtype=dtype).astype(np.float64).reshape(-1, source.channels)
        if source.sample == "uint8":
            values = (values - 128) / 128
        elif source.sample != "float32":
            values /= 32768 if source.sample == "int16" else 2147483648
        values = np.nan_to_num(values.mean(axis=1), nan=0.0, posinf=1.0, neginf=-1.0)
        mono = np.clip(np.rint(values * 32768), -32768, 32767).astype("<i2").tobytes()
        if self.resampler:
            mono = b"".join(bytes(frame.data) for frame in self.resampler.push(bytearray(mono)))
        return self._encode(mono)

    def flush(self) -> bytes:
        if self.pending:
            raise ValueError("incomplete_audio_sample")
        return (
            self._encode(b"".join(bytes(f.data) for f in self.resampler.flush()))
            if self.resampler
            else b""
        )

    def _encode(self, pcm: bytes) -> bytes:
        np, target = self.np, self.target
        if not pcm:
            return b""
        values = np.frombuffer(pcm, dtype="<i2")
        if target.sample == "int16":
            result = values
        elif target.sample == "int32":
            result = values.astype("<i4") * 65536
        elif target.sample == "float32":
            result = values.astype("<f4") / 32768
        else:
            result = np.clip(values.astype(np.int32) // 256 + 128, 0, 255).astype("u1")
        return np.repeat(result, target.channels).tobytes()


PCM48 = DeviceFormat(48000, 1, "int16")
PCM16 = DeviceFormat(16000, 1, "int16")
