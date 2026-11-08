"""Offline, attributed public speech for the desktop's default speed probe."""

from contextlib import contextmanager
import hashlib
from importlib.resources import as_file, files
import json
from pathlib import Path
from typing import Iterator
import wave


@contextmanager
def benchmark_audio(language: str, custom_path: str | None = None) -> Iterator[Path]:
    """Keep an installed-package resource alive for the entire benchmark process."""
    if custom_path:
        yield Path(custom_path)
        return
    resources = files("shinar.local_speech").joinpath("benchmark_samples")
    manifest = json.loads(resources.joinpath("manifest.json").read_text("utf-8"))
    sample = manifest["items"].get(language)
    if sample is None:
        raise ValueError("speech_benchmark_sample_unavailable")
    with as_file(resources.joinpath(sample["file"])) as path:
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample["sha256"]:
            raise ValueError("speech_benchmark_sample_invalid")
        with wave.open(str(path), "rb") as audio:
            if (
                (audio.getframerate(), audio.getnchannels(), audio.getsampwidth())
                != (16000, 1, 2)
                or audio.getcomptype() != "NONE"
                or not 0 < audio.getnframes() <= 60 * 16000
            ):
                raise ValueError("speech_benchmark_sample_invalid")
        yield path
