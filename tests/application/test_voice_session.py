import asyncio
import io
import wave

import pytest

from shinar.application.learning_workbench import LearningWorkbench
from shinar.application.voice_session import VoiceSessionCoordinator
from shinar.application.speech_text import SpeechTextBuffer
from shinar.core.domain import LanguageEnum, MessageRole, ProficiencyLevel
from shinar.infrastructure import SQLiteStore
from shinar.providers.mock import MockLearningLLMProvider


def wav_bytes(rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x10\x01" * (rate // 20))
    return output.getvalue()


class Speech:
    def __init__(self):
        self.texts = []

    async def transcribe(self, audio):
        return "I think she waited."

    async def synthesize(self, text):
        self.texts.append(text)
        return wav_bytes(24000)


class Dialogue(MockLearningLLMProvider):
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.histories = []

    async def stream_reply(self, **kwargs):
        self.calls += 1
        self.histories.append(kwargs["message_history"])
        yield "She waited. "
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("mock_failure")
        yield "Why do you think so?"


async def make_work(path, provider=None):
    provider = provider or Dialogue()
    work = LearningWorkbench(provider, event_store=SQLiteStore(path))
    await work.load_material(
        title="Bridge",
        content="Mira waited at the bridge. Ren left.",
        source_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.ENGLISH,
        native_language=LanguageEnum.CHINESE,
        learner_level=ProficiencyLevel.A2,
    )
    await work.start_session()
    return work, provider


def test_draft_confirmation_order_and_idempotency(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        speech, audio = Speech(), []

        async def consume(segment):
            audio.append(segment)

        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech, on_audio=consume)
        before = len(work.session.messages)
        draft = await voice.recognize(wav_bytes())
        assert len(work.session.messages) == before and provider.calls == 0
        result = await voice.submit_confirmed(draft, edited_text="She stayed.")
        assert result.text_status == result.speech_status == "completed"
        assert [a.index for a in audio] == [0, 1]
        assert all(a.sample_rate == 24000 for a in audio)
        assert provider.calls == 1
        assert [m.content for m in provider.histories[0]].count("She stayed.") == 1
        assert work.session.messages[-2].content == "She stayed."
        repeated = await voice.submit_confirmed(draft, edited_text="She stayed.")
        assert repeated.turn_id == result.turn_id and repeated.speech_status == "skipped"
        assert provider.calls == 1 and len(audio) == 2
        events = await work._event_store.list_session_events(work.session.id)
        user_events = [event for event in events if event.event_type.value == "message.user_added"]
        assert len(user_events) == 1
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_automatic_transcript_and_text_only_never_bind_tts(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        confirmed = []

        class NoTTS(Speech):
            async def bind(self, language):
                raise AssertionError("disabled TTS must not be bound")

        voice = VoiceSessionCoordinator(work, stt=Speech(), tts=NoTTS(),
                                        on_turn_confirmed=confirmed.append)
        draft = await voice.recognize(wav_bytes())
        result = await voice.submit_confirmed(draft, speak=False,
                                              confirmation_kind="automatic_transcript")
        assert result.text_status == "completed" and result.speech_status == "skipped"
        assert len(confirmed) == 1 and provider.calls == 1
        assert work.session.messages[-2].metadata["confirmation_kind"] == "automatic_transcript"
        assert "text_first_delta" in result.timings_ms
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_stop_speech_keeps_visible_stream_and_complete_history(tmp_path):
    async def run():
        first_audio, continue_reply = asyncio.Event(), asyncio.Event()

        class SlowDialogue(Dialogue):
            async def stream_reply(self, **kwargs):
                self.calls += 1
                yield "She waited. "
                await continue_reply.wait()
                yield "Then she left."

        work, provider = await make_work(tmp_path / "db", SlowDialogue())
        audio, deltas = [], []

        async def consume(segment):
            audio.append(segment)
            first_audio.set()

        voice = VoiceSessionCoordinator(work, stt=Speech(), tts=Speech(),
                                        on_audio=consume, on_text_delta=deltas.append)
        pending = asyncio.create_task(voice.submit_text("Why?", request_id="stop"))
        await asyncio.wait_for(first_audio.wait(), 2)
        turn_id = work.session.messages[-1].metadata["turn_id"]
        await voice.stop_speech(turn_id)
        assert not pending.done()
        continue_reply.set()
        result = await pending
        assert result.speech_status == "stopped" and result.text_status == "completed"
        assert len(audio) == 1 and "Then she left." in "".join(deltas)
        assert work.session.messages[-1].content == "She waited. Then she left."
        assert provider.calls == 1
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_failed_reply_keeps_confirmation_and_retries_after_restart(tmp_path):
    async def run():
        path = tmp_path / "db"
        work, provider = await make_work(path)
        speech = Speech()
        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech)
        provider.fail = True
        result = await voice.submit_text("She waited.", request_id="one")
        assert result.text_status == "failed"
        user_id = work.session.messages[-1].id
        assert work.session.messages[-1].role is MessageRole.USER
        assert work.get_turn(result.turn_id).state == "failed"
        await voice.aclose()
        await work.aclose()
        replacement = Dialogue()
        restored = LearningWorkbench(replacement, event_store=SQLiteStore(path))
        resumed = VoiceSessionCoordinator(restored, stt=speech, tts=speech)
        retried = await resumed.retry_reply(result.turn_id)
        assert retried.text_status == "completed"
        assert restored.session.messages[-2].id == user_id
        assert sum(m.id == user_id for m in restored.session.messages) == 1
        await resumed.retry_speech(result.turn_id)
        assert replacement.calls == 1
        await resumed.aclose()
        await restored.aclose()

    asyncio.run(run())


def test_transcription_is_single_flight_and_close_cancels_it(tmp_path):
    async def run():
        entered = asyncio.Event()

        class Slow(Speech):
            async def transcribe(self, audio):
                entered.set()
                await asyncio.Event().wait()

        work, provider = await make_work(tmp_path / "db")
        speech = Slow()
        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech)
        before = [m.id for m in work.session.messages]
        task = asyncio.create_task(voice.recognize(wav_bytes()))
        await entered.wait()
        with pytest.raises(RuntimeError, match="conversation_busy"):
            await voice.recognize(wav_bytes())
        with pytest.raises(RuntimeError, match="conversation_busy"):
            await work.send_message("concurrent")
        with pytest.raises(RuntimeError, match="conversation_busy"):
            work.reset()
        await voice.aclose()
        assert task.cancelled() and work._operation_owner is None
        assert [m.id for m in work.session.messages] == before and provider.calls == 0
        await work.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["tts", "consumer"])
def test_speech_failure_does_not_abort_or_regenerate_dialogue(tmp_path, failure):
    async def run():
        work, provider = await make_work(tmp_path / "db")

        class Failing(Speech):
            async def synthesize(self, text):
                if failure == "tts":
                    raise RuntimeError("tts_down")
                return await super().synthesize(text)

        async def consumer(segment):
            raise RuntimeError("sink_down")

        speech = Failing()
        voice = VoiceSessionCoordinator(
            work, stt=speech, tts=speech, on_audio=consumer if failure == "consumer" else None
        )
        result = await voice.submit_text("Why?", request_id="failure")
        assert result.text_status == "completed" and result.speech_status == "failed"
        assert work.session.messages[-1].role is MessageRole.ASSISTANT
        assert work.get_turn(result.turn_id).state == "completed" and provider.calls == 1
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_first_sentence_is_synthesized_before_full_llm_reply(tmp_path):
    async def run():
        first_audio = asyncio.Event()

        class Streaming(Dialogue):
            async def stream_reply(self, **kwargs):
                yield "First sentence. "
                await asyncio.wait_for(first_audio.wait(), 1)
                yield "Second sentence."

        work, _ = await make_work(tmp_path / "db", Streaming())
        speech = Speech()

        async def consume(segment):
            first_audio.set()

        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech, on_audio=consume)
        result = await voice.submit_text("Hello", request_id="early")
        assert result.text_status == "completed" and result.segment_count == 2
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_close_cancels_inflight_reply_and_releases_operation(tmp_path):
    async def run():
        entered = asyncio.Event()

        class Slow(Dialogue):
            async def stream_reply(self, **kwargs):
                entered.set()
                await asyncio.Event().wait()
                yield "unreachable"

        work, _ = await make_work(tmp_path / "db", Slow())
        speech = Speech()
        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech)
        task = asyncio.create_task(voice.submit_text("Hello", request_id="closing"))
        await entered.wait()
        with pytest.raises(RuntimeError):
            await work.send_message("concurrent")
        with pytest.raises(RuntimeError):
            work.reset()
        with pytest.raises(RuntimeError):
            await work.complete_session()
        await voice.aclose()
        assert task.cancelled() and not work._sending and work._operation_owner is None
        assert work._turns.find_turn(work.session.id, "closing").state == "failed"
        await work.aclose()

    asyncio.run(run())


def test_sentence_boundaries_preserve_abbreviations_decimals_and_trailing_text():
    buffer = SpeechTextBuffer()
    buffer.append("Dr. Smith paid 3.")
    assert buffer.pop_sentence() is None
    buffer.append("14. Really?はい。Tail")
    assert buffer.pop_sentence() == "Dr. Smith paid 3.14."
    assert buffer.pop_sentence() == " Really?"
    assert buffer.pop_sentence() == "はい。"
    assert buffer.pop_sentence() is None
    buffer.done = True
    assert buffer.pop_sentence() == "Tail"


@pytest.mark.parametrize("audio", [b"not WAV", wav_bytes(24000), wav_bytes()[:-2]])
def test_invalid_audio_is_rejected_before_models_or_confirmation(tmp_path, audio):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        speech = Speech()

        async def unexpected(audio):
            raise AssertionError("The invalid input must not reach STT")

        speech.transcribe = unexpected
        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech)
        before = [m.id for m in work.session.messages]
        with pytest.raises(ValueError):
            await voice.recognize(audio)
        assert [m.id for m in work.session.messages] == before and provider.calls == 0
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_speech_backlog_limit_preserves_complete_text(tmp_path):
    async def run():
        class LongReply(Dialogue):
            async def stream_reply(self, **kwargs):
                self.calls += 1
                yield "x" * 4100

        work, provider = await make_work(tmp_path / "db", LongReply())
        speech = Speech()
        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech)
        result = await voice.submit_text("Tell me more", request_id="backlog")
        assert result.text_status == "completed" and result.speech_status == "failed"
        assert result.error_code == "speech_text_buffer_full"
        assert result.assistant_message.content == "x" * 4100
        assert work.session.messages[-1].id == result.assistant_message.id
        assert provider.calls == 1 and not speech.texts
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_voice_uses_configured_dialogue_role_and_never_speaks_reasoning(tmp_path):
    async def run():
        from langchain_core.messages import AIMessageChunk
        from pydantic import SecretStr
        from shinar.providers.openai_compatible import (
            OpenAICompatibleLLMProvider,
            OpenAICompatibleLLMSettings,
        )

        path = tmp_path / "db"
        seeded, _ = await make_work(path)
        await seeded.aclose()
        calls = []

        class Reasoning:
            async def ainvoke(self, *args, **kwargs):
                calls.append("reasoning")
                await asyncio.Event().wait()

        class ConfiguredDialogue:
            async def astream(self, *args, **kwargs):
                calls.append("dialogue")
                yield AIMessageChunk(
                    content="Only the visible reply. ",
                    additional_kwargs={"reasoning_content": "PRIVATE REASONING"},
                    usage_metadata={"input_tokens": 10, "output_tokens": 6, "total_tokens": 16},
                )

        provider = OpenAICompatibleLLMProvider(
            OpenAICompatibleLLMSettings(
                api_key=SecretStr("fake"),
                base_url="https://example.test/v1",
                reasoning_model="user-thinker",
                dialogue_model="user-chat",
            ),
            reasoning_client=Reasoning(),
            dialogue_client=ConfiguredDialogue(),
        )
        work = LearningWorkbench(provider, event_store=SQLiteStore(path))
        speech = Speech()
        voice = VoiceSessionCoordinator(work, stt=speech, tts=speech)
        draft = await voice.recognize(wav_bytes())
        assert not calls
        result = await voice.submit_confirmed(draft)
        assert calls[0] == "dialogue" and calls.count("dialogue") == 1
        assert result.assistant_message.content == "Only the visible reply."
        assert "PRIVATE" not in " ".join(speech.texts)
        await voice.retry_speech(result.turn_id)
        assert calls.count("dialogue") == 1
        records = work._event_store.list_model_calls()
        assert len([r for r in records if r["workload"] == "dialogue"]) == 1
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())
