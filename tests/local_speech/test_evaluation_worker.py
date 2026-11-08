"""Timing semantics with controlled clocks; no real model or network is loaded."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")


@pytest.fixture
def worker(monkeypatch):
    directory = Path(__file__).resolve().parents[2] / "src/shinar/local_speech"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "strict_eval_worker_test", directory / "evaluation_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    value = 0.0

    def perf_counter(self):
        return self.value

    def sleep(self, duration):
        self.value += duration


@pytest.mark.parametrize("partial_only", [False, True])
def test_streaming_first_partial_includes_audio_wait_and_flush_is_separate(
    worker, monkeypatch, partial_only
):
    clock = Clock()
    monkeypatch.setattr(worker, "time", clock)

    class Stream:
        chunks = 0
        pending = False

        def accept_waveform(self, rate, samples):
            self.chunks += 1
            self.pending = True

        def input_finished(self):
            pass

    class Model:
        def create_stream(self):
            return Stream()

        def is_ready(self, stream):
            return stream.pending

        def decode_stream(self, stream):
            clock.value += 0.01
            stream.pending = False

        def get_result(self, stream):
            return "你好" if stream.chunks >= 2 else ""

    result = worker.recognize(
        Model(),
        {"adapter": "zipformer"},
        (16000, np.ones(8000)),
        paced=True,
        partial_only=partial_only,
    )
    assert result["first_text_wall_ms"] == pytest.approx(410)
    assert result["first_partial_audio_position_ms"] == 400
    assert result["compute_ms"] == pytest.approx(20 if partial_only else 40)
    assert result["finalization_compute_ms"] == pytest.approx(0 if partial_only else 10)
    assert result["synthetic_flush_padding_ms"] == (0 if partial_only else 660)
    assert result["processed_audio_s"] == (0.4 if partial_only else 0.5)
    assert result["vad_endpoint_measured"] is False


def test_offline_result_is_not_reported_as_native_partial(worker, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, "time", clock)
    stream = SimpleNamespace(accept_waveform=lambda *_: None, result=SimpleNamespace(text="日本語"))
    model = SimpleNamespace(create_stream=lambda: stream, decode_stream=lambda _: clock.sleep(0.25))
    result = worker.recognize(model, {"adapter": "sensevoice"}, (16000, np.ones(16000)))
    assert result["first_text_wall_ms"] == 250
    assert result["first_partial_audio_position_ms"] is None
    assert result["native_partial"] is False


def test_cold_and_repeated_tts_waveforms_are_retained_separately(worker, monkeypatch, tmp_path):
    import sys

    clock = Clock()
    monkeypatch.setattr(worker, "time", clock)
    memory = SimpleNamespace(rss=123, peak_wset=456)
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Process=lambda: SimpleNamespace(memory_info=lambda: memory)),
    )

    def generate(text, sid, callback):
        samples = np.ones(2400, dtype=np.float32) * 0.1
        clock.sleep(0.01)
        callback(samples, 1)
        return SimpleNamespace(samples=samples, sample_rate=24000)

    monkeypatch.setattr(worker, "load", lambda *_: SimpleNamespace(generate=generate))
    report = worker.run(
        {
            "model": {"id": "fake-tts", "task": "tts", "adapter": "vits", "language": "en"},
            "threads": 2,
            "items": [
                {"id": "a", "text": "Hello.", "category": "short"},
                {"id": "b", "text": "Goodbye.", "category": "short"},
            ],
            "repeats": 3,
            "output_dir": str(tmp_path),
        }
    )
    previews = {row["preview"] for row in report["rows"]}
    assert len(previews) == 6
    assert report["first_inference"]["preview"] not in previews
    assert all(Path(path).is_file() for path in previews)
    assert Path(report["first_inference"]["preview"]).is_file()
    assert len(list((tmp_path / "audio").glob("*.wav"))) == 7


def test_first_pcm_complete_generation_and_spoken_speed_are_distinct(worker, monkeypatch, tmp_path):
    clock = Clock()
    monkeypatch.setattr(worker, "time", clock)

    def generate(text, sid, callback):
        clock.sleep(0.1)
        callback(np.zeros(2400), 0.1)
        clock.sleep(0.3)
        callback(np.ones(21600) * 0.2, 1)
        return SimpleNamespace(
            samples=np.r_[np.zeros(2400), np.ones(21600) * 0.2], sample_rate=24000
        )

    result = worker.synthesize(
        SimpleNamespace(generate=generate),
        {"adapter": "vits", "language": "zh"},
        "这是测试。",
        tmp_path / "test.wav",
    )
    assert result["first_pcm_ms"] == 100
    assert result["first_nonzero_callback_ms"] == 400
    assert result["compute_ms"] == 400
    assert result["characters_per_compute_s"] == 10
    assert result["spoken_characters_per_s"] == 4
    assert result["leading_below_minus50db_ms"] == 100


def test_silent_output_cannot_pass_as_valid_audio(worker):
    model = SimpleNamespace(
        generate=lambda *_, **__: SimpleNamespace(samples=np.zeros(16000), sample_rate=16000)
    )
    with pytest.raises(ValueError, match="silent"):
        worker.synthesize(model, {"adapter": "vits", "language": "en"}, "Hello.")


def test_wav_header_bytes_cannot_be_counted_as_first_pcm(worker):
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 100)
    data = buffer.getvalue()
    assert worker.wav_data_offset(data[:20]) is None
    assert worker.wav_data_offset(data) == 44
