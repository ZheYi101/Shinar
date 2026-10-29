"""Fetch evaluation-only candidate assets without changing the public model catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

import httpx

from lingualoop.local_speech.catalog import safe_relative
from lingualoop.local_speech.storage import atomic_json


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download_ranges(
    client: httpx.Client,
    source: str,
    expected: str,
    total: int,
    path: Path,
    *,
    block_size: int = 16 * 1024**2,
) -> dict:
    """Bounded range transfer; promote only after a pinned upstream digest matches."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and digest(path) == expected:
        return {
            "url": source,
            "size": total,
            "sha256": expected,
            "hash_kind": "pinned upstream SHA256 verified",
        }
    partial = path.with_name(path.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > total or block_size <= 0:
        raise ValueError("Invalid partial size or range block size")
    while offset < total:
        end = min(total - 1, offset + block_size - 1)
        for attempt in range(4):
            try:
                expected_range = f"bytes {offset}-{end}/{total}"
                data = bytearray()
                with client.stream(
                    "GET", source, headers={"Range": f"bytes={offset}-{end}"}
                ) as response:
                    response.raise_for_status()
                    if (
                        response.status_code != 206
                        or response.headers.get("content-range") != expected_range
                    ):
                        raise ValueError("Official source returned an unexpected byte range")
                    for chunk in response.iter_bytes(1024**2):
                        data.extend(chunk)
                        if len(data) > end - offset + 1:
                            raise ValueError("Range response exceeded its declared size")
                if len(data) != end - offset + 1:
                    raise ValueError("Incomplete range response")
                with partial.open("ab") as output:
                    output.write(data)
                offset = end + 1
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        if offset == total or offset // (128 * 1024**2) != (offset - len(data)) // (128 * 1024**2):
            print(f"{path.name}: {offset // 1024**2}/{total // 1024**2} MiB", flush=True)
    if digest(partial) != expected:
        raise ValueError("Asset hash differs from pinned upstream; not installed")
    partial.replace(path)
    meta = {
        "url": source,
        "size": total,
        "sha256": expected,
        "hash_kind": "pinned upstream SHA256 verified",
    }
    atomic_json(path.with_name(path.name + ".download.json"), meta)
    return meta


def download_qwen_weight(
    client: httpx.Client, repo: str, name: str, entry: dict, path: Path
) -> dict:
    return download_ranges(
        client,
        f"https://modelscope.cn/models/{repo}/resolve/master/{name}",
        entry["lfs"]["sha256"],
        entry["size"],
        path,
    )


def download(client: httpx.Client, url: str, path: Path, limit: int = 1024**3) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = path.with_name(path.name + ".download.json")
    if path.exists() and metadata.exists():
        recorded = json.loads(metadata.read_text(encoding="utf-8"))
        if recorded["url"] == url and digest(path) == recorded["sha256"]:
            return recorded
        raise ValueError("Candidate file differs from its recorded hash.")
    partial = path.with_name(path.name + ".part")
    for attempt in range(4):
        offset = partial.stat().st_size if partial.exists() else 0
        try:
            with client.stream(
                "GET", url, headers={"Range": f"bytes={offset}-"} if offset else {}
            ) as response:
                response.raise_for_status()
                append = offset and response.status_code == 206
                if append and not response.headers.get("content-range", "").startswith(
                    f"bytes {offset}-"
                ):
                    raise ValueError("Unexpected candidate download range.")
                with partial.open("ab" if append else "wb") as output:
                    for chunk in response.iter_bytes(1024**2):
                        if output.tell() + len(chunk) > limit:
                            raise ValueError("Candidate download exceeded its size limit.")
                        output.write(chunk)
            partial.replace(path)
            recorded = {
                "url": url,
                "size": path.stat().st_size,
                "sha256": digest(path),
                "hash_kind": "locally observed, not an author signature",
            }
            atomic_json(metadata, recorded)
            print(f"Downloaded {path.name}: {recorded['size']} bytes", flush=True)
            return recorded
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 3:
                raise
            print(f"Retry {path.name}, attempt {attempt + 2}", flush=True)
    raise RuntimeError("Unreachable download state")


def extract_zip(path: Path, destination: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512 * 1024**2:
            raise ValueError("Expanded candidate exceeds limit.")
        names = set()
        for info in archive.infolist():
            name = safe_relative(info.filename.rstrip("/"))
            if name in names or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Unsafe candidate archive.")
            names.add(name)
            target = destination / name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))


def extract_tar(path: Path, destination: Path, limit: int = 512 * 1024**2) -> None:
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if sum(member.size for member in members) > limit:
            raise ValueError("Candidate archive expansion exceeds limit")
        names = set()
        for member in members:
            name = safe_relative(member.name.rstrip("/"))
            if name in names:
                raise ValueError("Duplicate candidate archive entry")
            names.add(name)
            target = destination / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
            else:
                raise ValueError("Unsafe candidate archive entry")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("build/local-speech-evaluation/strict"))
    parser.add_argument(
        "--families",
        nargs="+",
        choices=[
            "vosk",
            "whisper",
            "kokoro",
            "voicevox",
            "qwen_asr",
            "qwen_tts",
            "sensevoice",
            "piper",
            "zipformer",
            "kokoro_cutlet",
        ],
        default=["vosk", "whisper", "kokoro"],
    )
    parser.add_argument("--manifest", default="candidates.json")
    parser.add_argument(
        "--voicevox-license-accepted",
        action="store_true",
        help="Use only after the human accepts VOICEVOX model/voice terms",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = root / safe_relative(args.manifest)
    specs = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []

    def record(spec: dict) -> None:
        nonlocal specs
        specs = [
            old for old in specs if (old["id"], old["language"]) != (spec["id"], spec["language"])
        ] + [spec]
        for attempt in range(10):
            try:
                atomic_json(manifest, specs)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.2)

    with httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=True) as client:
        if "kokoro_cutlet" in args.families:
            base = next(
                spec
                for path in root.glob("*candidates.json")
                for spec in json.loads(path.read_text(encoding="utf-8"))
                if spec["id"] == "kokoro-ja-v10-int8"
            )
            record(
                dict(
                    base,
                    id="kokoro-ja-v10-int8-cutlet",
                    frontend_mode="cutlet_unidic_lite",
                    frontend="misaki Cutlet + UniDic-lite 2.1.2",
                )
            )
        if "zipformer" in args.families:
            from lingualoop.local_speech.catalog import load_catalog
            from lingualoop.local_speech.downloads import ModelStore

            store = ModelStore(root.parent / "cache")
            package = next(p for p in load_catalog() if p.id == "zipformer-small-zhen-20230216")
            store.verify(package)
            target = store.model_path(package)
            for variant, encoder_suffix, joiner_suffix in [
                ("fp32-decoder", ".int8.onnx", ".int8.onnx"),
                ("fp32", ".onnx", ".onnx"),
            ]:
                files = {
                    "encoder_file": str(target / ("encoder-epoch-99-avg-1" + encoder_suffix)),
                    "decoder_file": str(target / "decoder-epoch-99-avg-1.onnx"),
                    "joiner_file": str(target / ("joiner-epoch-99-avg-1" + joiner_suffix)),
                }
                for language in ["zh", "en"]:
                    record(
                        {
                            "id": "zipformer-small-zhen-" + variant,
                            "task": "stt",
                            "adapter": "zipformer",
                            "language": language,
                            "path": str(target),
                            **files,
                            "asset_sha256": {
                                key: digest(Path(path)) for key, path in files.items()
                            },
                            "decoding_method": "greedy_search",
                            "catalog_family": "zipformer-configuration-reference",
                        }
                    )
        if "piper" in args.families:
            for language, name in [("zh", "zh_CN-huayan-medium"), ("en", "en_US-amy-low")]:
                target = root / "candidate_models"
                archive_name = "vits-piper-" + name
                path = target / (archive_name + ".tar.bz2")
                meta = download(
                    client,
                    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{path.name}",
                    path,
                )
                destination = target / archive_name
                if not (destination / "tokens.txt").exists():
                    extract_tar(path, target)
                record(
                    {
                        "id": "piper-" + name.lower().replace("_", "-") + "-evaluation",
                        "task": "tts",
                        "adapter": "vits",
                        "language": language,
                        "path": str(destination),
                        "asset": meta,
                        "catalog_family": "piper-language-voices",
                        "license_scope": "technical evaluation only; individual voice redistribution not approved",
                    }
                )
        if "sensevoice" in args.families:
            revision = "2365baeacb507f821a0c8120fcee3d484dba7a07"
            repo = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
            target = root / "candidate_models/sensevoice-original-20240717"
            assets = [
                download(
                    client,
                    f"https://huggingface.co/{repo}/resolve/{revision}/{name}",
                    target / name,
                )
                for name in ["model.int8.onnx", "tokens.txt", "LICENSE"]
            ]
            for language in ["zh", "en", "ja"]:
                record(
                    {
                        "id": "sensevoice-original-20240717-int8",
                        "task": "stt",
                        "adapter": "sensevoice",
                        "language": language,
                        "path": str(target),
                        "revision": revision,
                        "assets": assets,
                        "catalog_family": "sensevoice-original-reference",
                    }
                )
        for family, repo, revision in [
            ("qwen_asr", "Qwen/Qwen3-ASR-0.6B", "5eb144179a02acc5e5ba31e748d22b0cf3e303b0"),
            (
                "qwen_tts",
                "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                "85e237c12c027371202489a0ec509ded67b5e4b5",
            ),
        ]:
            if family not in args.families:
                continue
            info = client.get(
                f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
            )
            info.raise_for_status()
            target = root / "candidate_models" / repo.split("/")[1]
            assets = []
            for entry in info.json()["siblings"]:
                name = safe_relative(entry["rfilename"])
                if name.endswith((".json", ".safetensors", ".txt")):
                    if name.endswith(".safetensors"):
                        assets.append(
                            download_qwen_weight(client, repo, name, entry, target / name)
                        )
                    else:
                        assets.append(
                            download(
                                client,
                                f"https://huggingface.co/{repo}/resolve/{revision}/{name}",
                                target / name,
                                3 * 1024**3,
                            )
                        )
            for language in ["zh", "en", "ja"]:
                record(
                    {
                        "id": "qwen3-asr-06b" if family == "qwen_asr" else "qwen3-tts-06b",
                        "task": "stt" if family == "qwen_asr" else "tts",
                        "adapter": family,
                        "language": language,
                        "path": str(target),
                        "revision": revision,
                        "assets": assets,
                        "provider": "cuda",
                        "dtype": "bfloat16",
                        "python": str(
                            root
                            / ("qwen-asr-runtime" if family == "qwen_asr" else "qwen-tts-runtime")
                            / "Scripts/python.exe"
                        ),
                        "voice": {"zh": "Vivian", "en": "Ryan", "ja": "Ono_Anna"}[language],
                    }
                )
        if "vosk" in args.families:
            for language, name in [
                ("zh", "vosk-model-small-cn-0.22"),
                ("en", "vosk-model-small-en-us-0.15"),
                ("ja", "vosk-model-small-ja-0.22"),
            ]:
                path = root / "candidate_models" / (name + ".zip")
                meta = download(client, f"https://alphacephei.com/vosk/models/{name}.zip", path)
                target = path.parent / name
                if not (target / "am/final.mdl").exists():
                    extract_zip(path, path.parent)
                record(
                    {
                        "id": name,
                        "task": "stt",
                        "adapter": "vosk",
                        "language": language,
                        "path": str(target),
                        "source": "https://alphacephei.com/vosk/models",
                        "asset": meta,
                        "catalog_family": "vosk-small-language-packs",
                    }
                )
        if "whisper" in args.families:
            revision = "536b0662742c02347bc0e980a01041f333bce120"
            target = root / "candidate_models/faster-whisper-small"
            assets = [
                download(
                    client,
                    f"https://huggingface.co/Systran/faster-whisper-small/resolve/{revision}/{name}",
                    target / name,
                )
                for name in ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
            ]
            for language in ["zh", "en", "ja"]:
                record(
                    {
                        "id": "faster-whisper-small",
                        "task": "stt",
                        "adapter": "faster_whisper",
                        "language": language,
                        "path": str(target),
                        "revision": revision,
                        "assets": assets,
                        "catalog_family": "whisper-small-multilingual",
                        "decoding": "cpu int8, beam_size=1, no VAD, no previous text",
                    }
                )
        if "kokoro" in args.families:
            target = root / "candidate_models/kokoro-ja-v10"
            base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
            assets = [
                download(client, f"{base}/{name}", target / name)
                for name in ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"]
            ]
            record(
                {
                    "id": "kokoro-ja-v10-int8",
                    "task": "tts",
                    "adapter": "kokoro_ja",
                    "language": "ja",
                    "model_file": str(target / "kokoro-v1.0.int8.onnx"),
                    "voices_file": str(target / "voices-v1.0.bin"),
                    "voice": "jf_alpha",
                    "assets": assets,
                    "catalog_family": "kokoro-japanese-frontend",
                    "frontend": "misaki JAG2P pyopenjtalk",
                }
            )
        if "voicevox" in args.families:
            target = root / "candidate_models/voicevox-0.17.1"
            base = "https://github.com/VOICEVOX/voicevox_core/releases/download/0.17.1"
            download(
                client,
                base + "/download-windows-x64.exe",
                target / "download-windows-x64.exe",
                64 * 1024**2,
            )
            download(
                client,
                base + "/voicevox_core-0.17.1-cp310-abi3-win_amd64.whl",
                target / "voicevox_core-0.17.1-cp310-abi3-win_amd64.whl",
                64 * 1024**2,
            )
            # An explicit preparation command, never run as part of timed inference.
            help_result = subprocess.run(
                [str(target / "download-windows-x64.exe"), "--help"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            (target / "downloader-help.txt").write_text(
                help_result.stdout + help_result.stderr, encoding="utf-8"
            )
            print("VOICEVOX downloader help saved; fixed assets prepared separately.", flush=True)
            if args.voicevox_license_accepted:
                assets = [
                    download(
                        client,
                        "https://github.com/VOICEVOX/voicevox_vvm/releases/download/0.17.0/0.vvm",
                        target / "0.vvm",
                    ),
                    download(
                        client,
                        "https://github.com/VOICEVOX/voicevox_vvm/releases/download/0.17.0/README.txt",
                        target / "VOICEVOX-TERMS.txt",
                    ),
                ]
                runtime = target / "voicevox_onnxruntime-win-x64-1.23.2.tgz"
                assets.append(
                    download(
                        client,
                        "https://github.com/VOICEVOX/onnxruntime-builder/releases/download/voicevox_onnxruntime-1.23.2/voicevox_onnxruntime-win-x64-1.23.2.tgz",
                        runtime,
                    )
                )
                with tarfile.open(runtime) as archive:
                    if sum(member.size for member in archive.getmembers()) > 256 * 1024**2:
                        raise ValueError("VOICEVOX runtime expansion exceeds limit")
                    for member in archive.getmembers():
                        name = safe_relative(member.name.rstrip("/"))
                        destination = target / name
                        if member.isdir():
                            destination.mkdir(parents=True, exist_ok=True)
                        elif member.isfile():
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(archive.extractfile(member).read())
                        else:
                            raise ValueError("Unexpected VOICEVOX runtime archive entry")
                record(
                    {
                        "id": "voicevox-zundamon-0.17.1",
                        "task": "tts",
                        "adapter": "voicevox",
                        "language": "ja",
                        "path": str(target),
                        "style_id": 3,
                        "onnxruntime": str(next(target.rglob("voicevox_onnxruntime.dll"))),
                        "model_file": str(target / "0.vvm"),
                        "assets": assets,
                        "attribution": "VOICEVOX:ずんだもん",
                        "human_license_acceptance": True,
                        "catalog_family": "voicevox-japanese",
                    }
                )


if __name__ == "__main__":
    main()
