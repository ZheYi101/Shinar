"""One frozen model/voice specification for benchmarks and live inference."""

import hashlib
import json
from pathlib import Path
from typing import TypedDict, NotRequired

from .catalog import ModelPackage
from .downloads import ModelStore
from .installation import (
    manifest,
    managed_status,
    resource_package,
    runtime_id_for,
    SpeechSetupError,
)
from .profiles import LocalSpeechProfile
from .runtime import runtime_python, runtime_status
from .storage import read_json


class VoiceOption(TypedDict):
    id: str
    label: str
    speaker_id: NotRequired[int]
    style_id: NotRequired[int]
    attribution: NotRequired[str]


def voices(package_id: str, root: Path | None = None) -> list[VoiceOption]:
    options = manifest()["voices"].get(package_id, [])
    if root is not None and package_id == "voicevox-japanese":
        from .catalog import load_catalog

        package = next(p for p in load_catalog() if p.id == package_id)
        path = ModelStore(root).model_path(package) / "0.vvm"
        if path.is_file():
            import zipfile

            try:
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo("metas.json")
                    if info.file_size > 128 * 1024:
                        raise ValueError
                    metadata = json.loads(archive.read(info))
                speaker = next(p for p in metadata if p["name"] == "ずんだもん")
                styles = {
                    s["id"]: s["name"]
                    for s in speaker["styles"]
                    if s["type"] in {"talk", "streaming_talk"}
                }
                options = [
                    {**v, "label": styles[v["style_id"]]}
                    for v in options
                    if v["style_id"] in styles
                ]
            except (ValueError, KeyError, StopIteration, zipfile.BadZipFile):
                raise SpeechSetupError("speech_voice_metadata_invalid") from None
    return options


def voice_choice(root: Path, package_id: str) -> VoiceOption | dict:
    options = voices(package_id, root)
    selected = read_json(root / "voices.json", {}).get(package_id)
    return next((v for v in options if v["id"] == selected), options[0] if options else {})


def accepted_terms(root: Path, package: ModelPackage) -> bool:
    return (
        package.adapter != "voicevox"
        or read_json(root / "voice-terms.json", {}).get(package.id) == package.fingerprint
    )


def build_profile(
    store: ModelStore,
    package: ModelPackage,
    language: str,
    device: str,
    *,
    gpu_index: int = 0,
    vram_budget_mb: int = 3072,
    idle_seconds: int = 120,
    reason: str = "selected local model",
    voice: VoiceOption | None = None,
    python_override: str | None = None,
) -> LocalSpeechProfile:
    if not accepted_terms(store.root, package):
        raise SpeechSetupError("speech_voice_terms_required")
    option = voice if voice is not None else voice_choice(store.root, package.id)
    native = package.adapter in {"voicevox", "melo_english"}
    runtime_id = runtime_id_for(package, device)
    status = (
        managed_status(store.root, runtime_id)
        if native
        else ({"prepared": True} if python_override else runtime_status(store.root, device))
    )
    if not status.get("prepared"):
        raise SpeechSetupError("speech_runtime_not_ready")
    if device == "cuda" and status.get("gpu_index", gpu_index) != gpu_index:
        raise SpeechSetupError("speech_runtime_not_ready")
    python = status["python"] if native else (python_override or runtime_python(store.root, device))
    spec = dict(
        id=package.id,
        task=package.task,
        adapter=package.adapter,
        path=str(store.model_path(package)),
        language=language,
        provider=device,
        gpu_index=gpu_index,
        vram_budget_mb=vram_budget_mb,
    )
    attribution = ""
    if native:
        from .installation import runtime_spec

        spec.update(
            runtime_id=runtime_id,
            runtime_fingerprint=runtime_spec(runtime_id).fingerprint,
            voice_id=option["id"],
            ram_estimate_mb=package.evaluation_budget_mb,
        )
        if option not in voices(package.id):
            raise SpeechSetupError("speech_voice_invalid")
        for key in ("speaker_id", "style_id"):
            if key in option:
                spec[key] = option[key]
        if package.adapter == "voicevox":
            ort = store.model_path(resource_package("voicevox-ort"))
            spec.update(
                model_file=str(store.model_path(package) / "0.vvm"),
                dictionary=str(store.model_path(resource_package("dictionary"))),
                onnxruntime=str(next(ort.rglob("voicevox_onnxruntime.dll"))),
                license_accepted=True,
            )
            attribution = option["attribution"]
        else:
            folder = Path(python).parent.parent
            spec.update(
                model_file=str(store.model_path(package) / "checkpoint.pth"),
                config_file=str(store.model_path(package) / "config.json"),
                bert_path=str(store.model_path(resource_package("bert"))),
                nltk_path=str(folder / "support/nltk_data"),
                melo_source=str(folder / "support/MeloTTS"),
                frontend_source=str(folder / "support/english_frontend"),
            )
    return LocalSpeechProfile(
        package.task,
        language,
        package.id,
        python,
        json.dumps(spec, sort_keys=True),
        idle_seconds,
        reason,
        attribution,
    )


def measurement_identity(
    root: Path, package: ModelPackage, device: str, voice_id: str | None = None
) -> dict:
    if package.adapter not in {"voicevox", "melo_english"}:
        return {}
    from .installation import runtime_spec

    option = next(
        (v for v in voices(package.id) if v["id"] == voice_id), voice_choice(root, package.id)
    )
    return {
        "voice_id": option["id"],
        "runtime_fingerprint": runtime_spec(runtime_id_for(package, device)).fingerprint,
        "frontend_fingerprint": hashlib.sha256(
            json.dumps(manifest().get("support_sha256", {}), sort_keys=True).encode()
        ).hexdigest(),
    }
