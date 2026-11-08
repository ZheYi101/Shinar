import asyncio
import io
import wave

import httpx
import pytest
from pydantic import SecretStr

from shinar.providers.speech import CompatibleSpeechProvider, SpeechSettings, validate_wav


def wav_bytes(*, silence=False):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((b"\0\0" if silence else b"\x01\x02") * 800)
    return buffer.getvalue()


def settings():
    return SpeechSettings(base_url="https://speech.example.test/v1", api_key=SecretStr("private-test-key"), model="configured-model", voice="configured-voice")


def test_transcription_and_synthesis_use_independent_configured_audio_api():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("transcriptions"):
            assert b"configured-model" in request.content
            assert b"recording.wav" in request.content
            return httpx.Response(200, json={"text": "  旅行が好きです。  "})
        assert b'"response_format":"wav"' in request.content
        return httpx.Response(200, content=wav_bytes())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = CompatibleSpeechProvider(settings(), client=client)
            assert await provider.transcribe(wav_bytes()) == "旅行が好きです。"
            assert await provider.synthesize("いいですね。") == wav_bytes()
        assert len(calls) == 2
        assert calls[0].headers["authorization"] == "Bearer private-test-key"
    asyncio.run(run())


@pytest.mark.parametrize("audio", [b"", b"not a wav", wav_bytes(silence=True)])
def test_empty_or_invalid_recording_is_not_uploaded(audio):
    with pytest.raises(ValueError):
        validate_wav(audio, require_speech=True)


def test_speech_errors_preserve_privacy_and_allow_manual_retry():
    def handler(request):
        return httpx.Response(403, text="private-test-key and private source text")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = CompatibleSpeechProvider(settings(), client=client)
            with pytest.raises(RuntimeError, match="HTTP 403") as error:
                await provider.transcribe(wav_bytes())
            assert "private" not in str(error.value)
    asyncio.run(run())


def test_timeout_and_invalid_transcript_have_actionable_errors():
    async def run():
        def timeout(request): raise httpx.ReadTimeout("private internal details")
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with pytest.raises(RuntimeError, match="超时"):
                await CompatibleSpeechProvider(settings(), client=client).synthesize("はい。")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"text": ""}))) as client:
            with pytest.raises(ValueError, match="没有识别"):
                await CompatibleSpeechProvider(settings(), client=client).transcribe(wav_bytes())
    asyncio.run(run())


def test_missing_speech_config_does_not_inherit_text_credentials(monkeypatch):
    for suffix in ("BASE_URL", "API_KEY", "MODEL", "VOICE"):
        monkeypatch.delenv("SHINAR_STT_" + suffix, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "text-only-key")
    with pytest.raises(ValueError, match="SHINAR_STT"):
        SpeechSettings.from_env("STT")


@pytest.mark.parametrize("url", ["http://speech.example.test", "http://localhost.evil.test", "https://user:password@example.test"])
def test_speech_endpoint_requires_https_and_does_not_accept_embedded_credentials(url):
    with pytest.raises(ValueError):
        SpeechSettings(base_url=url, api_key=SecretStr("test"), model="test")
