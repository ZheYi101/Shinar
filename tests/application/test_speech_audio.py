import asyncio
from dataclasses import replace
import io
import struct
import wave

import pytest

from shinar.application.speech_audio import SpeechPlayoutBuffer, trim_speech_padding
from shinar.application.speech_text import SpeechTextBuffer
from shinar.application.voice_session import VoiceSessionCoordinator
from shinar.core.voice import SpeechSegment
from tests.application.test_voice_session import Speech, Dialogue, make_work, wav_bytes


def test_next_audio_is_synthesized_while_previous_segment_is_being_sent(tmp_path):
    async def run():
        sending, next_ready, finish_send = asyncio.Event(), asyncio.Event(), asyncio.Event()
        order, prepared, all_text = [], [], asyncio.Event()

        class Streaming(Dialogue):
            async def stream_reply(self, **kwargs):
                self.calls += 1
                yield "First sentence. "
                await sending.wait()
                yield "Second sentence."
                all_text.set()

        class LookaheadSpeech(Speech):
            async def synthesize(self, text):
                prepared.append(text)
                if len(prepared) == 2:
                    assert sending.is_set() and not finish_send.is_set()
                    next_ready.set()
                return wav_bytes(24000)

        async def consume(segment):
            order.append(segment.index)
            if segment.index == 0:
                sending.set()
                # Before the fix, synthesis waited for this transport to return.
                await asyncio.wait_for(next_ready.wait(), 1)
                assert all_text.is_set()
                await finish_send.wait()

        work, provider = await make_work(tmp_path / "db", Streaming())
        voice = VoiceSessionCoordinator(work, stt=Speech(), tts=LookaheadSpeech(), on_audio=consume)
        task = asyncio.create_task(voice.submit_text("Hello", request_id="overlap"))
        await asyncio.wait_for(next_ready.wait(), 1)
        finish_send.set()
        result = await task
        assert result.speech_status == "completed" and order == [0, 1]
        assert result.segment_count == 2 and provider.calls == 1
        await voice.aclose()
        assert not any(t.get_name().startswith("tts-ahead-") for t in asyncio.all_tasks())
        await work.aclose()

    asyncio.run(run())


def test_playout_budget_includes_the_segment_owned_by_the_transport():
    async def run():
        segment = SpeechSegment.from_wav("turn", 0, "First.", wav_bytes())
        queue = SpeechPlayoutBuffer(segments=2, byte_limit=len(segment.audio) * 2)
        await queue.put(segment)
        playing = await queue.get()
        await queue.put(replace(segment, index=1))
        blocked = asyncio.create_task(queue.put(replace(segment, index=2)))
        await asyncio.sleep(0)
        assert not blocked.done()
        await queue.release(playing)
        await asyncio.wait_for(blocked, 1)
        assert (await queue.get()).index == 1
        assert (await queue.get()).index == 2
        await queue.finish()
        assert await queue.get() is None

    asyncio.run(run())


def test_speech_stop_cancels_lookahead_and_keeps_dialogue(tmp_path):
    async def run():
        first, building_second, continue_text = asyncio.Event(), asyncio.Event(), asyncio.Event()
        cancelled, audio = [], []

        class Streaming(Dialogue):
            async def stream_reply(self, **kwargs):
                yield "One. "
                await first.wait()
                yield "Two. "
                await continue_text.wait()
                yield "Complete visible text."

        class Slow(Speech):
            async def synthesize(self, text):
                if "Two" in text:
                    building_second.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.append(True)
                return wav_bytes()

        async def consume(segment):
            audio.append(segment)
            first.set()
            await asyncio.Event().wait()

        work, _ = await make_work(tmp_path / "db", Streaming())
        voice = VoiceSessionCoordinator(work, stt=Speech(), tts=Slow(), on_audio=consume)
        task = asyncio.create_task(voice.submit_text("Hi", request_id="stop-ahead"))
        await asyncio.wait_for(building_second.wait(), 1)
        turn = work.session.messages[-1].metadata["turn_id"]
        await voice.stop_speech(turn)
        continue_text.set()
        result = await task
        assert result.text_status == "completed" and result.speech_status == "stopped"
        assert cancelled and len(audio) == 1
        assert result.assistant_message.content.endswith("Complete visible text.")
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("rate,channels", [(16000, 1), (24000, 1), (44100, 2), (48000, 1)])
def test_padding_trim_preserves_low_level_consonants_internal_pauses_and_format(rate, channels):
    # Even a very quiet consonant above the digital-silence threshold is preserved.
    speech = struct.pack("<h", 12) * channels * (rate // 10)
    inside = b"\0\0" * channels * (rate // 3)
    content = speech + inside + speech
    padding = b"\0\0" * channels * (rate // 4)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(channels)
        wav.setframerate(rate)
        wav.setsampwidth(2)
        wav.writeframes(padding + content + padding)
    original = SpeechSegment.from_wav("turn", 2, "Speak.", stream.getvalue(), "credit")
    trimmed, ms = trim_speech_padding(original)
    assert ms == pytest.approx(400, abs=0.1)
    with wave.open(io.BytesIO(trimmed.audio)) as wav:
        assert wav.getframerate() == rate and wav.getnchannels() == channels
        pcm = wav.readframes(wav.getnframes())
    assert pcm == b"\0\0" * channels * (rate * 20 // 1000) + content + b"\0\0" * channels * (rate * 80 // 1000)
    assert trimmed.index == 2 and trimmed.attribution == "credit"


def test_chunk_coalescing_keeps_first_audio_fast_and_never_steals_partial_text():
    buffer = SpeechTextBuffer()
    buffer.append("First. Dr. Smith paid 3.14. Really?はい。 A partial")
    assert buffer.pop_chunk() == "First."
    assert buffer.pop_chunk(combine=True) == " Dr. Smith paid 3.14. Really?はい。"
    assert buffer.text == " A partial" and buffer.pop_chunk(combine=True) is None
    buffer.done = True
    assert buffer.pop_chunk(combine=True) == " A partial"


def test_chunk_limit_restores_the_next_whole_sentence():
    buffer = SpeechTextBuffer()
    buffer.append("One. Two long words. Three.")
    assert buffer.pop_chunk(combine=True, limit=9) == "One."
    assert buffer.pop_chunk() == " Two long words."


def test_long_all_silent_audio_is_not_relabelled_or_shortened():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setframerate(24000)
        wav.setsampwidth(2)
        wav.writeframes(b"\0\0" * 24000 * 3)
    original = SpeechSegment.from_wav("silent", 0, "Test.", stream.getvalue())
    result, removed = trim_speech_padding(original)
    assert result is original and removed == 0
