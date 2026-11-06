import asyncio

from lingualoop.application.continuous_voice import ContinuousConversation
from lingualoop.application.voice_session import VoiceSessionCoordinator
from lingualoop.core.domain import MessageRole
from test_voice_session import make_work, Speech, wav_bytes


class AudioProcess:
    id = "audio-session"

    def __init__(self):
        self.calls = []
        self.accept = True

    async def request(self, kind, *args, **kwargs):
        self.calls.append(kind)
        return {"accepted": self.accept}


def test_cancel_transaction_wins_over_late_reply_and_keeps_confirmed_user(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        turn = work.confirm_user_input("No, she left.", request_id="one")
        claimed = work._turns.claim_turn(turn.id)
        work.interrupt_reply(turn.id, "user_interruption")
        assert work.get_turn(turn.id).state == "cancelled"
        work._turns.fail_turn(claimed, "late_failure")
        assert work.get_turn(turn.id).state == "cancelled"
        try:
            work._turns.finish_turn(claimed, work.session, [])
        except RuntimeError as error:
            assert str(error) == "conversation_attempt_expired"
        else:
            raise AssertionError("cancelled reply was persisted")
        assert work.session.messages[-1].content == "No, she left."
        assert work.session.messages[-1].metadata["reply_interrupted"]
        await work.send_message("I mean Ren.")
        assert work.session.messages[-2].metadata["previous_reply_interrupted"]
        assert provider.calls == 1
        await work.aclose()

    asyncio.run(run())


def test_interrupt_coordinator_cancels_llm_but_stop_speech_does_not(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        entered = asyncio.Event()

        async def stream(**kwargs):
            yield "A prefix. "
            entered.set()
            await asyncio.Event().wait()

        provider.stream_reply = stream
        voice = VoiceSessionCoordinator(work, stt=Speech(), tts=Speech())
        task = asyncio.create_task(voice.submit_text("No.", request_id="one"))
        await entered.wait()
        turn = work.session.messages[-1].metadata["turn_id"]
        await voice.stop_speech(turn)
        assert not task.done()
        await voice.interrupt_reply(turn)
        assert task.cancelled()
        assert work.get_turn(turn).state == "cancelled"
        assert work.session.messages[-1].role == MessageRole.USER
        await voice.aclose()
        await work.aclose()

    asyncio.run(run())


def test_continuous_three_turns_and_speech_retry_never_resends_user(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        audio, events = AudioProcess(), []
        runner = ContinuousConversation(work, audio, lambda *event: events.append(event))
        for i in range(3):
            await runner.input_started(str(i), 1)
            await runner.receive(
                {"utterance": str(i), "revision": 1}, wav_bytes(), None, Speech(), Speech(), True
            )
        assert provider.calls == 3
        assert len([m for m in work.session.messages if m.role == MessageRole.USER]) == 3
        assert audio.calls.count("claim") == 3 and audio.calls.count("output_begin") == 3
        turn = runner.turn_id
        await runner.send_text(
            "", None, Speech(), Speech(), True, retry_turn=turn, speech_only=True
        )
        assert provider.calls == 3
        await runner.close()
        await work.aclose()

    asyncio.run(run())


def test_stale_recognition_and_rejected_claim_never_call_dialogue(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        audio = AudioProcess()
        runner = ContinuousConversation(work, audio, lambda *event: None)
        await runner.input_started("one", 2)
        await runner.receive(
            {"utterance": "one", "revision": 1}, wav_bytes(), None, Speech(), Speech(), False
        )
        audio.accept = False
        await runner.receive(
            {"utterance": "one", "revision": 2}, wav_bytes(), None, Speech(), Speech(), False
        )
        assert provider.calls == 0 and len(work.session.messages) == 1
        await runner.close()
        await work.aclose()

    asyncio.run(run())


def test_continuation_cancels_stt_without_a_user_message(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        audio, entered = AudioProcess(), asyncio.Event()
        speech = Speech()

        async def slow(audio):
            entered.set()
            await asyncio.Event().wait()

        speech.transcribe = slow
        runner = ContinuousConversation(work, audio, lambda *event: None)
        await runner.input_started("one", 1)
        task = asyncio.create_task(
            runner.receive(
                {"utterance": "one", "revision": 1}, wav_bytes(), None, speech, Speech(), False
            )
        )
        await entered.wait()
        await runner.input_started("one", 2)
        assert task.cancelled() and provider.calls == 0 and len(work.session.messages) == 1
        await runner.receive(
            {"utterance": "one", "revision": 2}, wav_bytes(), None, Speech(), Speech(), False
        )
        assert provider.calls == 1
        await runner.close()
        await work.aclose()

    asyncio.run(run())


def test_new_final_waits_for_slow_cancelled_stt_cleanup(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        speech, entered = Speech(), asyncio.Event()

        async def slow(audio):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.1)  # A resident model process needs time to exit.
                raise

        speech.transcribe = slow
        events = []
        runner = ContinuousConversation(work, AudioProcess(), lambda *e: events.append(e))
        await runner.input_started("one", 1)
        old = asyncio.create_task(
            runner.receive(
                {"utterance": "one", "revision": 1}, wav_bytes(), None, speech, Speech(), False
            )
        )
        await entered.wait()
        cleanup = asyncio.create_task(runner.input_started("one", 2))
        await asyncio.sleep(0)
        await runner.receive(
            {"utterance": "one", "revision": 2}, wav_bytes(), None, Speech(), Speech(), False
        )
        await cleanup
        assert old.cancelled() and provider.calls == 1
        assert not any(kind == "recognition_failed" for kind, *_ in events)
        await runner.close()
        await work.aclose()

    asyncio.run(run())


def test_old_coordinator_cannot_cancel_a_new_retry_of_the_same_turn(tmp_path):
    async def run():
        work, provider = await make_work(tmp_path / "db")
        entered = asyncio.Event()

        async def stream(**kwargs):
            entered.set()
            yield "A prefix. "
            await asyncio.Event().wait()

        provider.stream_reply = stream
        first = VoiceSessionCoordinator(work, stt=Speech(), tts=Speech())
        old = asyncio.create_task(first.submit_text("No.", request_id="one", speak=False))
        await entered.wait()
        turn_id = work.session.messages[-1].metadata["turn_id"]
        await first.interrupt_reply(turn_id)
        entered.clear()
        second = VoiceSessionCoordinator(work, stt=Speech(), tts=Speech())
        retry = asyncio.create_task(second.retry_reply(turn_id, speak=False))
        await entered.wait()
        await first.interrupt_reply(turn_id)
        assert not retry.done() and work.get_turn(turn_id).state == "generating"
        await second.interrupt_reply(turn_id)
        assert old.cancelled() and retry.cancelled()
        assert sum(m.role == MessageRole.USER for m in work.session.messages) == 1
        await first.aclose()
        await second.aclose()
        await work.aclose()

    asyncio.run(run())


def test_speech_delivery_notice_persists_separately_from_complete_text(tmp_path):
    async def run():
        work, _ = await make_work(tmp_path / "db")
        result = await work.send_message("I think so.")
        turn = work.get_turn(result.turn_id)
        work.record_speech_delivery(turn.id, "interrupted")
        assert work.get_turn(turn.id).state == "completed"
        user = work.session.messages[-2]
        assert user.metadata["speech_interrupted"] and not user.metadata.get("reply_interrupted")
        assert (
            work._event_store.get_session(work.session.id)
            .messages[-2]
            .metadata["speech_interrupted"]
        )
        work.record_speech_delivery(turn.id, "completed", 1)
        assert not work.session.messages[-2].metadata.get("speech_interrupted")
        assert work.get_turn(turn.id).last_played_segment == 1
        await work.aclose()

    asyncio.run(run())
