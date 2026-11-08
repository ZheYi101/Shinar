import asyncio
import base64
import io
from types import SimpleNamespace
import wave

import pytest

from shinar.local_speech.service import LocalSpeechService


def test_verification_uses_builtin_audio_and_is_cached_per_resident_profile(tmp_path):
    async def run():
        service = LocalSpeechService(tmp_path)
        pid, requests = [123], []
        service.worker_pid = lambda task: pid[0]

        async def execute(profile, **payload):
            requests.append((profile, payload))
            with wave.open(io.BytesIO(payload["audio"])) as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            return {"text": "A diagnostic transcription, never saved."}

        service.execute = execute
        profile = SimpleNamespace(task="stt", language="en", model_json='{"voice":1}')
        await service.verify(profile)
        await service.verify(profile)
        assert len(requests) == 1 and not list(tmp_path.rglob("*.wav"))
        pid[0] = 456
        await service.verify(profile)
        assert len(requests) == 2
        profile.model_json = '{"voice":2}'
        await service.verify(profile)
        assert len(requests) == 3
        await service._stop("stt")
        assert "stt" not in service._verified

    asyncio.run(run())


@pytest.mark.parametrize("task", ["stt", "tts"])
def test_failed_real_inference_is_not_cached_as_ready(tmp_path, task):
    async def run():
        service = LocalSpeechService(tmp_path)
        service.worker_pid = lambda task: 123

        async def execute(profile, **payload):
            return {"text": " ", "audio": base64.b64encode(b"invalid wav").decode()}

        service.execute = execute
        with pytest.raises(ValueError, match="speech_model_verification_failed"):
            await service.verify(SimpleNamespace(task=task, language="ja", model_json="{}"))
        assert not service._verified

    asyncio.run(run())
