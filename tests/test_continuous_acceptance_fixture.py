"""The human-device harness must identify each reply without pretending to be an LLM."""

import asyncio
from pathlib import Path
from types import SimpleNamespace


def test_human_fixture_has_distinct_numbered_replies_and_one_call_per_input(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from validate_continuous_desktop import SlowDialogue

    async def run():
        for language in ("zh", "en", "ja"):
            provider = SlowDialogue(language, human=True)
            provider.reply_delay = 0
            replies, samples = [], []
            for number in range(1, 21):
                user = SimpleNamespace(id=f"user-{number}", content="An actual recognized answer.")
                chunks = [chunk async for chunk in provider.stream_reply(user_message=user)]
                assert len(chunks) == 2 and str(number) in chunks[0]
                assert user.content not in "".join(chunks)
                assert provider.calls == number
                assert provider.responses[-1] == {"number": number, "user_message_id": user.id}
                replies.append("".join(chunks))
                samples.append(chunks[-1])
            assert len(set(replies)) == 20
            assert len(set(samples[:6])) == 6

    asyncio.run(run())
