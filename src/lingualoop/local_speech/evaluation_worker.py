"""Isolated strict evaluation worker. Public corpus text is saved only in its run folder."""

from __future__ import annotations

import hashlib
import asyncio
import importlib.metadata
import io
import json
import random
import struct
import sys
import time
import wave
from pathlib import Path

from evaluation_metrics import (
    aggregate_accuracy,
    distribution,
    error_metrics,
    normalized_characters,
)
from runtime_worker import load_model, read_wav


def wav_data_offset(header: bytes) -> int | None:
    if len(header) < 12:
        return None
    if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("Streaming TTS did not return a WAV header.")
    position = 12
    while position + 8 <= len(header):
        size = struct.unpack_from("<I", header, position + 4)[0]
        if header[position : position + 4] == b"data":
            return position + 8
        position += 8 + size + size % 2
    return None


def load(spec: dict, threads: int):
    if spec["adapter"] == "zipformer" and spec.get("encoder_file"):
        import sherpa_onnx

        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(Path(spec["path"]) / "tokens.txt"),
            encoder=spec["encoder_file"],
            decoder=spec["decoder_file"],
            joiner=spec["joiner_file"],
            num_threads=threads,
            enable_endpoint_detection=False,
            provider="cpu",
            decoding_method=spec.get("decoding_method", "greedy_search"),
        )
    if spec["adapter"] in {"qwen_asr", "qwen_tts"}:
        import torch

        torch.set_num_threads(threads)
        torch.manual_seed(9321)
        if not torch.cuda.is_available():
            raise ValueError("CUDA runtime is unavailable; no silent CPU fallback.")
        dtype = getattr(torch, spec.get("dtype", "bfloat16"))
        if dtype == torch.bfloat16 and not torch.cuda.is_bf16_supported():
            raise ValueError("The selected GPU does not support this bfloat16 profile.")
        if spec["adapter"] == "qwen_asr":
            from qwen_asr import Qwen3ASRModel

            return Qwen3ASRModel.from_pretrained(
                spec["path"],
                dtype=dtype,
                device_map="cuda:0",
                max_new_tokens=512,
                attn_implementation="sdpa",
            )
        from qwen_tts import Qwen3TTSModel

        return Qwen3TTSModel.from_pretrained(
            spec["path"], device_map="cuda:0", dtype=dtype, attn_implementation="sdpa"
        )
    if spec["adapter"] == "voicevox":
        import pyopenjtalk
        from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

        dictionary = pyopenjtalk.OPEN_JTALK_DICT_DIR
        if isinstance(dictionary, bytes):
            dictionary = dictionary.decode()
        if not Path(dictionary).exists():
            raise ValueError("Prepare the Open JTalk dictionary before timing.")
        model = Synthesizer(
            Onnxruntime.load_once(filename=spec["onnxruntime"]),
            OpenJtalk(dictionary),
            acceleration_mode="CPU",
            cpu_num_threads=threads,
        )
        with VoiceModelFile.open(spec["model_file"]) as voices:
            model.load_voice_model(voices)
        return model
    if spec["adapter"] == "vosk":
        import vosk

        vosk.SetLogLevel(-1)
        return vosk.Model(spec["path"])
    if spec["adapter"] == "faster_whisper":
        from faster_whisper import WhisperModel

        return WhisperModel(
            spec["path"],
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
            num_workers=1,
            local_files_only=True,
        )
    if spec["adapter"] == "kokoro_ja":
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        from misaki.ja import JAG2P

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            spec["model_file"], sess_options=options, providers=["CPUExecutionProvider"]
        )
        if spec.get("frontend_mode") == "cutlet_unidic_lite":
            import unidic
            import unidic_lite

            # Configure the dictionary before Fugashi constructs its Tagger;
            # this affects only the isolated evaluation process.
            unidic.DICDIR = unidic_lite.DICDIR
            frontend = JAG2P(version="cutlet")
        else:
            frontend = JAG2P(version="pyopenjtalk")
        return Kokoro.from_session(session, spec["voices_file"]), frontend
    return load_model(spec, threads)


def recognize(
    model, spec: dict, audio: tuple, paced: bool = False, partial_only: bool = False
) -> dict:
    import numpy as np

    rate, samples = audio
    adapter = spec["adapter"]
    if partial_only and adapter not in {"zipformer", "vosk"}:
        raise ValueError("This adapter has no native partial text API.")
    if spec.get("provider") == "cuda":
        import torch

        torch.cuda.synchronize()
    begin = time.perf_counter()
    first_text = first_audio_position = None
    partial_changes = 0
    last_partial = ""
    cpu_ms = 0.0
    if adapter == "qwen_asr":
        result = model.transcribe(
            audio=(samples, rate),
            language={"zh": "Chinese", "en": "English", "ja": "Japanese"}[spec["language"]],
        )
        torch.cuda.synchronize()
        text = result[0].text
        cpu_ms = final_ms = (time.perf_counter() - begin) * 1000
        first_text = cpu_ms if text.strip() else None
    elif adapter == "sensevoice":
        stream = model.create_stream()
        stream.accept_waveform(rate, samples)
        model.decode_stream(stream)
        text = stream.result.text
        cpu_ms = final_ms = (time.perf_counter() - begin) * 1000
        first_text = cpu_ms if text.strip() else None
    elif adapter == "faster_whisper":
        segments, _ = model.transcribe(
            samples,
            language=spec["language"],
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        parts = []
        for segment in segments:
            parts.append(segment.text)
            if first_text is None and segment.text.strip():
                first_text = (time.perf_counter() - begin) * 1000
        text = "".join(parts)
        cpu_ms = final_ms = (time.perf_counter() - begin) * 1000
    else:
        if adapter == "vosk":
            from vosk import KaldiRecognizer

            stream = KaldiRecognizer(model, rate)
            fragments = []
        else:
            stream = model.create_stream()
        for position in range(0, len(samples), 3200):
            end = min(position + 3200, len(samples))
            if paced:
                time.sleep(max(0, begin + end / rate - time.perf_counter()))
            before = time.perf_counter()
            if adapter == "vosk":
                pcm = (samples[position:end] * 32768).astype("<i2").tobytes()
                if stream.AcceptWaveform(pcm):
                    fragments.append(json.loads(stream.Result()).get("text", ""))
                partial = " ".join(
                    fragments + [json.loads(stream.PartialResult()).get("partial", "")]
                )
            else:
                stream.accept_waveform(rate, samples[position:end])
                while model.is_ready(stream):
                    model.decode_stream(stream)
                partial = model.get_result(stream)
            cpu_ms += (time.perf_counter() - before) * 1000
            if partial.strip() and first_text is None:
                first_text = (time.perf_counter() - begin) * 1000
                first_audio_position = end / rate * 1000
            if partial.strip() != last_partial.strip():
                partial_changes += 1
                last_partial = partial
            if partial_only and first_text is not None:
                break
        before = time.perf_counter()
        if partial_only:
            text = last_partial
        elif adapter == "vosk":
            fragments.append(json.loads(stream.FinalResult()).get("text", ""))
            text = " ".join(fragments)
        else:
            stream.accept_waveform(rate, np.zeros(int(rate * 0.66), dtype=np.float32))
            stream.input_finished()
            while model.is_ready(stream):
                model.decode_stream(stream)
            text = model.get_result(stream)
        final_ms = (time.perf_counter() - before) * 1000
        cpu_ms += final_ms
    wall_ms = (time.perf_counter() - begin) * 1000
    duration_s = len(samples) / rate
    processed_audio_s = end / rate if partial_only else duration_s
    return {
        "hypothesis": text.strip(),
        "compute_ms": cpu_ms,
        "finalization_compute_ms": final_ms,
        "first_text_wall_ms": first_text,
        "first_partial_audio_position_ms": first_audio_position,
        "native_partial": adapter in {"zipformer", "vosk"},
        "paced_input": paced,
        "partial_changes": partial_changes,
        "wall_ms": wall_ms,
        "input_duration_s": duration_s,
        "rtf": cpu_ms / (processed_audio_s * 1000),
        "output_characters_per_compute_s": len(normalized_characters(text)) / (cpu_ms / 1000),
        "synthetic_flush_padding_ms": 660 if adapter == "zipformer" and not partial_only else 0,
        "vad_endpoint_measured": False,
        "partial_only": partial_only,
        "processed_audio_s": processed_audio_s,
    }


def synthesize(model, spec: dict, text: str, output: Path | None = None) -> dict:
    import numpy as np

    if spec.get("provider") == "cuda":
        import torch

        torch.cuda.synchronize()
    begin = time.perf_counter()
    callbacks = []
    frontend_ms = None

    def callback(samples, _progress):
        if len(samples):
            callbacks.append(
                {
                    "ms": (time.perf_counter() - begin) * 1000,
                    "samples": len(samples),
                    "nonzero": bool(np.any(samples)),
                }
            )
        return 1

    if spec["adapter"] == "qwen_tts":
        audios, rate = model.generate_custom_voice(
            text=text,
            language={"zh": "Chinese", "en": "English", "ja": "Japanese"}[spec["language"]],
            speaker=spec["voice"],
            max_new_tokens=2048,
        )
        torch.cuda.synchronize()
        samples = audios[0]
        callback(samples, 1)
    elif spec["adapter"] == "voicevox":
        query = model.create_audio_query(text, spec["style_id"])
        frontend_ms = (time.perf_counter() - begin) * 1000
        chunks = []
        header, pcm_started = bytearray(), False
        for index, chunk in enumerate(model.streaming_synthesis(query, spec["style_id"])):
            chunks.append(chunk)
            if not pcm_started:
                header.extend(chunk)
                offset = wav_data_offset(header)
                if offset is None:
                    continue
                pcm, pcm_started = header[offset:], True
            else:
                pcm = chunk
            if pcm:
                callback(np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768, 0)
        with wave.open(io.BytesIO(b"".join(chunks))) as wav:
            rate = wav.getframerate()
            samples = (
                np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)
                / 32768
            )
    elif spec["adapter"] == "kokoro_ja":
        kokoro, g2p = model
        phonemes, _ = g2p(text)
        frontend_ms = (time.perf_counter() - begin) * 1000

        async def generate():
            chunks, sample_rate = [], None
            async for chunk, sample_rate in kokoro.create_stream(
                phonemes, voice=spec["voice"], is_phonemes=True
            ):
                callback(chunk, 0)
                chunks.append(chunk)
            if not chunks:
                raise ValueError("Kokoro did not emit audio.")
            return np.concatenate(chunks), sample_rate

        samples, rate = asyncio.run(generate())
    else:
        sid = spec.get("sid", 3 if spec["language"] == "zh" and spec["adapter"] == "kokoro" else 0)
        result = model.generate(text, sid=sid, callback=callback)
        samples, rate = result.samples, result.sample_rate
    elapsed_ms = (time.perf_counter() - begin) * 1000
    samples = np.asarray(samples, dtype=np.float32)
    if not len(samples) or not np.all(np.isfinite(samples)) or not np.any(samples):
        raise ValueError("TTS generated empty, silent or nonfinite audio.")
    duration_s = len(samples) / rate
    characters = len(normalized_characters(text))
    audible = np.flatnonzero(np.abs(samples) > 0.0031623)  # -50 dBFS amplitude, diagnostic only
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return {
        "compute_ms": elapsed_ms,
        "frontend_ms": frontend_ms,
        "first_pcm_ms": callbacks[0]["ms"] if callbacks else None,
        "first_nonzero_callback_ms": next((c["ms"] for c in callbacks if c["nonzero"]), None),
        "callbacks": callbacks,
        "duration_s": duration_s,
        "sample_rate": rate,
        "characters": characters,
        "characters_per_compute_s": characters / (elapsed_ms / 1000),
        "spoken_characters_per_s": characters / duration_s,
        "rtf": elapsed_ms / (duration_s * 1000),
        "peak_amplitude": float(np.max(np.abs(samples))),
        "rms_dbfs": float(20 * np.log10(max(float(np.sqrt(np.mean(samples**2))), 1e-10))),
        "clipping_fraction": float(np.mean(np.abs(samples) >= 0.999)),
        "leading_below_minus50db_ms": float(audible[0] / rate * 1000) if len(audible) else None,
        "human_listening_score": None,
    }


def run(request: dict) -> dict:
    import psutil

    spec = request["model"]
    before = time.perf_counter()
    model = load(spec, request["threads"])
    load_peak_cuda_allocated = load_peak_cuda_reserved = None
    if spec.get("provider") == "cuda":
        import torch

        torch.cuda.synchronize()
        load_peak_cuda_allocated = torch.cuda.max_memory_allocated()
        load_peak_cuda_reserved = torch.cuda.max_memory_reserved()
        torch.cuda.reset_peak_memory_stats()
    load_ms = (time.perf_counter() - before) * 1000
    rows, first, paced = [], None, []
    items = request["items"]

    def checkpoint(values: list[dict]) -> None:
        folder = Path(request["output_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"progress-{len(values):04d}.json"
        path.write_text(
            json.dumps(
                {
                    "complete": False,
                    "model": spec,
                    "load_ms": load_ms,
                    "first_inference": first,
                    "rows": values,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if request.get("first_partial_only"):
        warmup = recognize(model, spec, read_wav(items[0]["wav"]), partial_only=True)
        partial_rows = []
        for item in items:
            row = recognize(model, spec, read_wav(item["wav"]), paced=True, partial_only=True)
            row["item_id"] = item["id"]
            partial_rows.append(row)
            if len(partial_rows) % 10 == 0:
                checkpoint(partial_rows)
                print(
                    json.dumps({"progress": f"first partial {len(partial_rows)}/{len(items)}"}),
                    flush=True,
                )
        return {
            "schema": "strict-first-partial-v1",
            "model": spec,
            "load_ms": load_ms,
            "threads": request["threads"],
            "first_stream_unpaced": warmup,
            "rows": partial_rows,
            "first_text_ms": distribution(
                [
                    row["first_text_wall_ms"]
                    for row in partial_rows
                    if row["first_text_wall_ms"] is not None
                ]
            ),
            "missing_partial": sum(row["first_text_wall_ms"] is None for row in partial_rows),
            "recordings": len(partial_rows),
            "live_microphone_evaluated": False,
            "scope": "200ms clock-paced public file replay, stop at first native text; includes source silence and acoustic context",
        }
    if spec.get("attribution"):
        attribution = Path(request["output_dir"]) / "ATTRIBUTION.txt"
        attribution.write_text(
            spec["attribution"] + "\nhttps://github.com/VOICEVOX/voicevox_vvm\n", encoding="utf-8"
        )
    for repeat in range(request["repeats"]):
        order = list(items)
        random.Random(9321 + repeat).shuffle(order)
        for item in order:
            if spec["task"] == "stt":
                audio = read_wav(item["wav"])
                row = recognize(model, spec, audio)
                row["accuracy"] = error_metrics(
                    item["reference"], row["hypothesis"], spec["language"]
                )
                row["reference_characters_per_compute_s"] = len(
                    normalized_characters(item["reference"])
                ) / (row["compute_ms"] / 1000)
            else:
                audio_folder = Path(request["output_dir"]) / "audio"
                preview = audio_folder / f"{item['id']}--r{repeat}.wav"
                measured_audio = (
                    audio_folder / f"cold--{item['id']}.wav" if first is None else preview
                )
                row = synthesize(model, spec, item["text"], measured_audio)
                row.update(
                    {
                        "text": item["text"],
                        "category": item["category"],
                        "preview": str(measured_audio),
                    }
                )
            row.update({"item_id": item["id"], "repeat": repeat})
            if first is None:
                first = row.copy()
                # Measure an additional run so every text has the same warm sample count.
                if spec["task"] == "stt":
                    row = recognize(model, spec, audio)
                    row["accuracy"] = error_metrics(
                        item["reference"], row["hypothesis"], spec["language"]
                    )
                    row["reference_characters_per_compute_s"] = len(
                        normalized_characters(item["reference"])
                    ) / (row["compute_ms"] / 1000)
                else:
                    row = synthesize(model, spec, item["text"], preview)
                    row.update(
                        {
                            "text": item["text"],
                            "category": item["category"],
                            "preview": str(preview),
                        }
                    )
                row.update({"item_id": item["id"], "repeat": repeat})
            rows.append(row)
            if len(rows) % 10 == 0:
                checkpoint(rows)
        checkpoint(rows)
        print(
            json.dumps({"progress": f"{spec['id']} {spec['language']} repeat {repeat + 1}"}),
            flush=True,
        )
    if spec["task"] == "stt" and spec["adapter"] in {"zipformer", "vosk"}:
        for item in sorted(items, key=lambda row: row["id"])[: request.get("paced_count", 3)]:
            row = recognize(model, spec, read_wav(item["wav"]), paced=True)
            row["item_id"] = item["id"]
            paced.append(row)
    fields = (
        "compute_ms",
        "first_pcm_ms",
        "first_text_wall_ms",
        "finalization_compute_ms",
        "characters_per_compute_s",
        "reference_characters_per_compute_s",
        "rtf",
        "spoken_characters_per_s",
        "output_characters_per_compute_s",
    )
    summary = {
        field: distribution([row[field] for row in rows if row.get(field) is not None])
        for field in fields
    }
    if spec["task"] == "stt":
        # Accuracy once per unique recording; timing repeats must not inflate corpus size.
        summary["accuracy"] = aggregate_accuracy([row for row in rows if row["repeat"] == 0])
        summary["audio_duration_s"] = sum(item["duration_s"] for item in items)
        summary["corpus_characters_per_compute_s"] = sum(
            len(normalized_characters(item["reference"])) for item in items
        ) / sum(row["compute_ms"] / 1000 for row in rows if row["repeat"] == 0)
    memory = psutil.Process().memory_info()
    versions = {}
    for package in [
        "sherpa-onnx",
        "numpy",
        "psutil",
        "vosk",
        "faster-whisper",
        "ctranslate2",
        "kokoro-onnx",
        "misaki",
        "unidic-lite",
        "voicevox-core",
        "torch",
        "transformers",
        "qwen-asr",
        "qwen-tts",
    ]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    result = {
        "schema": "strict-speech-evaluation-v1",
        "model": spec,
        "threads": request["threads"],
        "load_ms": load_ms,
        "first_inference": first,
        "rows": rows,
        "paced": paced,
        "summary": summary,
        "versions": versions,
        "peak_process_rss_bytes": getattr(memory, "peak_wset", memory.rss),
        "peak_memory_kind": "process_peak" if hasattr(memory, "peak_wset") else "final_rss",
        "human_listening_evaluated": False,
        "live_chain_evaluated": False,
        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "metrics_sha256": hashlib.sha256(
            Path(__file__).with_name("evaluation_metrics.py").read_bytes()
        ).hexdigest(),
        "runtime_worker_sha256": hashlib.sha256(
            Path(__file__).with_name("runtime_worker.py").read_bytes()
        ).hexdigest(),
    }
    if spec.get("provider") == "cuda":
        result["inference_peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated()
        result["peak_cuda_allocated_bytes"] = max(
            load_peak_cuda_allocated, torch.cuda.max_memory_allocated()
        )
        result["peak_cuda_reserved_bytes"] = max(
            load_peak_cuda_reserved, torch.cuda.max_memory_reserved()
        )
        result["cuda_device"] = torch.cuda.get_device_name()
    return result


def main() -> None:
    request = json.loads(sys.stdin.readline())
    result = run(request)
    output = Path(request["output_dir"]) / "report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(output)}), flush=True)


if __name__ == "__main__":
    main()
