"""Independent OpenAI-compatible file transcription and WAV synthesis adapters."""
from __future__ import annotations

import io
import os
import wave
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, SecretStr, field_validator

from shinar.providers.openai_compatible import normalize_openai_base_url

from shinar.configuration import getenv


class SpeechSettings(BaseModel):
    base_url: str
    api_key: SecretStr
    model: str
    voice: str = ""

    @field_validator("base_url")
    @classmethod
    def _url(cls, value: str) -> str:
        try:
            value = normalize_openai_base_url(value)
        except ValueError:
            raise ValueError("Speech endpoint is not a valid URL.") from None
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (
            parsed.scheme == "https" or
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Speech endpoints must use HTTPS (HTTP allowed for localhost).")
        return value

    @classmethod
    def from_env(cls, kind: str) -> SpeechSettings:
        prefix = f"SHINAR_{kind.upper()}_"
        names = ["BASE_URL", "API_KEY", "MODEL"] + (["VOICE"] if kind.upper() == "TTS" else [])
        missing = [prefix + name for name in names if not getenv(prefix + name, "").strip()]
        if missing:
            raise ValueError("缺少语音配置：" + "、".join(missing))
        return cls(base_url=getenv(prefix + "BASE_URL").strip(),
                   api_key=SecretStr(getenv(prefix + "API_KEY").strip()),
                   model=getenv(prefix + "MODEL").strip(),
                   voice=getenv(prefix + "VOICE", "").strip())


def validate_wav(audio: bytes, *, require_speech: bool = False) -> None:
    if len(audio) > 24 * 1024 * 1024:
        raise ValueError("录音过大，请缩短后重录。")
    try:
        with wave.open(io.BytesIO(audio), "rb") as recording:
            frames = recording.readframes(recording.getnframes())
            if not frames or recording.getframerate() <= 0:
                raise ValueError("没有录到音频，请检查麦克风后重录。")
            if require_speech and not any(frames):
                raise ValueError("录音为空或静音，请检查麦克风后重录。")
    except (wave.Error, EOFError) as exc:
        raise ValueError("语音服务需要有效的 PCM WAV 音频。") from exc


class CompatibleSpeechProvider:
    def __init__(self, settings: SpeechSettings, *, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def _post(self, endpoint: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": "Bearer " + self.settings.api_key.get_secret_value()}
        try:
            if self._client is not None:
                response = await self._client.post(self.settings.base_url + endpoint, headers=headers, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                    response = await client.post(self.settings.base_url + endpoint, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException:
            raise RuntimeError("语音服务超时，内容已保留，可以重试。") from None
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"语音服务返回 HTTP {exc.response.status_code}，请检查端点、模型和权限。") from None
        except httpx.HTTPError:
            raise RuntimeError("无法连接语音服务，请检查网络和配置。") from None

    async def transcribe(self, audio: bytes) -> str:
        validate_wav(audio, require_speech=True)
        response = await self._post("/audio/transcriptions",
                                    files={"file": ("recording.wav", audio, "audio/wav")},
                                    data={"model": self.settings.model, "response_format": "json"})
        try:
            text = response.json()["text"]
        except (ValueError, KeyError, TypeError):
            raise ValueError("识别结果格式无效，请重试或使用文字补充。") from None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("没有识别到发言，请重录或使用文字补充。")
        return text.strip()

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("没有可以朗读的回复。")
        if len(text) > 4096:
            raise ValueError("回复过长，暂不能完整朗读；文字回复已保留。")
        response = await self._post("/audio/speech", json={
            "model": self.settings.model, "voice": self.settings.voice,
            "input": text, "response_format": "wav",
        })
        validate_wav(response.content)
        return response.content
