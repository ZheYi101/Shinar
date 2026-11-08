"""ASR round-trip of public TTS prompts; an intelligibility proxy, not human MOS."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from shinar.local_speech.storage import atomic_json
from evaluate_local_speech import sha256, validate_report
from report_speech_evaluation import collect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("build/local-speech-evaluation/strict"))
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--output", type=Path, help="Use a new directory if source audio or judge set changes"
    )
    parser.add_argument(
        "--judges", nargs="+", default=["sensevoice-original-20240717-int8", "faster-whisper-small"]
    )
    args = parser.parse_args()
    root = args.root.resolve()
    reports = [r for r in collect(args.runs) if r["model"]["task"] == "tts"]
    output = args.output.resolve() if args.output else root / "roundtrip"
    output.mkdir(parents=True, exist_ok=True)
    suite = {
        "judges": args.judges,
        "inputs": [
            {
                "report_sha256": sha256(Path(report["report_path"])),
                "item_id": row["item_id"],
                "source_audio_sha256": sha256(Path(row["preview"])),
            }
            for report in reports
            for row in report["rows"]
            if row["repeat"] == 0
        ],
    }
    suite_path = output / "suite.json"
    if suite_path.exists() and json.loads(suite_path.read_text(encoding="utf-8")) != suite:
        raise ValueError(
            "Roundtrip source suite changed; choose a new --output before overwriting audio"
        )
    incomplete = [
        path.parent.name
        for path in output.glob("*/request.json")
        if not path.with_name("report.json").exists()
    ]
    if incomplete:
        raise ValueError(
            "Prior incomplete roundtrip preserved; choose a new --output: " + ", ".join(incomplete)
        )
    atomic_json(suite_path, suite)
    snapshot = output / "source_snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "src/shinar/local_speech"
    for name in ["evaluation_worker.py", "evaluation_metrics.py", "runtime_worker.py"]:
        if not (snapshot / name).exists():
            shutil.copyfile(source / name, snapshot / name)
    items_by_language = {language: [] for language in ["zh", "en", "ja"]}
    source_items = {}
    for report in reports:
        for row in report["rows"]:
            if row["repeat"] != 0:
                continue
            model = report["model"]
            item_id = model["id"] + "__" + model["language"] + "__" + row["item_id"]
            wav = output / "audio16k" / (item_id + ".wav")
            wav.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    row["preview"],
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(wav),
                ],
                capture_output=True,
                check=True,
                timeout=20,
            )
            item = {
                "id": item_id,
                "wav": str(wav),
                "reference": row["text"],
                "duration_s": row["duration_s"],
                "sha256": sha256(wav),
                "source_audio_sha256": sha256(Path(row["preview"])),
            }
            items_by_language[model["language"]].append(item)
            source_items[item_id] = {
                "tts_model": model["id"],
                "language": model["language"],
                "text_id": row["item_id"],
                "category": row["category"],
                "sha256": item["sha256"],
            }
    specs = []
    for path in root.glob("*candidates.json"):
        specs.extend(json.loads(path.read_text(encoding="utf-8")))
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(s in key.upper() for s in ["API_KEY", "TOKEN", "SECRET", "PASSWORD"])
    }
    env.update(
        {
            "PYTHONUTF8": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "GRADIO_ANALYTICS_ENABLED": "False",
            "OMP_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
        }
    )
    env.pop("PYTHONPATH", None)
    atomic_json(output / "source-items.json", source_items)
    completed = []
    for judge in args.judges:
        for language, items in items_by_language.items():
            if not items:
                continue
            model = next(s for s in specs if s["id"] == judge and s["language"] == language)
            destination = output / (judge + "--" + language)
            destination.mkdir(parents=True, exist_ok=True)
            request = {
                "model": model,
                "items": items,
                "threads": 2,
                "repeats": 1,
                "paced_count": 0,
                "output_dir": str(destination),
                "scope": "synthetic TTS roundtrip; not real-human ASR accuracy or MOS",
            }
            request_path = destination / "request.json"
            if (destination / "report.json").exists():
                if json.loads(request_path.read_text(encoding="utf-8")) != request:
                    raise ValueError("Roundtrip inputs changed; use a new evaluation root")
                validate_report(destination / "report.json", request)
                completed.append(destination.name)
                continue
            atomic_json(request_path, request)
            with (
                (destination / "stdout.txt").open("wb") as stdout,
                (destination / "stderr.txt").open("wb") as stderr,
            ):
                result = subprocess.run(
                    [
                        str(root / "runtime/Scripts/python.exe"),
                        str(snapshot / "evaluation_worker.py"),
                    ],
                    input=(json.dumps(request) + "\n").encode(),
                    stdout=stdout,
                    stderr=stderr,
                    env=env,
                    timeout=1800,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            if result.returncode:
                raise RuntimeError("Roundtrip worker failed: " + str(destination))
            validate_report(destination / "report.json", request)
            completed.append(destination.name)
            print(f"Completed {judge} {language}: {len(items)} synthetic utterances", flush=True)
    atomic_json(output / "source-items.json", source_items)
    atomic_json(
        output / "complete.json",
        {
            "schema": "tts-roundtrip-suite-v1",
            "jobs": completed,
            "synthetic_utterances": len(source_items),
            "judges": args.judges,
            "human_listening_evaluated": False,
        },
    )


if __name__ == "__main__":
    main()
