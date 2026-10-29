"""Resident JSON-line worker. Audio/transcripts stay in pipes and memory only."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import wave

from runtime_worker import load_model, recognize, synthesize


def load_key(spec):
    result = dict(spec)
    for name in ("speaker_id", "style_id", "voice"):
        result.pop(name, None)
    if spec["adapter"] in {"sensevoice-ort", "voicevox", "melo_english"}:
        result.pop("language", None)
    return result


def audio_samples(encoded: str):
    import numpy as np

    if len(encoded) > 32 * 1024**2:
        raise ValueError("录音过大。")
    audio = base64.b64decode(encoded, validate=True)
    with wave.open(io.BytesIO(audio), "rb") as stream:
        rate = stream.getframerate()
        if (
            stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or rate != 16000
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("本地识别需要 16kHz、单声道、16-bit PCM WAV；请检查录音设备。")
        if not 0 < stream.getnframes() <= rate * 60:
            raise ValueError("录音最长 60 秒。")
        samples = (
            np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32)
            / 32768
        )
        if not len(samples) or not np.any(samples):
            raise ValueError("没有录到有效声音。")
    return rate, samples


def serve() -> None:
    print(json.dumps({"worker_pid": os.getpid()}), flush=True)
    model, loaded_spec = None, None
    while raw := sys.stdin.buffer.readline(34 * 1024**2):
        try:
            request = json.loads(raw)
            spec = request["model"]
            start = time.perf_counter()
            cold = load_key(spec) != loaded_spec
            if cold:
                model = None  # release a previous language/model before allocating the next
                model = load_model(spec, 2)
                loaded_spec = load_key(spec)
            loaded_ms = (time.perf_counter() - start) * 1000
            if spec["task"] == "stt":
                if spec["adapter"] == "sensevoice-ort":
                    model.spec = spec
                result = recognize(
                    model, spec["adapter"], audio_samples(request["audio"]), include_text=True
                )
                if not result["nonempty"]:
                    raise ValueError("没有识别到发言，请重录或使用文字补充。")
            else:
                if spec["adapter"] in {"voicevox", "melo_english"}:
                    model.speaker_id = spec.get("style_id", spec.get("speaker_id", 0))
                text = request["text"]
                if not isinstance(text, str) or not 0 < len(text.strip()) <= 4096:
                    raise ValueError("朗读文本须为 1–4096 字。")
                audio = io.BytesIO()
                result = synthesize(
                    model, spec["language"], output=audio, adapter=spec["adapter"], text=text
                )
                result["audio"] = base64.b64encode(audio.getvalue()).decode("ascii")
            result.update(device=spec["provider"], cold=cold, load_ms=loaded_ms)
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc)
                        if isinstance(exc, ValueError)
                        else "本地推理未完成，请检查模型、运行环境和可用资源。",
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    serve()
