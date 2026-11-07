from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from lingualoop.application import LearningWorkbench
from lingualoop.cli import ConsoleSessionApp, _safe_print, build_provider
from lingualoop.core import (
    LanguageEnum,
    MaterialTrack,
    ProficiencyLevel,
    ReviewItem,
    ReviewRating,
    ReviewStatus,
)
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers import MockLearningLLMProvider


def test_workbench_load_start_send_and_export(tmp_path) -> None:
    async def run_case() -> None:
        db_path = tmp_path / "lingualoop.sqlite3"
        workbench = LearningWorkbench(
            MockLearningLLMProvider(),
            event_store=SQLiteStore(db_path),
        )

        material = await workbench.load_material(
            title="Market trip",
            source_language=LanguageEnum.ENGLISH,
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.A2,
            content="Yesterday I went to the market and bought apples.",
        )

        assert material.analysis is not None
        assert material.analysis.summary
        assert workbench.profile is not None
        assert workbench.profile.target_language is LanguageEnum.ENGLISH

        started = await workbench.start_session()
        assert started.assistant_message is not None
        assert started.session.current_instruction is not None

        answered = await workbench.send_message("Yesterday I go market and buy apple.")
        assert answered.assistant_message is not None
        assert answered.feedback_items == []  # Default discussion defers feedback until closeout.
        assert answered.review_items == []
        assert workbench.review_queue == []

        completed = await workbench.complete_session()
        assert completed.session.review is not None
        assert completed.review_items
        assert workbench.review_queue
        assert any(line.startswith("Status: completed") for line in workbench.session_lines())
        assert any(line.startswith("Review summary:") for line in workbench.session_lines())
        assert "Current task:" not in workbench.session_lines()

        restored = LearningWorkbench(
            MockLearningLLMProvider(),
            event_store=SQLiteStore(db_path),
        )
        assert restored.materials[0].title == "Market trip"
        assert restored.session is not None
        assert restored.session.review is not None
        assert restored.review_queue[0].prompt == completed.review_items[0].prompt

        original_due_at = restored.review_queue[0].due_at
        with pytest.raises(ValueError, match="does not match"):
            await restored.record_review_outcome(
                restored.review_queue[0].id,
                ReviewRating.GOOD,
                "banana",
            )
        assert restored.review_queue[0].due_at == original_due_at

        outcome = await restored.record_review_outcome(
            restored.review_queue[0].id,
            ReviewRating.HARD,
            "banana",
        )
        assert outcome.next_due_at is not None
        assert restored.review_queue[0].status is ReviewStatus.ACTIVE

        accepted = await restored.record_review_outcome(
            restored.review_queue[0].id,
            ReviewRating.GOOD,
            restored.review_queue[0].answer,
        )
        assert accepted.next_due_at is not None

        exported = await workbench.export_json(tmp_path / "session.json")
        payload = json.loads(exported.read_text(encoding="utf-8"))

        assert payload["material"]["analysis"]["summary"]
        assert payload["session"]["messages"]
        assert payload["events"]
        assert payload["review_queue"]

        await restored.update_review_status(restored.review_queue[0].id, ReviewStatus.IGNORED)
        assert restored.review_queue == []

    asyncio.run(run_case())


def test_cli_command_flow(tmp_path) -> None:
    async def run_case() -> None:
        responses = iter(
            [
                "Market trip",
                "english",
                "english",
                "chinese",
                "A2",
                "Yesterday I went to the market and bought apples.",
                ".",
                "100",
                "Yesterday I go market and buy apple.",
                "I go market and buy apple.",
            ]
        )
        outputs: list[str] = []

        def fake_input(prompt: str) -> str:
            return next(responses)

        app = ConsoleSessionApp(
            LearningWorkbench(
                MockLearningLLMProvider(),
                event_store=SQLiteStore(tmp_path / "cli.sqlite3"),
            ),
            input_fn=fake_input,
            output_fn=outputs.append,
        )

        load = await app.handle_line("load")
        assert any(line.startswith("Loaded:") for line in load.lines)

        start = await app.handle_line("start")
        assert any("Session started." in line for line in start.lines)

        say = await app.handle_line("say")
        assert any(line.startswith("Assistant:") for line in say.lines)
        assert not any(line.startswith("Feedback items:") for line in say.lines)

        finish = await app.handle_line("finish")
        assert any(line.startswith("Session completed.") for line in finish.lines)
        assert any(line.startswith("Review items:") for line in finish.lines)

        review = await app.handle_line("review")
        assert review.lines[0].startswith("今日到期复习项")

        review_all = await app.handle_line("review --all")
        assert review_all.lines[0].startswith("全部复习项")

        exported_path = tmp_path / "cli-session.json"
        export = await app.handle_line(f"export {exported_path}")
        assert any("Exported to" in line for line in export.lines)
        assert exported_path.exists()

        summary = await app.handle_line("summary")
        assert any(line.startswith("Material:") for line in summary.lines)

        reset = await app.handle_line("reset")
        assert reset.lines == ["State reset."]

        quit_result = await app.handle_line("quit")
        assert quit_result.should_exit is True

    asyncio.run(run_case())


def test_review_lines_default_to_due_items_and_all_lists_queue(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "review.sqlite3")
    now = datetime.now(timezone.utc)
    store.save_review_item(
        ReviewItem(prompt="Due prompt", answer="went", due_at=now - timedelta(minutes=1))
    )
    store.save_review_item(
        ReviewItem(prompt="Later prompt", answer="bought", due_at=now + timedelta(days=2))
    )
    workbench = LearningWorkbench(MockLearningLLMProvider(), event_store=store)

    due_lines = workbench.review_lines()
    all_lines = workbench.review_lines(due_only=False)

    assert due_lines[0].startswith("今日到期复习项（1")
    assert "Due prompt" in "\n".join(due_lines)
    assert "Later prompt" not in "\n".join(due_lines)
    assert all_lines[0].startswith("全部复习项（2")
    assert "Later prompt" in "\n".join(all_lines)


def test_cli_import_supports_title_track_and_preview(tmp_path) -> None:
    async def run_case() -> None:
        path = tmp_path / "wind-story.md"
        path.write_text(
            "# Wind Story\n\nThe wind blew hard. The sun shone warmly.",
            encoding="utf-8",
        )
        responses = iter(["Custom Wind", "live_chat", "english", "english", "chinese", "A2", "100"])
        outputs: list[str] = []

        app = ConsoleSessionApp(
            LearningWorkbench(
                MockLearningLLMProvider(),
                event_store=SQLiteStore(tmp_path / "import.sqlite3"),
            ),
            input_fn=lambda _prompt: next(responses),
            output_fn=outputs.append,
        )

        imported = await app.handle_line(f"import {path}")

        assert "Normalized preview:" in outputs
        assert any("Wind Story" in line for line in outputs)
        assert "Raw content is preserved separately." in outputs
        assert "Imported: Custom Wind" in imported.lines
        assert "Track: live_chat" in imported.lines
        assert app._workbench.material is not None
        assert app._workbench.material.track is MaterialTrack.LIVE_CHAT

    asyncio.run(run_case())


def test_cli_build_provider_loads_cwd_dotenv(monkeypatch, tmp_path) -> None:
    for name in [
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_REASONING_MODEL",
        "OPENAI_DIALOGUE_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=dotenv-key\n"
        "OPENAI_BASE_URL=https://api.example.com\n"
        "OPENAI_REASONING_MODEL=reasoning-model\n",
        encoding="utf-8",
    )

    provider = build_provider(use_mock=False)

    assert provider._settings.api_key.get_secret_value() == "dotenv-key"


def test_safe_print_replaces_unencodable_characters() -> None:
    class StrictAsciiStream:
        encoding = "ascii"

        def __init__(self) -> None:
            self.values: list[str] = []

        def write(self, value: str) -> None:
            value.encode(self.encoding)
            self.values.append(value)

        def flush(self) -> None:
            return None

    stream = StrictAsciiStream()

    _safe_print("✅", file=stream)

    assert "?" in "".join(stream.values)
