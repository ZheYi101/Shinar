"""Short-lived, bounded evaluation process. Never imports Qt or cloud providers."""

from __future__ import annotations

import json
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def read_wav(path):
    import numpy as np

    if Path(path).stat().st_size > 24 * 1024**2:
        raise ValueError("测速 WAV 最多 24 MiB。")
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("测速需要单声道 16-bit PCM WAV。")
        rate = stream.getframerate()
        if rate != 16000 or not 0 < stream.getnframes() <= rate * 60:
            raise ValueError("测速需要 16kHz、1–60 秒 WAV。")
        samples = (
            np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32)
            / 32768
        )
    if not np.any(samples):
        raise ValueError("测速音频不能是全静音。")
    return rate, samples


def load_model(spec, threads):
    if spec.get("cuda_dll_directory"):
        import os
        os.environ["LINGUALOOP_CUDA_DLL_DIR"] = spec["cuda_dll_directory"]
    if spec.get("nltk_path"):
        import os
        os.environ["NLTK_DATA"] = spec["nltk_path"]
    if spec["adapter"] in {"voicevox", "melo_english"}:
        from native_tts import NativeTts
        return NativeTts(spec, threads)
    if spec["adapter"] == "sensevoice-ort":
        from sensevoice import SenseVoiceOrt

        return SenseVoiceOrt(spec, threads)
    if spec.get("provider", "cpu") != "cpu":
        raise ValueError("此适配器尚未开放 GPU，未静默改用 CPU。")
    import sherpa_onnx as sherpa

    path = Path(spec["path"])
    adapter = spec["adapter"]
    if adapter == "reazon":
        return sherpa.OfflineRecognizer.from_transducer(
            encoder=str(path / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(path / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(path / "joiner-epoch-99-avg-1.int8.onnx"),
            tokens=str(path / "tokens.txt"),
            num_threads=threads,
            provider="cpu",
        )
    if adapter == "sensevoice":
        return sherpa.OfflineRecognizer.from_sense_voice(
            model=str(path / "model.int8.onnx"),
            tokens=str(path / "tokens.txt"),
            num_threads=threads,
            language=spec["language"],
            use_itn=False,
            provider="cpu",
        )
    if adapter == "zipformer":

        def find(pattern, *, exclude_int8=False):
            matches = [
                item for item in path.glob(pattern) if not exclude_int8 or ".int8." not in item.name
            ]
            if len(matches) != 1:
                raise ValueError("模型文件不完整。")
            return str(matches[0])

        return sherpa.OnlineRecognizer.from_transducer(
            tokens=str(path / "tokens.txt"),
            encoder=find("encoder-*.int8.onnx"),
            # The official file-decoding configuration keeps the decoder FP32.
            # This package's INT8 decoder severely deletes speech on the public corpus.
            decoder=find("decoder-*.onnx", exclude_int8=True),
            joiner=find("joiner-*.int8.onnx"),
            num_threads=threads,
            enable_endpoint_detection=False,
            provider="cpu",
        )
    return _load_tts(sherpa, path, adapter, threads)


def recognize(model, adapter, audio, *, include_text=False):
    import numpy as np

    rate, samples = audio
    start = time.perf_counter()
    stream = model.create_stream() if adapter != "sensevoice-ort" else None
    first_partial = None
    if adapter == "sensevoice-ort":
        text = model.transcribe(rate, samples)
        final_compute = (time.perf_counter() - start) * 1000
    elif adapter in {"sensevoice", "reazon"}:
        stream.accept_waveform(rate, samples)
        model.decode_stream(stream)
        text = stream.result.text
        final_compute = (time.perf_counter() - start) * 1000
    else:
        for position in range(0, len(samples), 3200):
            stream.accept_waveform(rate, samples[position : position + 3200])
            while model.is_ready(stream):
                model.decode_stream(stream)
            if first_partial is None and model.get_result(stream).strip():
                first_partial = min(position + 3200, len(samples)) / rate * 1000
        final_start = time.perf_counter()
        stream.accept_waveform(rate, np.zeros(int(rate * 0.66), dtype=np.float32))
        stream.input_finished()
        while model.is_ready(stream):
            model.decode_stream(stream)
        text = model.get_result(stream)
        final_compute = (time.perf_counter() - final_start) * 1000
    elapsed = (time.perf_counter() - start) * 1000
    result = {
        "compute_ms": elapsed,
        "finalization_compute_ms": final_compute,
        "rtf": elapsed / (len(samples) / rate * 1000),
        "first_partial_audio_position_ms": first_partial,
        "recognized_characters": len(text.strip()),
        "nonempty": bool(text.strip()),
    }
    if include_text:
        result["text"] = text.strip()
    return result


TEXTS = {
    "ja": [
        "物語の中で、どの人物が印象に残りましたか。",
        "あの結末についてどう思いますか。",
        "少し意外な選択でしたね。",
    ],
    "zh": [
        "你更喜欢故事里的哪位人物？",
        "我觉得结尾留下了很多没有说出口的话。",
        "这个角色的选择让我有些意外。",
    ],
    "en": [
        "Which character stayed with you after reading?",
        "I thought the ending left a lot unsaid.",
        "That choice surprised me a little.",
    ],
}


def synthesize(model, language, index=0, output=None, adapter="kokoro", *, text=None):
    import numpy as np

    start = time.perf_counter()
    first = None

    def callback(samples, progress):
        nonlocal first
        if len(samples) and first is None:
            first = (time.perf_counter() - start) * 1000
        return 1

    # v1_1-zh differs from v1_0: af_maple=0, zf_001=3.
    sid = (3 if language == "zh" else 0) if adapter == "kokoro" else 0
    result = model.generate(text or TEXTS[language][index % 3], sid=sid, callback=callback)
    elapsed = (time.perf_counter() - start) * 1000
    samples = np.asarray(result.samples)
    if not len(samples) or not np.all(np.isfinite(samples)) or not np.any(samples):
        raise ValueError("模型没有生成有效音频。")
    if output:
        with wave.open(output if hasattr(output, "write") else str(output), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(result.sample_rate)
            stream.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return {
        "compute_ms": elapsed,
        "first_pcm_ms": first if first is not None else elapsed,
        "duration_ms": len(samples) / result.sample_rate * 1000,
        "rtf": elapsed / (len(samples) / result.sample_rate * 1000),
    }


def evaluate(request):
    import psutil
    sherpa_version = None
    if any(s["adapter"] not in {"voicevox", "melo_english", "sensevoice-ort"} for s in request["models"]):
        import sherpa_onnx
        sherpa_version = sherpa_onnx.__version__.split("+")[0]
        if sherpa_version != request["runtime_version"]:
            raise ValueError("本地推理运行时版本不匹配，请安装项目固定的 local-speech extra。")
    if any(s["adapter"] == "sensevoice-ort" for s in request["models"]):
        import onnxruntime

        if onnxruntime.__version__ != "1.23.2":
            raise ValueError("SenseVoice GPU 适配需要 ONNX Runtime 1.23.2。")
    start = time.perf_counter()
    specs = request["models"]
    loaded, cold = {}, {}
    for spec in specs:
        before = time.perf_counter()
        loaded[spec["task"]] = load_model(spec, request["threads"])
        cold[spec["id"]] = (time.perf_counter() - before) * 1000
    asr = next((s for s in specs if s["task"] == "stt"), None)
    tts = next((s for s in specs if s["task"] == "tts"), None)
    audio = read_wav(request["wav"]) if asr else None

    # Warmup is measured and reported separately, never silently discarded.
    def run_asr():
        return recognize(loaded["stt"], asr["adapter"], audio)

    def run_tts(i=0, output=None):
        return synthesize(loaded["tts"], tts["language"], i, output, tts["adapter"])

    warmup = {}
    if asr:
        warmup["stt"] = run_asr()
    if tts:
        warmup["tts"] = run_tts(output=request.get("preview"))
    sequential = {"stt": [], "tts": []}
    for i in range(request["repeats"]):
        if asr:
            sequential["stt"].append(run_asr())
        if tts:
            sequential["tts"].append(run_tts(i))
    concurrent = {"stt": [], "tts": []}
    if asr and tts:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for i in range(request["repeats"]):
                recognition = pool.submit(run_asr)
                synthesis = pool.submit(run_tts, i)
                concurrent["stt"].append(recognition.result())
                concurrent["tts"].append(synthesis.result())
    memory = psutil.Process().memory_info()
    return {
        "runtime_version": sherpa_version,
        "sherpa_build": sherpa_version,
        "provider": specs[0].get("provider", "cpu")
        if len({s.get("provider", "cpu") for s in specs}) == 1
        else "mixed",
        "devices": {s["id"]: s.get("provider", "cpu") for s in specs},
        "gpu_index": next(
            (s.get("gpu_index", 0) for s in specs if s.get("provider") == "cuda"), None
        ),
        "runtime_versions": {
            s["id"]: "1.23.2"
            if s["adapter"] == "sensevoice-ort"
            else "voicevox-0.17.1" if s["adapter"] == "voicevox"
            else "torch-2.9.1-transformers-4.57.3" if s["adapter"] == "melo_english"
            else sherpa_version
            for s in specs
        },
        "threads_per_model": request["threads"],
        "cold_load_ms": cold,
        "warmup": warmup,
        "sequential": sequential,
        "concurrent": concurrent,
        "peak_process_rss_bytes": getattr(memory, "peak_wset", memory.rss),
        "peak_memory_kind": "process_peak" if hasattr(memory, "peak_wset") else "final_rss",
        "wall_ms": (time.perf_counter() - start) * 1000,
        "scope": "compute_only; no VAD endpoint, microphone, LLM, RTC, or audible playback",
    }


def main():
    try:
        request = json.loads(sys.stdin.readline())
        result = evaluate(request)
        print(json.dumps({"ok": True, "result": result}), flush=True)
    except Exception as exc:
        # Do not forward native logs, file paths, or audio/transcripts to the UI.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc)
                    if isinstance(exc, ValueError)
                    else "本地运行失败，请检查 local-speech 依赖、模型文件及语言。",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1
    return 0




def _load_tts(sherpa, path, adapter, threads):
    if adapter == "kokoro":
        config = sherpa.OfflineTtsConfig()
        config.model.kokoro.model = str(path / "model.int8.onnx")
        config.model.kokoro.voices = str(path / "voices.bin")
        config.model.kokoro.tokens = str(path / "tokens.txt")
        config.model.kokoro.data_dir = str(path / "espeak-ng-data")
        config.model.kokoro.dict_dir = str(path / "dict")
        config.model.kokoro.lexicon = ",".join(
            str(path / f"lexicon-{name}.txt") for name in ("us-en", "zh")
        )
        config.rule_fsts = ",".join(
            str(path / name) for name in ("date-zh.fst", "number-zh.fst", "phone-zh.fst")
        )
        config.model.num_threads = threads
        config.model.provider = "cpu"
        config.max_num_sentences = 1
        if not config.validate():
            raise ValueError("TTS 模型配置无效。")
        return sherpa.OfflineTts(config)
    if adapter == "vits":
        config = sherpa.OfflineTtsConfig()
        piper = not (path / "model.onnx").exists()
        models = list(path.glob("*.onnx")) if piper else [path / "model.onnx"]
        if len(models) != 1:
            raise ValueError("VITS 模型主文件不唯一。")
        config.model.vits.model = str(models[0])
        config.model.vits.tokens = str(path / "tokens.txt")
        if piper:
            config.model.vits.data_dir = str(path / "espeak-ng-data")
        else:
            config.model.vits.lexicon = str(path / "lexicon.txt")
            config.model.vits.dict_dir = str(path / "dict")
        config.rule_fsts = ",".join(
            str(path / name)
            for name in ("date.fst", "number.fst", "phone.fst", "new_heteronym.fst")
            if (path / name).exists()
        )
        config.model.num_threads = threads
        config.model.provider = "cpu"
        config.max_num_sentences = 1
        if not config.validate():
            raise ValueError("VITS 模型配置无效。")
        return sherpa.OfflineTts(config)
    raise ValueError("模型运行适配器尚未实现。")


if __name__ == "__main__":
    raise SystemExit(main())
