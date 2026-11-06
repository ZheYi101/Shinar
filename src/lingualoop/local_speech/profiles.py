"""Frozen per-turn bindings; process identity excludes supported dynamic options."""

from dataclasses import dataclass
import base64
import hashlib
import json
from pathlib import Path


def instance_key(spec: dict) -> str:
    spec = dict(spec)
    for name in ("speaker_id", "style_id", "voice", "voice_id"):
        spec.pop(name, None)
    if spec.get("adapter") in {"sensevoice-ort", "voicevox", "melo_english"}:
        spec.pop("language", None)
    return json.dumps(spec, sort_keys=True)


@dataclass(frozen=True)
class LocalSpeechProfile:
    task: str
    language: str
    package_id: str
    python: str
    model_json: str
    idle_seconds: int = 120
    reason: str = "explicit prepared runtime"
    attribution: str = ""
    assets_json: str = "{}"

    @property
    def spec(self) -> dict:
        return json.loads(self.model_json)

    def validate_assets(self) -> None:
        if not Path(self.python).is_file() or self.task not in {"stt", "tts"}:
            raise ValueError("prepared_speech_runtime_missing")
        spec = self.spec
        if spec.get("provider", "cpu") not in {"cpu", "cuda"}:
            raise ValueError("unsupported_prepared_device")
        if type(spec.get("gpu_index", 0)) is not int or not 0 <= spec.get("gpu_index", 0) <= 15:
            raise ValueError("invalid_prepared_gpu_index")
        if spec.get("adapter") not in {
            "sensevoice-ort",
            "sensevoice",
            "reazon",
            "vits",
            "voicevox",
            "melo_english",
        }:
            raise ValueError("unsupported_prepared_adapter")
        if (
            spec.get("language") != self.language
            or spec.get("task") != self.task
            or spec.get("id") != self.package_id
        ):
            raise ValueError("prepared_speech_profile_mismatch")
        assets = json.loads(self.assets_json)
        if not assets:
            raise ValueError("prepared_speech_assets_unverified")
        required = set()
        for name in ("model_file", "tokens_file", "config_file", "onnxruntime"):
            if spec.get(name):
                required.add(str(Path(spec[name]).resolve()))
        for name in (
            ("melo_source", "frontend_source", "bert_path", "path")
            if spec["adapter"] in {"vits", "sensevoice", "reazon"}
            else ("melo_source", "frontend_source", "bert_path")
        ):
            if spec.get(name):
                directory = Path(spec[name])
                if not directory.is_dir():
                    raise ValueError("prepared_speech_runtime_assets_missing")
                required.update(
                    str(p.resolve())
                    for p in directory.rglob("*")
                    if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts
                )
        if not required.issubset({str(Path(p).resolve()) for p in assets}):
            raise ValueError("prepared_speech_assets_unverified")
        for name, expected in assets.items():
            path = Path(name)
            if not path.is_file():
                raise ValueError("prepared_speech_asset_mismatch")
            with path.open("rb") as stream:
                observed = hashlib.file_digest(stream, "sha256").hexdigest()
            if observed != expected:
                raise ValueError("prepared_speech_asset_mismatch")
        if self.task == "stt" and not (0 < spec.get("validated_mean_ms", 0) <= 500):
            raise ValueError("prepared_stt_not_latency_qualified")
        if spec["adapter"] == "voicevox" and (
            not spec.get("license_accepted") or not self.attribution
        ):
            raise ValueError("voicevox_license_required")


class LocalSpeechProvider:
    def __init__(self, service, task: str, profile: LocalSpeechProfile | None = None) -> None:
        self.service, self.task, self.profile = service, task, profile
        self.attribution = profile.attribution if profile else ""

    async def bind(self, language: str) -> "LocalSpeechProvider":
        profile = await self.service.resolve(self.task, language)
        return LocalSpeechProvider(self.service, self.task, profile)

    async def transcribe(self, audio: bytes) -> str:
        if self.task != "stt" or self.profile is None:
            raise ValueError("speech_provider_requires_stt_binding")
        if len(audio) > 24 * 1024**2:
            raise ValueError("speech_audio_too_large")
        result = await self.service.execute(self.profile, audio=audio)
        return result["text"]

    async def prepare(self) -> None:
        if self.profile is None:
            raise ValueError("speech_provider_requires_binding")
        await self.service._request(self.task, self.profile.language,
                                    _profile=self.profile, prepare=True)

    async def synthesize(self, text: str) -> bytes:
        if self.task != "tts" or self.profile is None:
            raise ValueError("speech_provider_requires_tts_binding")
        result = await self.service.execute(self.profile, text=text)
        return base64.b64decode(result["audio"], validate=True)

    async def aclose(self) -> None:
        await self.service.close()
