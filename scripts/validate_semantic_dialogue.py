"""Export native histories and replay bounded source-context comparisons.

All learning data/results stay in an explicit local validation directory. Native B
replies are reused rather than paying to regenerate them. A/C replays do not add
messages to the application database. Gold evidence must be reviewed explicitly.
"""

# ruff: noqa: E402 -- this standalone tool bootstraps the checkout's src path.
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import random
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

from lingualoop.application import LearningWorkbench
from lingualoop.application.semantic_preparation import SemanticPreparation, analysis_with_knowledge
from lingualoop.core.domain import (
    LanguageEnum,
    LearningMaterial,
    Message,
    MessageRole,
    PracticeInstruction,
    ProficiencyLevel,
)
from lingualoop.core.knowledge import TurnEvidence
from lingualoop.core.knowledge_context import assemble_turn_context, digest
from lingualoop.infrastructure import SQLiteStore
from lingualoop.infrastructure.material_import import import_material_file
from lingualoop.providers import OpenAICompatibleLLMProvider
from benchmark_prepared_dialogue import AuditClient
from model_request_guard import ModelRequestGuard


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def cases_from_histories(store):
    result = []
    for session in sorted(store.list_sessions(), key=lambda item: item.created_at):
        if session.pattern_id != "free-discussion" or session.status.value != "completed":
            continue
        for index, message in enumerate(session.messages):
            if message.role is not MessageRole.USER:
                continue
            assistant = session.messages[index + 1]
            if assistant.role is not MessageRole.ASSISTANT:
                raise ValueError("Confirmed messages must alternate")
            # Earlier failed development replies remain exported, but are not
            # silently mixed into the corrected candidate's paired comparison.
            if (
                assistant.metadata.get("context", {}).get("prompt_version")
                != "semantic-dialogue-v2"
            ):
                continue
            result.append(
                {
                    "case_id": f"case-{len(result) + 1:02d}",
                    "session": session,
                    "index": index,
                    "user": message,
                    "assistant": assistant,
                }
            )
    return result


def export(store, output):
    sessions = store.list_sessions()
    data = []
    for session in sorted(sessions, key=lambda item: item.created_at):
        lines = [
            f"# Actual native conversation {session.id}",
            f"Read endpoint: {session.options.read_through if session.options else None}",
            "",
        ]
        for message in session.messages:
            lines.extend([f"## {message.role.value}", "", message.content, ""])
        if session.review:
            lines.extend(["## Review", "", session.review.summary, ""])
        path = output / f"{session.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        data.append(session.model_dump(mode="json"))
    dump(output / "actual-sessions.json", data)
    return len(cases_from_histories(store))


def draft_gold(store, output):
    rows = []
    for case in cases_from_histories(store):
        session = case["session"]
        material = store.get_material(session.material_id)
        provenance = case["assistant"].metadata.get("context", {})
        end = session.options.read_through
        service = SemanticPreparation(None, store)
        identity = material.analysis.knowledge.generation_identity
        knowledge = service.load_manifest(material, end, identity)
        if knowledge is None:
            raise ValueError("Scope manifest missing; finish actual preparation first")
        paragraphs = {span.id: (span, unit) for unit in knowledge.units for span in unit.paragraphs}
        candidates = []
        for identifier in provenance.get("evidence_ids", []):
            if identifier not in paragraphs:
                continue
            span, unit = paragraphs[identifier]
            candidates.append(
                {
                    "id": identifier,
                    "start_char": span.start_char,
                    "end_char": min(span.end_char, span.start_char + 4000),
                    "source_kind": unit.source_kind,
                    "text": material.content[
                        span.start_char : min(span.end_char, span.start_char + 4000)
                    ],
                }
            )
        rows.append(
            {
                "case_id": case["case_id"],
                "scope_end": end,
                "source_hash": material.source_hash,
                "question": case["user"].content,
                "reviewed_by": None,
                "evidence": candidates,
            }
        )
    dump(output / "gold-draft.json", rows)


async def compare(store, provider, output, gold_path):
    cases = cases_from_histories(store)
    if len(cases) != 12:
        raise ValueError("Expected exactly twelve completed native reader turns")
    gold = {row["case_id"]: row for row in json.loads(gold_path.read_text(encoding="utf-8"))}
    path = output / "comparison.json"
    results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    keys = {(row["case_id"], row["condition"]) for row in results}
    for case in cases:
        session = case["session"]
        material = store.get_material(session.material_id)
        end = session.options.read_through
        prefix = session.model_copy(
            update={
                "messages": session.messages[: case["index"]],
                "conversation_memory": None,
                "focus_reference": None,
            }
        )
        row = gold[case["case_id"]]
        if (
            not row.get("reviewed_by")
            or row["source_hash"] != material.source_hash
            or row["scope_end"] != end
        ):
            raise ValueError(
                "Gold evidence must be explicitly source-reviewed for the same reading scope"
            )
        evidence = [TurnEvidence.model_validate(item) for item in row["evidence"]]
        for item in evidence:
            if (
                not (0 <= item.start_char < item.end_char <= end)
                or material.content[item.start_char : item.end_char] != item.text
            ):
                raise ValueError("Gold evidence position/text mismatch")
        if (case["case_id"], "B") not in keys:
            results.append(
                {
                    "case_id": case["case_id"],
                    "condition": "B",
                    "response": case["assistant"].content,
                    "timing": case["assistant"].metadata.get("timing"),
                    "origin": "actual-native-reply",
                }
            )
            keys.add((case["case_id"], "B"))
        baseline_material = material.model_copy(update={"analysis": None})
        baseline = assemble_turn_context(baseline_material, prefix, case["user"].content)
        conditions = ["A", "C"]
        random.Random(case["case_id"]).shuffle(conditions)
        for condition in conditions:
            if (case["case_id"], condition) in keys:
                continue
            context = (
                baseline
                if condition == "A"
                else baseline.model_copy(
                    update={
                        "brief": "Manually source-checked passages; no prewritten answer or mandatory interpretation.",
                        "notes": [],
                        "evidence": evidence,
                        "memory": [],
                        "focus_points": [],
                        "gaps": [],
                    }
                )
            )
            instruction = PracticeInstruction(
                prompt="Free discussion",
                metadata={
                    "turn_context": context.model_dump(mode="json"),
                    "options": session.options.model_dump(mode="json"),
                },
            )
            started = perf_counter()
            parts, first = [], None
            try:
                async for part in provider.stream_reply(
                    current_instruction=instruction,
                    material=baseline_material,
                    message_history=[*prefix.messages, case["user"]],
                    user_message=case["user"],
                    corrections=[],
                    target_language=session.profile.target_language,
                ):
                    if first is None and part:
                        first = perf_counter()
                    parts.append(part)
                result = {
                    "case_id": case["case_id"],
                    "condition": condition,
                    "response": "".join(parts),
                    "timing": {
                        "ttft_ms": (first - started) * 1000 if first else None,
                        "total_ms": (perf_counter() - started) * 1000,
                    },
                    "origin": "same-native-user-and-frozen-prior-history-replay",
                }
            except Exception as exc:
                result = {
                    "case_id": case["case_id"],
                    "condition": condition,
                    "error": type(exc).__name__,
                }
                results.append(result)
                dump(path, results)
                raise
            results.append(result)
            keys.add((case["case_id"], condition))
            dump(path, results)
            print(
                json.dumps(
                    {"case": case["case_id"], "condition": condition, "complete": len(results)},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    blinded = []
    for case in cases:
        candidates = [row for row in results if row["case_id"] == case["case_id"]]
        random.Random("blind:" + case["case_id"]).shuffle(candidates)
        blinded.append(
            {
                "case_id": case["case_id"],
                "question": case["user"].content,
                "candidates": [
                    {"label": chr(65 + i), "response": row.get("response", "")}
                    for i, row in enumerate(candidates)
                ],
                "independent_human_ratings": None,
            }
        )
    dump(output / "blinded-responses.json", blinded)


async def languages(provider, output):
    fixtures = [
        (
            "chinese",
            "作者认为，交通拥堵不能只靠扩建道路解决。新增道路可能吸引更多汽车，因此短期顺畅不一定持续。\n作者同时承认，在缺乏基本道路的地区，修路仍可能有益；结论需要考虑当地条件，并非禁止所有道路建设。",
            "作者的说法不是修路永远没用，对吗？",
        ),
        (
            "japanese",
            "00:00:01 --> 00:00:03\n葵：雨がやむまで駅で待とう。\n00:00:04 --> 00:00:06\n蓮：僕の傘を使って、先に帰っていいよ。\n00:00:07 --> 00:00:09\n葵：でも、一人で待たせたくない。",
            "葵は傘がないことより、蓮を一人にすることが気になるのかな。",
        ),
    ]
    rows = []
    for language, text, question in fixtures:
        work = LearningWorkbench(provider, event_store=SQLiteStore(output / f"{language}.sqlite3"))
        code = LanguageEnum(language)
        suffix = ".srt" if language == "japanese" else ".md"
        path = output / f"authored-{language}{suffix}"
        if language == "japanese":
            text = "1\n00:00:01,000 --> 00:00:03,000\n葵：雨がやむまで駅で待とう。\n\n2\n00:00:04,000 --> 00:00:06,000\n蓮：僕の傘を使って、先に帰っていいよ。\n\n3\n00:00:07,000 --> 00:00:09,000\n葵：でも、一人で待たせたくない。"
        path.write_text(text, encoding="utf-8")
        await work.load_imported_material(
            import_material_file(path),
            title=f"Authored {language} fixture",
            source_language=code,
            target_language=code,
            native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B2,
            auto_prepare=False,
        )
        work.set_reading_scope(len(work.material.content))
        await work.prepare_current_material()
        if work.material.analysis.knowledge.status != "ready":
            raise RuntimeError(f"{language} preparation incomplete")
        await work.start_session()
        reply = await work.send_message(question)
        rows.append(
            {
                "language": language,
                "status": work.material.analysis.knowledge.status,
                "notes": work.material.analysis.knowledge.model_dump(mode="json"),
                "question": question,
                "response": reply.assistant_message.content,
                "timing": reply.timing.model_dump(mode="json"),
            }
        )
        dump(output / "language-checks.json", rows)
        # The shared provider is closed once, after both independent workbenches.
        if work._preparation_task and not work._preparation_task.done():
            work._preparation_task.cancel()
            await asyncio.gather(work._preparation_task, return_exceptions=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["export", "draft-gold", "compare", "languages"], required=True
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--request-ledger", type=Path)
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(args.data_dir / "lingualoop.sqlite3")
    if args.phase == "export":
        print({"native_reader_turns": export(store, args.output)})
        return
    if args.phase == "draft-gold":
        draft_gold(store, args.output)
        return
    load_dotenv(ROOT / ".env")
    if not args.real or os.getenv("RUN_REAL_AI_TESTS") != "1" or not args.request_ledger:
        raise SystemExit(
            "Real validation requires --real, RUN_REAL_AI_TESTS=1 and --request-ledger"
        )
    guard = ModelRequestGuard(args.request_ledger, 100)
    provider = OpenAICompatibleLLMProvider.from_env()
    records = []

    class GuardedClient(AuditClient):
        def begin(self, streaming):
            guard.reserve(self.role)
            return super().begin(streaming)

    for name, role in [("_reasoning_client", "reasoning"), ("_dialogue_client", "dialogue")]:
        client = getattr(provider, name).model_copy(update={"max_retries": 0})
        setattr(provider, name, GuardedClient(client, role, records, max_calls=100))
    try:
        if args.phase == "compare":
            if not args.gold:
                raise SystemExit("--gold is required")
            await compare(store, provider, args.output, args.gold)
        else:
            await languages(provider, args.output)
    finally:
        await provider.aclose()
        dump(args.output / f"{args.phase}-requests.json", records)


if __name__ == "__main__":
    asyncio.run(main())
