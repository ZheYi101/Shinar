"""Repeatable per-model CPU latency, throughput and public-speech accuracy evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lingualoop.local_speech import adapter_revision
from lingualoop.local_speech.catalog import ModelPackage, load_catalog
from lingualoop.local_speech.downloads import ModelStore, package_lock
from lingualoop.local_speech.hardware import detect_hardware
from lingualoop.local_speech.storage import atomic_json


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_report(path: Path, request: dict) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    partial = request.get("first_partial_only", False)
    expected_schema = "strict-first-partial-v1" if partial else "strict-speech-evaluation-v1"
    if report.get("schema") != expected_schema or any(
        report.get("model", {}).get(key) != request["model"][key] for key in ("id", "language")
    ):
        raise ValueError("Worker result schema or model identity does not match request")
    if partial:
        expected = Counter(item["id"] for item in request["items"])
        observed = Counter(row["item_id"] for row in report["rows"])
    else:
        expected = Counter(
            (item["id"], repeat)
            for item in request["items"]
            for repeat in range(request["repeats"])
        )
        observed = Counter((row["item_id"], row["repeat"]) for row in report["rows"])
    if expected != observed:
        raise ValueError("Worker returned an incomplete or duplicated evaluation corpus")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("build/local-speech-evaluation/strict"))
    parser.add_argument("--cache", type=Path, default=Path("build/local-speech-evaluation/cache"))
    parser.add_argument(
        "--python",
        type=Path,
        default=Path("build/local-speech-evaluation/runtime/Scripts/python.exe"),
    )
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument(
        "--languages", nargs="+", choices=["zh", "en", "ja"], default=["zh", "en", "ja"]
    )
    parser.add_argument("--threads", type=int, choices=[1, 2, 4], default=2)
    parser.add_argument("--stt-repeats", type=int, default=3)
    parser.add_argument("--tts-repeats", type=int, default=5)
    parser.add_argument("--paced-count", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--limit-items", type=int, help="Smoke probe only; not a full corpus run")
    parser.add_argument(
        "--first-partial-only",
        action="store_true",
        help="Clock-paced native first text on every corpus item, stop at first output",
    )
    args = parser.parse_args()
    if not 1 <= args.stt_repeats <= 10 or not 3 <= args.tts_repeats <= 10:
        parser.error("STT repeats 1–10, TTS repeats 3–10")
    root, cache = args.root.resolve(), args.cache.resolve()
    run_dir = (
        args.run_dir or root / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    store = ModelStore(cache)
    packages = load_catalog()
    piper = cache.parent / "piper-evaluation-manifest.json"
    if piper.exists():
        packages.append(ModelPackage.model_validate_json(piper.read_text(encoding="utf-8")))
    jobs = []
    for package in packages:
        if package.files and store.installed(package):
            for language in args.languages:
                if language in package.languages:
                    jobs.append(
                        (
                            package,
                            {
                                "id": package.id,
                                "task": package.task,
                                "adapter": package.adapter,
                                "adapter_revision": adapter_revision(package.adapter),
                                "path": str(store.model_path(package)),
                                "language": language,
                                "fingerprint": package.fingerprint,
                            },
                        )
                    )
    for candidates in sorted(root.glob("*candidates.json")):
        jobs.extend(
            (None, spec)
            for spec in json.loads(candidates.read_text(encoding="utf-8"))
            if spec["language"] in args.languages
        )
    if args.first_partial_only:
        jobs = [
            (package, spec) for package, spec in jobs if spec["adapter"] in {"zipformer", "vosk"}
        ]
    if args.ids:
        unknown = set(args.ids) - {spec["id"] for _, spec in jobs}
        if unknown:
            parser.error("No runnable evaluation job for " + ", ".join(sorted(unknown)))
        jobs = [(package, spec) for package, spec in jobs if spec["id"] in args.ids]
        order = {model_id: index for index, model_id in enumerate(args.ids)}
        jobs.sort(key=lambda job: (order[job[1]["id"]], args.languages.index(job[1]["language"])))
    texts = json.loads(
        Path(__file__)
        .with_name("fixtures")
        .joinpath("speech_tts_texts.json")
        .read_text(encoding="utf-8")
    )
    worker = (
        Path(__file__).resolve().parents[1] / "src/lingualoop/local_speech/evaluation_worker.py"
    )
    snapshot = run_dir / "source_snapshot"
    snapshot.mkdir(exist_ok=True)
    prior_environment = run_dir / "environment.json"
    if prior_environment.exists() and any(
        not (snapshot / name).exists()
        for name in ("evaluation_worker.py", "evaluation_metrics.py", "runtime_worker.py")
    ):
        raise ValueError(
            "Existing run lacks a complete source snapshot; preserve it and choose a fresh --run-dir"
        )
    for name in ("evaluation_worker.py", "evaluation_metrics.py", "runtime_worker.py"):
        frozen = snapshot / name
        if frozen.exists() and sha256(frozen) != sha256(worker.with_name(name)):
            raise ValueError(
                "Worker source changed since this run; preserve its snapshot and choose a fresh --run-dir"
            )
        if not frozen.exists():
            shutil.copyfile(worker.with_name(name), frozen)
    worker = snapshot / "evaluation_worker.py"
    hardware = detect_hardware(cache)
    environment_path = run_dir / "environment.json"
    environment = {
        "hardware": hardware,
        "threads": args.threads,
        "worker_sha256": sha256(worker),
        "tts_texts_sha256": sha256(Path(__file__).with_name("fixtures") / "speech_tts_texts.json"),
        "paid_service_calls": False,
        "normal_learning_database_used": False,
    }
    if environment_path.exists():
        previous = json.loads(environment_path.read_text(encoding="utf-8"))
        identity = ("platform", "architecture", "cpu", "cpu_name", "logical_cpus")
        if previous.get("threads") != args.threads or any(
            previous.get("hardware", {}).get(key) != hardware.get(key) for key in identity
        ):
            raise ValueError("Run hardware/thread profile changed; choose a new --run-dir")
    else:
        atomic_json(environment_path, environment)
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(s in key.upper() for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    env.update(
        {
            "PYTHONUTF8": "1",
            "OMP_NUM_THREADS": str(args.threads),
            "OPENBLAS_NUM_THREADS": str(args.threads),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "GRADIO_ANALYTICS_ENABLED": "False",
        }
    )
    env.pop("PYTHONPATH", None)
    failures = []
    print(f"Run directory: {run_dir}; {len(jobs)} model/language jobs", flush=True)
    for package, spec in jobs:
        destination = run_dir / (spec["id"] + "--" + spec["language"])
        destination.mkdir(parents=True, exist_ok=True)
        if spec["task"] == "stt":
            corpus_path = root / "corpus" / spec["language"]
            manifest = json.loads((corpus_path / "manifest.json").read_text(encoding="utf-8"))
            items = [dict(item, wav=str(corpus_path / item["file"])) for item in manifest["items"]]
            for item in items:
                if sha256(Path(item["wav"])) != item["sha256"]:
                    raise ValueError("Corpus hash mismatch")
            corpus_hash = sha256(corpus_path / "manifest.json")
        else:
            items, corpus_hash = texts[spec["language"]], None
        if args.limit_items:
            items = items[: args.limit_items]
        request = {
            "model": spec,
            "items": items,
            "threads": args.threads,
            "repeats": args.stt_repeats if spec["task"] == "stt" else args.tts_repeats,
            "paced_count": args.paced_count,
            "output_dir": str(destination),
            "corpus_manifest_sha256": corpus_hash,
            "first_partial_only": args.first_partial_only,
        }
        if (destination / "report.json").exists():
            previous = json.loads((destination / "request.json").read_text(encoding="utf-8"))
            previous.setdefault("first_partial_only", False)
            if previous != request:
                raise ValueError("Completed run inputs changed; choose a new --run-dir")
            validate_report(destination / "report.json", request)
            print(f"Already complete and verified: {destination.name}", flush=True)
            continue
        if (destination / "failure.json").exists():
            failures.append(
                {
                    "job": destination.name,
                    "error": "Prior failed attempt preserved; use a fresh --run-dir to retry",
                }
            )
            continue
        if (destination / "request.json").exists():
            failures.append(
                {
                    "job": destination.name,
                    "error": "Prior incomplete attempt preserved, including progress and logs; use a fresh --run-dir",
                }
            )
            print(f"Preserved incomplete attempt: {destination.name}", flush=True)
            continue
        atomic_json(destination / "request.json", request)
        print(f"Starting {destination.name}", flush=True)

        def execute() -> None:
            with (
                (destination / "stdout.txt").open("wb") as stdout,
                (destination / "stderr.txt").open("wb") as stderr,
            ):
                before = time.perf_counter()
                result = subprocess.run(
                    [str(Path(spec.get("python", args.python)).resolve()), str(worker)],
                    input=(json.dumps(request) + "\n").encode(),
                    stdout=stdout,
                    stderr=stderr,
                    env=env,
                    timeout=args.timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode:
                    raise RuntimeError(f"Worker exit {result.returncode}; see isolated stderr.txt")
                validate_report(destination / "report.json", request)
                atomic_json(
                    destination / "validation.json",
                    {
                        "request_sha256": sha256(destination / "request.json"),
                        "report_sha256": sha256(destination / "report.json"),
                        "complete_corpus_verified": True,
                    },
                )
                print(
                    f"Complete {destination.name}: {time.perf_counter() - before:.1f}s", flush=True
                )

        try:
            if package:
                store.verify(package)
                with package_lock(cache, package):
                    if not store.installed(package):
                        raise ValueError("Model changed after verification")
                    execute()
            else:
                execute()
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            failures.append({"job": destination.name, "error": str(exc)})
            atomic_json(destination / "failure.json", failures[-1])
            print(f"FAILED {destination.name}: {exc}", flush=True)
    atomic_json(run_dir / "failures.json", failures)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
