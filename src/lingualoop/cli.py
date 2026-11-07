from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Sequence

from dotenv import load_dotenv

from lingualoop.application import LearningWorkbench
from lingualoop.core.domain import LanguageEnum, MaterialTrack, ProficiencyLevel, ReviewRating
from lingualoop.core.ports import LearningLLMProvider
from lingualoop.infrastructure.material_import import import_material_file
from lingualoop.infrastructure.blocking_jobs import BlockingRequest, run_blocking
from lingualoop.core.reading_scope import paragraph_boundary
from lingualoop.providers import MockLearningLLMProvider, OpenAICompatibleLLMProvider


@dataclass
class CommandOutcome:
    lines: list[str]
    should_exit: bool = False


class ConsoleSessionApp:
    def __init__(
        self,
        workbench: LearningWorkbench,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._workbench = workbench
        self._input = input_fn
        self._output = output_fn or _safe_print

    async def run(self) -> int:
        self._output("LinguaLoop CLI")
        self._output("Type 'help' for commands.")
        while True:
            try:
                raw = self._input("lingualoop> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._output("")
                return 0
            if not raw:
                continue

            result = await self.handle_line(raw)
            for line in result.lines:
                self._output(line)
            if result.should_exit:
                return 0

    async def handle_line(self, raw: str) -> CommandOutcome:
        try:
            command, args = _split_command(raw)
            if command in {"quit", "exit"}:
                return CommandOutcome(["Bye."], should_exit=True)
            if command == "help":
                return CommandOutcome(_help_lines())
            if command == "load":
                return CommandOutcome(await self._load_material())
            if command == "import":
                return CommandOutcome(await self._import_material(args))
            if command == "start":
                return CommandOutcome(await self._start_session())
            if command == "scope":
                return CommandOutcome(self._confirm_scope(args))
            if command == "say":
                text = args or self._input("Message: ").strip()
                return CommandOutcome(await self._say(text))
            if command == "finish":
                return CommandOutcome(await self._finish())
            if command == "review":
                review_args = args.strip().lower()
                if review_args in {"", "--due"}:
                    return CommandOutcome(self._workbench.review_lines(due_only=True))
                if review_args in {"--all", "all"}:
                    return CommandOutcome(self._workbench.review_lines(due_only=False))
                return CommandOutcome(["Usage: review [--all]"])
            if command == "rate":
                return CommandOutcome(await self._rate(args))
            if command == "summary":
                return CommandOutcome(
                    [*self._workbench.overview_lines(), *self._workbench.session_lines()]
                )
            if command == "export":
                path_text = args or self._input("Export path [lingualoop-session.json]: ")
                path = Path(path_text.strip() or "lingualoop-session.json")
                exported = await self._workbench.export_json(path)
                return CommandOutcome([f"Exported to {exported}"])
            if command == "reset":
                self._workbench.reset()
                return CommandOutcome(["State reset."])

            if self._workbench.session is not None:
                return CommandOutcome(await self._say(raw))

            return CommandOutcome([f"Unknown command: {command}", "Type 'help' for commands."])
        except Exception as exc:
            return CommandOutcome([f"Error: {exc}"])

    async def _load_material(self) -> list[str]:
        title = self._prompt("Title: ")
        source_language = _prompt_enum(
            self._input,
            self._output,
            "Source language (e.g. english, chinese): ",
            LanguageEnum,
        )
        target_language = _prompt_enum(
            self._input,
            self._output,
            "Target language (e.g. english, chinese): ",
            LanguageEnum,
        )
        native_language = _prompt_enum(
            self._input,
            self._output,
            "Native language (e.g. chinese, english): ",
            LanguageEnum,
        )
        learner_level = _prompt_enum(
            self._input,
            self._output,
            "Learner level (A1/A2/B1/B2/C1/C2/unknown): ",
            ProficiencyLevel,
        )
        self._output("Paste material text. Finish with a single '.' line.")
        content = _read_multiline(self._input)

        material = await self._workbench.load_material(
            title=title,
            source_language=source_language,
            target_language=target_language,
            native_language=native_language,
            learner_level=learner_level,
            content=content,
            auto_prepare=False,
        )
        scope_lines = self._confirm_scope()

        lines = [
            f"Loaded: {material.title}",
            *scope_lines,
            *self._workbench.overview_lines(),
            "Type 'start' to open the practice session.",
        ]
        return lines

    async def _import_material(self, path_text: str) -> list[str]:
        path = Path(path_text.strip() or self._input("File path: ").strip())
        imported = await run_blocking(BlockingRequest("import", (path,)))
        self._output("Normalized preview:")
        for line in _preview_lines(imported.normalized_content):
            self._output(line)
        self._output("Raw content is preserved separately.")

        title = self._input(f"Title [{imported.title}]: ").strip() or imported.title
        track = _prompt_enum(
            self._input,
            self._output,
            "Track (article_reading/live_chat) [article_reading]: ",
            MaterialTrack,
            default=MaterialTrack.ARTICLE_READING,
        )
        source_language = _prompt_enum(
            self._input,
            self._output,
            "Source language (e.g. english, chinese): ",
            LanguageEnum,
        )
        target_language = _prompt_enum(
            self._input,
            self._output,
            "Target language (e.g. english, chinese): ",
            LanguageEnum,
        )
        native_language = _prompt_enum(
            self._input,
            self._output,
            "Native language (e.g. chinese, english): ",
            LanguageEnum,
        )
        learner_level = _prompt_enum(
            self._input,
            self._output,
            "Learner level (A1/A2/B1/B2/C1/C2/unknown): ",
            ProficiencyLevel,
        )
        material = await self._workbench.load_imported_material(
            imported,
            title=title,
            source_language=source_language,
            target_language=target_language,
            native_language=native_language,
            learner_level=learner_level,
            track=track,
            auto_prepare=False,
        )
        scope_lines = self._confirm_scope()
        return [
            f"Imported: {material.title}",
            *scope_lines,
            f"Track: {material.track.value}",
            *imported.diagnostics,
            *self._workbench.overview_lines(),
            "Type 'start' to open the practice session.",
        ]

    def _confirm_scope(self, value: str | None = None) -> list[str]:
        material = self._workbench.material
        if material is None:
            raise ValueError("Load a material before confirming its reading scope.")
        value = self._input("Read percentage 1–100 [unconfirmed]: ").strip() if value is None else value.strip()
        if not value:
            return ["Reading scope unconfirmed. Use 'scope <1–100>' before starting."]
        percent = float(value)
        if not (1 <= percent <= 100 and percent.is_integer()):
            raise ValueError("Read percentage must be an integer between 1 and 100.")
        end = paragraph_boundary(material.content, int(percent))
        self._workbench.set_reading_scope(end)
        return [f"Reading scope confirmed: {percent:g}%."]

    async def _start_session(self) -> list[str]:
        result = await self._workbench.start_session()
        lines = ["Session started."]
        if result.assistant_message is not None:
            lines.append(f"Task: {result.assistant_message.content}")
        lines.extend(self._workbench.session_lines())
        return lines

    async def _say(self, user_text: str) -> list[str]:
        result = await self._workbench.send_message(user_text)
        lines = []
        if result.assistant_message is not None:
            lines.append(f"Assistant: {result.assistant_message.content}")
        if result.feedback_items:
            lines.append(f"Feedback items: {len(result.feedback_items)}")
            for item in result.feedback_items:
                lines.append(f"- {item.original} -> {item.corrected}")
        return lines or ["No response."]

    async def _finish(self) -> list[str]:
        result = await self._workbench.complete_session()
        review = result.session.review
        lines = ["Session completed."]
        if review is not None:
            lines.append(f"Summary: {review.summary}")
            if review.focus_areas:
                lines.append("Focus: " + "; ".join(review.focus_areas[:3]))
            if review.next_action:
                lines.append(f"Next: {review.next_action}")
        if result.review_items:
            lines.append(f"Review items: {len(result.review_items)}")
            for item in result.review_items[:3]:
                lines.append(f"- {item.prompt}")
        return lines

    async def _rate(self, args: str) -> list[str]:
        parts = args.split(maxsplit=2)
        if len(parts) < 2:
            return ["Usage: rate <review_id_or_number> <again|hard|good|easy> [answer]"]
        items = self._workbench.review_queue
        key = parts[0]
        item = items[int(key) - 1] if key.isdigit() and 0 < int(key) <= len(items) else next(
            (candidate for candidate in items if candidate.id == key),
            None,
        )
        if item is None:
            return [f"Review item not found: {key}"]
        rating = ReviewRating(parts[1].lower())
        answer = parts[2] if len(parts) == 3 else None
        outcome = await self._workbench.record_review_outcome(item.id, rating, answer)
        return [f"Recorded {outcome.rating.value}; next due at {outcome.next_due_at}."]

    def _prompt(self, message: str) -> str:
        return self._input(message).strip()


def _help_lines() -> list[str]:
    return [
        "Commands:",
        "  load    Save one material and confirm the reading scope",
        "  import  Import .md/.markdown/.docx material",
        "  start   Start the practice session",
        "  scope   Confirm the read percentage (1–100)",
        "  say     Send a learner message",
        "  finish  Complete the session and create review items",
        "  review  Show due review items",
        "  review --all  Show all active review items",
        "  rate    Record review outcome",
        "  summary Show material/session summary",
        "  export  Save session JSON",
        "  reset   Clear current state",
        "  quit    Exit the CLI",
    ]


def _split_command(raw: str) -> tuple[str, str]:
    parts = raw.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return command, args


def _prompt_enum(
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    prompt: str,
    enum_cls: type[StrEnum],
    *,
    default: StrEnum | None = None,
) -> StrEnum:
    while True:
        raw = input_fn(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            return _parse_enum(raw, enum_cls)
        except ValueError as exc:
            output_fn(f"Invalid value: {exc}")


def _parse_enum(
    raw: str, enum_cls: type[StrEnum]
) -> StrEnum:
    candidate = raw.strip().lower()
    if not candidate:
        raise ValueError("value must not be blank")
    for member in enum_cls:
        if candidate in {member.name.lower(), str(member.value).lower()}:
            return member
    raise ValueError(f"expected one of {[member.value for member in enum_cls]}")


def _read_multiline(input_fn: Callable[[str], str]) -> str:
    lines: list[str] = []
    while True:
        line = input_fn("").rstrip("\n")
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _preview_lines(text: str, *, max_lines: int = 8, max_chars: int = 800) -> list[str]:
    preview = text.strip()[:max_chars]
    lines = preview.splitlines()[:max_lines]
    if len(text.strip()) > len(preview) or len(text.strip().splitlines()) > max_lines:
        lines.append("...")
    return [f"  {line}" if line else "" for line in lines] or ["  (empty)"]


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            continue


def _safe_print(text: str, *, file=None) -> None:
    stream = file or sys.stdout
    try:
        print(text, file=stream)
        return
    except UnicodeEncodeError:
        pass

    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
            print(text, file=stream)
            return
        except (AttributeError, UnicodeEncodeError, ValueError, OSError):
            pass

    encoding = getattr(stream, "encoding", None) or sys.getdefaultencoding()
    safe_text = str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_text, file=stream)


def build_provider(use_mock: bool) -> LearningLLMProvider:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    if use_mock:
        return MockLearningLLMProvider()
    return OpenAICompatibleLLMProvider.from_env()


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console_encoding()
    parser = argparse.ArgumentParser(description="LinguaLoop CLI")
    parser.add_argument("--mock", action="store_true", help="Use the deterministic mock provider")
    args = parser.parse_args(argv)

    try:
        provider = build_provider(args.mock)
    except Exception as exc:
        _safe_print(f"Error: {exc}", file=sys.stderr)
        return 2
    app = ConsoleSessionApp(LearningWorkbench(provider))
    return asyncio.run(app.run())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
