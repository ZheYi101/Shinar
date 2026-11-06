"""Bounded recurrent VAD and utterance revisions, independent of Qt and RTC."""

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import io
import wave


@dataclass(frozen=True)
class Utterance:
    id: str
    revision: int
    audio: bytes
    ended_samples: int


def pcm_wav(pcm: bytes, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return out.getvalue()


class SileroVad:
    WINDOW = 512

    def __init__(self, model: Path):
        import numpy as np
        import onnxruntime as ort

        self.np = np
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self) -> None:
        self.state = self.np.zeros((2, 1, 128), dtype=self.np.float32)
        self.context = self.np.zeros((1, 64), dtype=self.np.float32)

    def probability(self, pcm: bytes) -> float:
        if len(pcm) != self.WINDOW * 2:
            raise ValueError("vad_requires_512_samples")
        np = self.np
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32).reshape(1, -1) / 32768
        data = np.concatenate((self.context, samples), axis=1)
        output, self.state = self.session.run(
            None, {"input": data, "state": self.state, "sr": np.array(16000, dtype=np.int64)}
        )
        self.context = data[:, -64:].copy()
        return float(output[0][0])


class EndpointDetector:
    """One final owner. A pending utterance is retained until an explicit claim."""

    WINDOW = 512
    MAX_SAMPLES = 16000 * 60
    MAX_BYTES = 24 * 1024**2

    def __init__(self, pause_ms: int = 650):
        if pause_ms not in {650, 1000}:
            raise ValueError("invalid_endpoint_pause")
        self.pause_samples = pause_ms * 16
        self.pre_roll = deque(maxlen=8)  # 256 ms, including onset candidates.
        self.total_samples = 0
        self.reset()

    def reset(self) -> None:
        self.id = ""
        self.revision = 0
        self.pcm = bytearray()
        self.speaking = False
        self.pending = False
        self.onset = self.silence = 0
        self.pre_roll.clear()

    def feed(self, pcm: bytes, probability: float) -> list[tuple[str, object]]:
        if len(pcm) != self.WINDOW * 2 or not 0 <= probability <= 1:
            raise ValueError("invalid_vad_window")
        self.total_samples += self.WINDOW
        events = []
        if self.id and not self.pending:
            self.pcm.extend(pcm)
        else:
            self.pre_roll.append(pcm)
        if probability >= 0.5:
            self.onset += 1
        else:
            self.onset = 0
        if not self.speaking and self.onset >= 3:
            if not self.id:
                self.id = uuid4().hex
                self.pcm.extend(b"".join(self.pre_roll))
            elif self.pending:
                self.pcm.extend(b"".join(self.pre_roll))
            self.revision += 1
            self.speaking, self.pending, self.silence = True, False, 0
            events.append(("started", (self.id, self.revision)))
        if self.id and len(self.pcm) >= min(self.MAX_BYTES, self.MAX_SAMPLES * 2):
            events.append(("limit", None))
            self.reset()
            return events
        if self.speaking:
            self.silence = self.silence + self.WINDOW if probability < 0.35 else 0
            if self.silence >= self.pause_samples:
                self.speaking, self.pending = False, True
                events.append(
                    (
                        "ended",
                        Utterance(
                            self.id, self.revision, pcm_wav(bytes(self.pcm)), self.total_samples
                        ),
                    )
                )
        return events

    def claim(self, utterance_id: str, revision: int) -> bool:
        if not self.pending or self.id != utterance_id or self.revision != revision:
            return False
        self.reset()
        return True
