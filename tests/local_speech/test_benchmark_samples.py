import hashlib
from importlib.resources import files
import json
import wave

import pytest

from shinar.local_speech.samples import benchmark_audio


@pytest.mark.parametrize("language", ["zh", "en", "ja"])
def test_bundled_demo_is_public_attributed_pcm_and_hash_verified(language):
    resources = files("shinar.local_speech").joinpath("benchmark_samples")
    manifest = json.loads(resources.joinpath("manifest.json").read_text("utf-8"))
    assert manifest["license"] == "CC-BY-4.0"
    assert "Google" in resources.joinpath("LICENSE.txt").read_text("utf-8")
    with benchmark_audio(language) as path, wave.open(str(path), "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
        assert 3 <= audio.getnframes() / 16000 <= 10
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["items"][language]["sha256"]
        assert any(audio.readframes(audio.getnframes()))


def test_custom_recording_stays_optional_and_unknown_language_is_explicit(tmp_path):
    custom = tmp_path / "own.wav"
    with benchmark_audio("fr", str(custom)) as path:
        assert path == custom
    with pytest.raises(ValueError, match="speech_benchmark_sample_unavailable"):
        with benchmark_audio("fr"):
            pytest.fail("Must not silently use a different language's audio")


def test_corrupt_bundled_demo_never_reaches_inference(tmp_path, monkeypatch):
    import shinar.local_speech.samples as module

    resources = tmp_path / "benchmark_samples"
    resources.mkdir()
    (resources / "manifest.json").write_text(json.dumps({"items": {"en": {
        "file": "en.wav", "sha256": "0" * 64,
    }}}))
    (resources / "en.wav").write_bytes(b"bad audio")
    monkeypatch.setattr(module, "files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="speech_benchmark_sample_invalid"):
        with benchmark_audio("en"):
            pytest.fail("Corrupt audio must not reach inference")
