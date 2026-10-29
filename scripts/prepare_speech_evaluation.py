"""Download a bounded, pinned FLEURS test subset; never use private recordings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import tarfile
import wave
from pathlib import Path

import httpx

REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
CONFIGS = {"zh": "cmn_hans_cn", "en": "en_us", "ja": "ja_jp"}
BASE = f"https://huggingface.co/datasets/google/fleurs/resolve/{REVISION}/data"


class BoundedReader:
    def __init__(self, response: httpx.Response, limit: int = 256 * 1024**2):
        self.chunks = response.iter_bytes(65536)
        self.buffer = bytearray()
        self.total = 0
        self.limit = limit

    def read(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = next(self.chunks, b"")
            if not chunk:
                break
            self.total += len(chunk)
            if self.total > self.limit:
                raise ValueError("Corpus transfer exceeded the evaluation limit.")
            self.buffer.extend(chunk)
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data


def prepare(root: Path, language: str, count: int) -> None:
    destination = root / "corpus" / language
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["revision"] == REVISION and len(manifest["items"]) == count:
            for item in manifest["items"]:
                assert (
                    hashlib.sha256((destination / item["file"]).read_bytes()).hexdigest()
                    == item["sha256"]
                )
            print(f"{language}: reused {count} verified public recordings", flush=True)
            return
        raise ValueError("Use a new root for a different corpus selection.")
    config = CONFIGS[language]
    with httpx.Client(timeout=httpx.Timeout(45, connect=20), follow_redirects=True) as client:
        response = client.get(f"{BASE}/{config}/test.tsv")
        response.raise_for_status()
        tsv = response.content
        (destination / "test.tsv").write_bytes(tsv)
        references = {row[1]: row for row in csv.reader(io.StringIO(tsv.decode()), delimiter="\t")}
        items = []
        with client.stream("GET", f"{BASE}/{config}/audio/test.tar.gz") as audio_response:
            audio_response.raise_for_status()
            reader = BoundedReader(audio_response)
            with tarfile.open(fileobj=reader, mode="r|gz") as archive:
                for member in archive:
                    name = Path(member.name).name
                    if not member.isfile() or name not in references or member.size > 4 * 1024**2:
                        continue
                    row = references[name]
                    # Skip >30s before decode, never silently truncate a sentence.
                    if not 16000 <= int(row[5]) <= 30 * 16000:
                        continue
                    data = archive.extractfile(member).read()
                    # FLEURS contains float32 WAV; convert deterministically to the
                    # existing application's 16-bit PCM evaluation input contract.
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-i",
                            "pipe:0",
                            "-ar",
                            "16000",
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(destination / name),
                        ],
                        input=data,
                        capture_output=True,
                        check=True,
                        timeout=10,
                    )
                    converted = (destination / name).read_bytes()
                    with wave.open(io.BytesIO(converted)) as wav:
                        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (
                            16000,
                            1,
                            2,
                        ):
                            raise ValueError("Unexpected FLEURS audio encoding.")
                        duration = wav.getnframes() / 16000
                    items.append(
                        {
                            "id": f"fleurs-{config}-test-{name[:-4]}",
                            "file": name,
                            "reference": row[3],
                            "raw_reference": row[2],
                            "gender": row[6],
                            "duration_s": duration,
                            "sha256": hashlib.sha256(converted).hexdigest(),
                            "source_sha256": hashlib.sha256(data).hexdigest(),
                        }
                    )
                    if len(items) % 10 == 0:
                        print(f"{language}: {len(items)}/{count} recordings", flush=True)
                    if len(items) == count:
                        break
        if len(items) != count:
            raise ValueError("Insufficient eligible public recordings.")
    manifest = {
        "dataset": "google/fleurs",
        "revision": REVISION,
        "config": config,
        "split": "test",
        "license": "CC-BY-4.0",
        "source": "https://huggingface.co/datasets/google/fleurs",
        "selection": "first eligible archive entries, fixed revision; 1–30s, no model-based filtering",
        "tsv_sha256": hashlib.sha256(tsv).hexdigest(),
        "streamed_archive_bytes": reader.total,
        "full_archive_hash_verified": False,
        "conversion": "ffmpeg float32 WAV to 16kHz mono PCM16; no trim or respeed",
        "human_read_speech": True,
        "learner_or_microphone_accuracy_evaluated": False,
        "items": items,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"{language}: saved {count} items, {sum(i['duration_s'] for i in items):.1f}s", flush=True
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("build/local-speech-evaluation/strict"))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--languages", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    args = parser.parse_args()
    if not 20 <= args.count <= 100:
        parser.error("count must be 20–100 per language")
    for language in args.languages:
        prepare(args.root, language, args.count)


if __name__ == "__main__":
    main()
