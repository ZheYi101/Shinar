"""Resumable semantic preparation, independently cached and durably budgeted."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, TypeVar

from lingualoop.core.domain import LearningMaterial, MaterialAnalysis, PracticeSession, new_id
from lingualoop.core.knowledge import (
    BriefPoint,
    ConversationMemory,
    FocusReference,
    GroundedNote,
    MaterialKnowledge,
    MemoryItem,
    ModelBudgetExceeded,
    ReadingBrief,
    ReasoningRequest,
    ReasoningResponse,
    SourceSpan,
    SourceUnit,
    TurnContext,
    model_call_usage,
)
from lingualoop.core.knowledge_context import (
    AUXILIARY_KINDS,
    VERSION,
    coverage_valid,
    digest,
    estimate_tokens,
    source_units,
)

T = TypeVar("T")


class PreparationFailure(ValueError):
    """Safe diagnostic: no raw model output or source material in error messages."""


class PreparationTruncated(PreparationFailure):
    """A different, smaller source request is needed; never raise its token cap."""


def parse_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


class SemanticPreparation:
    def __init__(
        self, provider, store, *, foreground_active: Callable[[], bool] | None = None
    ) -> None:
        self.provider = provider
        self.store = store
        self.foreground_active = foreground_active or (lambda: False)
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def supported(self) -> bool:
        return bool(getattr(self.provider, "supports_semantic_preparation", False)) and not getattr(
            self.provider, "offline_read_only", False
        )

    def identity(self, material: LearningMaterial) -> str:
        public = getattr(
            self.provider, "preparation_cache_identity", type(self.provider).__qualname__
        )
        return digest(
            json.dumps([VERSION, public, material.source_language.value], ensure_ascii=False)
        )

    def owner(self, material: LearningMaterial) -> str:
        return (
            "material:"
            + (material.source_hash or digest(material.content))
            + ":"
            + self.identity(material)
        )

    def manifest_key(
        self, material: LearningMaterial, end: int, identity: str | None = None
    ) -> str:
        return digest(
            json.dumps(
                [
                    "manifest",
                    material.source_hash or digest(material.content),
                    identity or self.identity(material),
                    end,
                ]
            )
        )

    def load_manifest(
        self, material: LearningMaterial, end: int, identity: str | None = None
    ) -> MaterialKnowledge | None:
        if not hasattr(self.store, "get_knowledge_artifact"):
            return None
        payload = self.store.get_knowledge_artifact(self.manifest_key(material, end, identity))
        try:
            value = MaterialKnowledge.model_validate(payload) if payload else None
            if (
                value
                and value.scope_end == end
                and value.source_hash == (material.source_hash or digest(material.content))
                and value.version == VERSION
                and coverage_valid(value)
            ):
                unit_ids = {unit.id for unit in value.units}
                if value.status == "ready" and (
                    value.brief is None
                    or set(value.completed_unit_ids + value.excluded_unit_ids) != unit_ids
                ):
                    return None
                spans = {span.id for unit in value.units for span in unit.paragraphs}
                if any(
                    unit.end_char > end
                    or unit.content_hash
                    != digest(material.content[unit.start_char : unit.end_char])
                    for unit in value.units
                ):
                    return None
                if any(
                    note.unit_id not in unit_ids
                    or note.knowledge_end > end
                    or not set(note.dependency_ids) <= unit_ids
                    or not set(note.support_ids) <= spans
                    for note in value.notes
                ):
                    return None
                if value.brief and (
                    value.brief.knowledge_end > end
                    or not set(value.brief.support_ids) <= {note.id for note in value.notes}
                    or any(
                        not set(point.support_ids) <= {note.id for note in value.notes}
                        for point in value.brief.points
                    )
                ):
                    return None
                return value
        except (ValueError, TypeError):
            pass
        return None

    def save_manifest(self, material: LearningMaterial, knowledge: MaterialKnowledge) -> None:
        if hasattr(self.store, "save_knowledge_artifact"):
            self.store.save_knowledge_artifact(
                self.manifest_key(material, knowledge.scope_end, knowledge.generation_identity),
                knowledge.source_hash,
                "manifest",
                knowledge.model_dump(mode="json"),
            )

    async def account(
        self,
        owner: str,
        workload: str,
        fingerprint: str,
        input_tokens: int,
        output_tokens: int,
        operation: Callable[[], Awaitable[T]],
        *,
        deadline: float = 150,
        metadata: dict[str, Any] | None = None,
    ) -> T:
        """Reserve before sending; unknown failed/cancelled usage keeps its reservation."""
        call_id = new_id("call")
        if hasattr(self.store, "reserve_model_call"):
            self.store.reserve_model_call(
                call_id,
                owner,
                workload,
                fingerprint,
                input_tokens,
                output_tokens,
                lease_seconds=deadline + 15,
                metadata=metadata,
            )
        usage: dict[str, Any] = {}
        token = model_call_usage.set(usage)
        started = perf_counter()
        status = "unknown"
        try:
            result = await operation()
            if isinstance(result, ReasoningResponse):
                usage.update(
                    {
                        key: value
                        for key, value in result.usage.items()
                        if key
                        in {
                            "input_tokens",
                            "output_tokens",
                            "total_tokens",
                            "reasoning_tokens",
                            "finish_reason",
                        }
                    }
                )
            status = "truncated" if usage.get("finish_reason") == "length" else "completed"
            return result
        except BaseException:
            status = "failed" if "input_tokens" in usage and "output_tokens" in usage else "unknown"
            raise
        finally:
            model_call_usage.reset(token)
            if hasattr(self.store, "settle_model_call"):
                self.store.settle_model_call(
                    call_id, usage, status, elapsed_ms=(perf_counter() - started) * 1000
                )

    async def request(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        owner: str,
        cache_key: str,
        source_hash: str,
        validate: Callable[[dict[str, Any]], T],
        max_tokens: int = 4096,
        deadline: float = 120,
        background: bool = False,
    ) -> T:
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            last = (
                self.store.latest_model_call(owner, method, cache_key)
                if hasattr(self.store, "latest_model_call")
                else None
            )
            if last and last["status"] == "truncated":
                raise PreparationTruncated("该输入曾达到输出预算，需要缩小输入后继续。")
            failure = (
                self.store.get_knowledge_artifact("failed:" + cache_key)
                if hasattr(self.store, "get_knowledge_artifact")
                else None
            )
            if failure and failure.get("reason") == "length":
                raise PreparationTruncated("该输入曾达到输出预算，需要缩小输入后继续。")
            cached = (
                self.store.get_knowledge_artifact(cache_key)
                if hasattr(self.store, "get_knowledge_artifact")
                else None
            )
            if cached:
                try:
                    result = validate(cached)
                except (ValueError, TypeError, KeyError):
                    pass
                else:
                    if hasattr(self.store, "record_knowledge_cache_hit"):
                        self.store.record_knowledge_cache_hit(cache_key, source_hash, method)
                    return result
            for attempt in range(2):
                while background and self.foreground_active():
                    await asyncio.sleep(0.05)
                request_payload = dict(payload)
                if attempt:
                    request_payload["repair"] = (
                        "Previous structure or evidence IDs were invalid. Return the compact requested schema using only supplied IDs."
                    )
                request = ReasoningRequest(
                    payload=request_payload, max_tokens=max_tokens, deadline_seconds=deadline
                )
                response = await self.account(
                    owner,
                    method,
                    cache_key + f":{attempt}",
                    estimate_tokens(json.dumps(request_payload, ensure_ascii=False)) + 1000,
                    max_tokens,
                    lambda: asyncio.wait_for(
                        getattr(self.provider, method)(request), timeout=deadline
                    ),
                    deadline=deadline,
                    metadata={
                        "source_hash": source_hash,
                        "source_revision": cache_key,
                        "source_ids": [item["id"] for item in payload.get("paragraphs", [])],
                        "message_ids": [
                            item["id"]
                            for item in payload.get("recent", payload.get("messages", []))
                        ],
                    },
                )
                if response.usage.get("finish_reason") == "length":
                    if hasattr(self.store, "save_knowledge_artifact"):
                        self.store.save_knowledge_artifact(
                            "failed:" + cache_key, source_hash, "failure", {"reason": "length"}
                        )
                    raise PreparationTruncated(
                        "模型输出达到预算，当前资料未记为成功；可保留进度后重试。"
                    )
                try:
                    data = parse_object(response.content)
                    result = validate(data)
                except (ValueError, TypeError, KeyError):
                    if attempt:
                        raise PreparationFailure(
                            "资料结构或来源验证失败，原文与已完成进度保留。"
                        ) from None
                    continue
                if hasattr(self.store, "save_knowledge_artifact"):
                    self.store.save_knowledge_artifact(cache_key, source_hash, method, data)
                return result
        raise AssertionError("unreachable")

    def initial(self, material: LearningMaterial) -> MaterialKnowledge:
        end = material.read_through if material.read_through is not None else len(material.content)
        if end <= 0:
            raise ValueError("请先确认已读范围。")
        units = []
        for root in source_units(material.content, len(material.content)):
            if root.start_char >= end:
                break
            for unit in self._expanded_units(material, root):
                if unit.start_char >= end:
                    break
                if unit.end_char > end:
                    value_hash = digest(material.content[unit.start_char : end])
                    paragraphs = [
                        SourceSpan(
                            id=f"p_{span.start_char}_{digest(material.content[span.start_char : min(span.end_char, end)])[:10]}",
                            start_char=span.start_char,
                            end_char=min(span.end_char, end),
                        )
                        for span in unit.paragraphs
                        if span.start_char < end
                    ]
                    unit = unit.model_copy(
                        update={
                            "id": f"unit_{unit.start_char}_{value_hash[:12]}",
                            "content_hash": value_hash,
                            "end_char": end,
                            "paragraphs": paragraphs,
                        }
                    )
                units.append(unit)
        excluded = (
            [unit.id for unit in units if unit.source_kind in AUXILIARY_KINDS]
            if any(unit.source_kind == "body" for unit in units)
            else []
        )
        return MaterialKnowledge(
            source_hash=material.source_hash or digest(material.content),
            scope_end=end,
            units=units,
            excluded_unit_ids=excluded,
            generation_identity=self.identity(material),
        )

    def _split_key(self, material: LearningMaterial, unit: SourceUnit) -> str:
        return digest(json.dumps([self.identity(material), unit.id, "split-plan"]))

    def _expanded_units(
        self, material: LearningMaterial, unit: SourceUnit, depth: int = 0
    ) -> list[SourceUnit]:
        cached = (
            self.store.get_knowledge_artifact(self._split_key(material, unit))
            if hasattr(self.store, "get_knowledge_artifact")
            else None
        )
        if cached and depth < 3:
            try:
                children = [SourceUnit.model_validate(value) for value in cached["units"]]
                if (
                    not children
                    or children[0].start_char != unit.start_char
                    or children[-1].end_char != unit.end_char
                ):
                    raise ValueError("Invalid split coverage")
                if any(
                    left.end_char != right.start_char for left, right in zip(children, children[1:])
                ):
                    raise ValueError("Invalid split continuity")
                if any(
                    child.content_hash
                    != digest(material.content[child.start_char : child.end_char])
                    for child in children
                ):
                    raise ValueError("Invalid split hash")
                return [
                    result
                    for child in children
                    for result in self._expanded_units(material, child, depth + 1)
                ]
            except (ValueError, TypeError, KeyError):
                pass
        return [unit]

    def _save_smaller_units(self, material: LearningMaterial, unit: SourceUnit) -> None:
        text = material.content[unit.start_char : unit.end_char]
        if estimate_tokens(text) <= 1200 or not hasattr(self.store, "save_knowledge_artifact"):
            return
        children = source_units(
            text, len(text), target_tokens=max(1000, estimate_tokens(text) // 2)
        )
        if len(children) < 2:
            # A single long paragraph needs a deterministic interior cut too.
            middle = len(text) // 2
            children = source_units(text[:middle], middle) + [
                child.model_copy(
                    update={
                        "start_char": child.start_char + middle,
                        "end_char": child.end_char + middle,
                        "paragraphs": [
                            span.model_copy(
                                update={
                                    "start_char": span.start_char + middle,
                                    "end_char": span.end_char + middle,
                                }
                            )
                            for span in child.paragraphs
                        ],
                    }
                )
                for child in source_units(text[middle:], len(text) - middle)
            ]
        absolute = []
        for child in children:
            start, stop = unit.start_char + child.start_char, unit.start_char + child.end_char
            value_hash = digest(material.content[start:stop])
            spans = [
                SourceSpan(
                    id=f"p_{unit.start_char + span.start_char}_{digest(material.content[unit.start_char + span.start_char : unit.start_char + span.end_char])[:10]}",
                    start_char=unit.start_char + span.start_char,
                    end_char=unit.start_char + span.end_char,
                )
                for span in child.paragraphs
            ]
            absolute.append(
                SourceUnit(
                    id=f"unit_{start}_{value_hash[:12]}",
                    start_char=start,
                    end_char=stop,
                    content_hash=value_hash,
                    source_kind=unit.source_kind,
                    section_path=unit.section_path,
                    paragraphs=spans,
                )
            )
        self.store.save_knowledge_artifact(
            self._split_key(material, unit),
            material.source_hash or digest(material.content),
            "split-plan",
            {"units": [child.model_dump() for child in absolute]},
        )

    async def prepare(
        self,
        material: LearningMaterial,
        on_progress: Callable[[MaterialKnowledge], Awaitable[None]],
        *,
        split_depth: int = 0,
    ) -> MaterialKnowledge:
        knowledge = self.initial(material)
        owner = self.owner(material)
        amount = estimate_tokens(material.content[: knowledge.scope_end])
        if hasattr(self.store, "ensure_model_budget"):
            # Merge groups and one repair per task share these same durable limits.
            self.store.ensure_model_budget(
                owner,
                input_limit=2 * amount + 16000,
                output_limit=max(16000, int(0.75 * amount)),
                request_limit=2 * (len(knowledge.units) + 8),
            )
        notes: list[GroundedNote] = []
        completed: list[str] = []
        errors: dict[str, str] = {}

        async def save(status: str, brief: ReadingBrief | None = None) -> MaterialKnowledge:
            nonlocal knowledge
            knowledge = knowledge.model_copy(
                update={
                    "notes": list(notes),
                    "completed_unit_ids": list(completed),
                    "errors": dict(errors),
                    "status": status,
                    "brief": brief,
                }
            )
            self.save_manifest(material, knowledge)
            await on_progress(knowledge)
            return knowledge

        await save("preparing")
        for unit_index, unit in enumerate(knowledge.units):
            if unit.id in knowledge.excluded_unit_ids:
                # Original auxiliary material stays local and separately tagged;
                # it is not a default paid workload for story discussion.
                continue
            previous_unit = knowledge.units[unit_index - 1] if unit_index else None
            preceding = (
                material.content[
                    max(previous_unit.start_char, unit.start_char - 350) : unit.start_char
                ]
                if previous_unit and previous_unit.source_kind == unit.source_kind
                else ""
            )
            while preceding and estimate_tokens(preceding) > 300:
                preceding = preceding[max(1, len(preceding) // 8) :]
            dependencies = [previous_unit.id] if preceding and previous_unit else []
            payload = {
                "source_language": material.source_language.value,
                "source_kind": unit.source_kind,
                "section": unit.section_path,
                "preceding_context": preceding,
                "paragraphs": [
                    {"id": span.id, "text": material.content[span.start_char : span.end_char]}
                    for span in unit.paragraphs
                ],
            }
            key = digest(
                json.dumps(
                    [knowledge.generation_identity, unit.model_dump(), digest(preceding)],
                    sort_keys=True,
                )
            )
            try:
                values = await self.request(
                    "prepare_source_unit",
                    payload,
                    owner=owner,
                    cache_key=key,
                    source_hash=knowledge.source_hash,
                    validate=lambda data, current=unit, deps=dependencies: validate_unit_notes(
                        data, current, deps
                    ),
                    background=True,
                )
                notes.extend(values)
                completed.append(unit.id)
                await save("preparing")
            except asyncio.CancelledError:
                await save("partial")
                raise
            except Exception as exc:
                if isinstance(exc, PreparationTruncated):
                    self._save_smaller_units(material, unit)
                errors[unit.id] = type(exc).__name__
                await save("partial" if completed else "failed")
                if (
                    isinstance(exc, PreparationTruncated)
                    and split_depth < 3
                    and len(self._expanded_units(material, unit)) > 1
                ):
                    return await self.prepare(material, on_progress, split_depth=split_depth + 1)
                # Budget/deadline/provider errors stop this run. Successful unit
                # artifacts survive and the explicit retry starts from their cache.
                return knowledge
        body_notes = notes
        try:
            brief = await self.make_brief(material, knowledge, body_notes, owner)
        except asyncio.CancelledError:
            await save("partial")
            raise
        except Exception as exc:
            errors["brief"] = type(exc).__name__
            return await save("partial")
        return await save("ready", brief)

    async def make_brief(
        self,
        material: LearningMaterial,
        knowledge: MaterialKnowledge,
        notes: list[GroundedNote],
        owner: str,
    ) -> ReadingBrief:
        if not notes:
            raise PreparationFailure("当前范围未形成足够的语义笔记，不能标记整体认识完成。")
        # Bounded fan-in; leaf notes remain unchanged and independently retrievable.
        items = [
            {
                "id": note.id,
                "text": note.text,
                "attribution": note.attribution,
                "kind": note.statement_kind,
                "entities": note.entities,
            }
            for note in notes
        ]
        ancestry = {note.id: [note.id] for note in notes}
        generation = 0
        while estimate_tokens(json.dumps(items, ensure_ascii=False)) > 12000:
            groups, group = [], []
            for item in items:
                if group and estimate_tokens(json.dumps([*group, item], ensure_ascii=False)) > 6000:
                    groups.append(group)
                    group = []
                group.append(item)
            if group:
                groups.append(group)
            if len(groups) == 1:
                raise PreparationFailure("合并输入超出预算。")
            merged = []
            for index, group in enumerate(groups):
                brief = await self._brief_request(
                    material, knowledge, group, owner, f"group-{generation}-{index}"
                )
                group_id = f"group-{generation}-{index}"
                ancestry[group_id] = sorted(
                    {source for item in group for source in ancestry[item["id"]]}
                )
                merged.append(
                    {
                        "id": group_id,
                        "text": brief.summary,
                        "source_ids": sorted(
                            {value for point in brief.points for value in point.support_ids}
                        ),
                    }
                )
            items = merged
            generation += 1
        brief = await self._brief_request(material, knowledge, items, owner, "reading")
        points = [
            point.model_copy(
                update={
                    "support_ids": sorted(
                        {source for value in point.support_ids for source in ancestry[value]}
                    )
                }
            )
            for point in brief.points
        ]
        # Global brief provenance includes every input unit, including empty notes.
        return brief.model_copy(
            update={
                "knowledge_end": knowledge.scope_end,
                "support_ids": [note.id for note in notes],
                "points": points,
            }
        )

    async def _brief_request(self, material, knowledge, items, owner, kind):
        wire_ids = {f"n{index + 1}": item["id"] for index, item in enumerate(items)}
        compact = [
            {
                "id": alias,
                "text": item["text"],
                "who": item.get("attribution", "source notes"),
                "kind": item.get("kind", "condensed notes"),
            }
            for alias, item in zip(wire_ids, items)
        ]
        payload = {
            "source_language": material.source_language.value,
            "title": material.title,
            "read_scope_end": knowledge.scope_end,
            "ordered_notes": compact,
        }
        key = digest(
            json.dumps(
                [knowledge.generation_identity, kind, payload, wire_ids],
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        allowed = set(wire_ids)

        def validate(data):
            summary = str(data["summary"]).strip()
            if not summary or len(summary) > 6500:
                raise ValueError("Invalid brief length")
            points = [BriefPoint.model_validate(point) for point in data.get("points", [])]
            if any(
                not point.support_ids or not set(point.support_ids) <= allowed for point in points
            ):
                raise ValueError("Unknown note ID")
            points = [
                point.model_copy(
                    update={"support_ids": [wire_ids[value] for value in point.support_ids]}
                )
                for point in points
            ]
            return ReadingBrief(
                summary=summary,
                points=points[:16],
                support_ids=sorted(wire_ids.values()),
                knowledge_end=knowledge.scope_end,
            )

        return await self.request(
            "summarize_reading",
            payload,
            owner=owner,
            cache_key=key,
            source_hash=knowledge.source_hash,
            validate=validate,
            background=True,
        )

    async def focus(
        self,
        material: LearningMaterial,
        session: PracticeSession,
        context: TurnContext,
        *,
        query: str = "",
        background: bool = True,
    ) -> FocusReference:
        owner = f"background:{session.id}"
        if hasattr(self.store, "ensure_model_budget"):
            self.store.ensure_model_budget(
                owner, input_limit=32000, output_limit=8192, request_limit=8
            )
        ids = [message.id for message in session.messages]
        payload = {
            "title": material.title,
            "target_language": session.profile.target_language.value,
            "gap": context.gaps,
            "brief": context.brief[:2200],
            "current_query": query,
            "evidence": [item.model_dump() for item in context.evidence],
            "notes": [note.model_dump() for note in context.notes],
            "recent": [
                {"id": message.id, "role": message.role.value, "text": message.content}
                for message in session.messages[-6:]
            ],
        }
        allowed = {item.id for item in context.evidence}
        key = digest(
            json.dumps(
                [VERSION, self.identity(material), context.focus_key, query, payload["recent"]],
                sort_keys=True,
                ensure_ascii=False,
            )
        )

        def validate(data):
            points = [BriefPoint.model_validate(point) for point in data.get("points", [])]
            if any(
                not point.support_ids
                or not set(point.support_ids) <= allowed
                or len(point.text) > 1000
                for point in points
            ):
                raise ValueError("Unsupported focus point")
            units = (
                material.analysis.knowledge.units
                if material.analysis and material.analysis.knowledge
                else source_units(material.content, context.scope_end)
            )
            span_units = {span.id: unit for unit in units for span in unit.paragraphs}
            facts = []
            for value in data.get("facts", [])[:2]:
                supports = value.get("support_ids", [])
                if (
                    not supports
                    or not set(supports) <= allowed
                    or not set(supports) <= span_units.keys()
                ):
                    raise ValueError("Unsupported focus fact")
                if value.get("statement_kind") not in {"narrated", "claim", "uncertain"}:
                    raise ValueError("Interpretation cannot become a material fact")
                first_unit = span_units[supports[0]]
                facts.append(
                    GroundedNote.model_validate(
                        {
                            **value,
                            "id": "focus_"
                            + digest(json.dumps(value, sort_keys=True, ensure_ascii=False))[:24],
                            "unit_id": first_unit.id,
                            "source_kind": first_unit.source_kind,
                            "dependency_ids": [
                                unit.id for unit in units if unit.end_char <= context.scope_end
                            ],
                            "knowledge_end": context.scope_end,
                        }
                    )
                )
            return FocusReference(
                key=context.focus_key,
                source_hash=context.source_hash,
                knowledge_end=context.scope_end,
                based_on_message_ids=ids,
                points=points[:3],
                facts=facts,
                directions=[str(value)[:120] for value in data.get("directions", [])][:2],
            )

        return await self.request(
            "prepare_focus",
            payload,
            owner=owner,
            cache_key=key,
            source_hash=context.source_hash,
            validate=validate,
            max_tokens=2048,
            deadline=45,
            background=background,
        )

    async def remember(
        self, material: LearningMaterial, session: PracticeSession
    ) -> ConversationMemory:
        owner = f"background:{session.id}"
        if hasattr(self.store, "ensure_model_budget"):
            self.store.ensure_model_budget(
                owner, input_limit=32000, output_limit=8192, request_limit=8
            )
        # Include prior validated memory plus a bounded overlap of original messages.
        old = session.conversation_memory
        start = max(0, old.through_message_count - 4) if old else 0
        messages = session.messages[start:-6][-30:]
        payload = {
            "previous": old.model_dump() if old else None,
            "messages": [
                {"id": message.id, "role": message.role.value, "text": message.content}
                for message in messages
            ],
        }
        known = {message.id: message for message in session.messages}
        allowed = {message.id for message in messages} | set(old.source_message_ids if old else [])

        def validate(data):
            items = [MemoryItem.model_validate(item) for item in data.get("items", [])]
            for item in items:
                if not item.message_ids or not set(item.message_ids) <= allowed:
                    raise ValueError("Unknown message ID")
                if any(known[value].role.value != item.speaker for value in item.message_ids):
                    raise ValueError("Memory speaker mismatch")
            return ConversationMemory(
                items=items[:8],
                through_message_count=len(session.messages) - 6,
                source_message_ids=sorted(allowed),
            )

        return await self.request(
            "summarize_conversation",
            payload,
            owner=owner,
            cache_key=digest(
                json.dumps([self.identity(material), payload], sort_keys=True, ensure_ascii=False)
            ),
            source_hash=material.source_hash or digest(material.content),
            validate=validate,
            max_tokens=2048,
            deadline=45,
            background=True,
        )


def validate_unit_notes(
    data: dict[str, Any], unit: SourceUnit, dependencies: list[str] | None = None
) -> list[GroundedNote]:
    allowed = {span.id for span in unit.paragraphs}
    values = data["notes"]
    if not isinstance(values, list) or len(values) > 16:
        raise ValueError("Invalid note count")
    notes = []
    for index, item in enumerate(values):
        # Provenance is computed from actual request inputs, never from model claims.
        note = GroundedNote.model_validate(
            {
                **item,
                "id": f"{unit.id}:n{index}",
                "unit_id": unit.id,
                "knowledge_end": unit.end_char,
                "dependency_ids": [*(dependencies or []), unit.id],
                "source_kind": unit.source_kind,
            }
        )
        if (
            not note.text.strip()
            or len(note.text) > 1800
            or not note.attribution.strip()
            or not note.support_ids
            or not set(note.support_ids) <= allowed
        ):
            raise ValueError("Invalid grounded note")
        notes.append(note)
    return notes


def analysis_with_knowledge(
    analysis: MaterialAnalysis, knowledge: MaterialKnowledge
) -> MaterialAnalysis:
    return analysis.model_copy(
        update={
            "knowledge": knowledge,
            "preparation_strategy": VERSION,
            "scope_end": knowledge.scope_end,
            "preparation_complete": knowledge.status == "ready",
            "overview_complete": knowledge.brief is not None,
        }
    )
