"""Deterministic source boundaries, grounded retrieval and context assembly."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lingualoop.core.domain import LearningMaterial, PracticeSession

from lingualoop.core.knowledge import (
    MaterialKnowledge,
    MemoryItem,
    SourceSpan,
    SourceUnit,
    TurnContext,
    TurnEvidence,
)

VERSION = "semantic-v1"
AUXILIARY_KINDS = {"foreword", "author_note", "commentary"}


@lru_cache(maxsize=4096)
def cached_terms(text: str) -> frozenset[str]:
    from lingualoop.core.material_context import _terms

    return frozenset(_terms(text))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Local multilingual estimate, separate from provider-reported usage."""
    ascii_count = sum(ord(char) < 128 for char in text)
    return max(1, math.ceil(ascii_count / 4) + 2 * (len(text) - ascii_count))


def heading_kind(text: str, current: str) -> str:
    heading = text.strip().strip('[]“”"').casefold()
    if len(heading) > 160:
        return current
    if re.fullmatch(r"(?:.*\b)?(?:foreword|preface)|序言|前言|まえがき", heading):
        return "foreword"
    if re.search(r"on a book entitled|^afterword$|^あとがき$|^后记$|^作者说明$", heading):
        return "author_note"
    if re.search(r"^commentary$|^解説$|^评论$|^解说$|^by craig raine$", heading):
        return "commentary"
    if re.fullmatch(
        r"part (?:one|two|three|four|\d+)|chapter .+|第.{1,12}[章部篇]|\d{1,3}", heading
    ):
        if heading.isdigit() and current in AUXILIARY_KINDS:
            return current
        return "body"
    return current


def source_units(text: str, end: int, *, target_tokens: int = 6000) -> list[SourceUnit]:
    """Stable greedy boundaries. Only the last unit changes when a prefix advances."""
    end = min(end, len(text))
    if end < len(text):
        # The entire original already exists locally. Determine structural cuts
        # without sending unread text anywhere, then clip the boundary unit.
        full = source_units(text, len(text), target_tokens=target_tokens)
        clipped = []
        for unit in full:
            if unit.start_char >= end:
                break
            if unit.end_char <= end:
                clipped.append(unit)
                continue
            paragraphs = []
            for span in unit.paragraphs:
                if span.start_char >= end:
                    break
                stop = min(span.end_char, end)
                paragraphs.append(
                    SourceSpan(
                        id=f"p_{span.start_char}_{digest(text[span.start_char : stop])[:10]}",
                        start_char=span.start_char,
                        end_char=stop,
                    )
                )
            content_hash = digest(text[unit.start_char : end])
            clipped.append(
                unit.model_copy(
                    update={
                        "id": f"unit_{unit.start_char}_{content_hash[:12]}",
                        "end_char": end,
                        "content_hash": content_hash,
                        "paragraphs": paragraphs,
                    }
                )
            )
        return clipped
    prefix = text[:end]
    result: list[SourceUnit] = []
    paragraphs: list[SourceSpan] = []
    start, kind, title, tokens = 0, "unknown", "", 0

    def flush(stop: int) -> None:
        nonlocal start, paragraphs, tokens
        if stop <= start:
            return
        content_hash = digest(text[start:stop])
        result.append(
            SourceUnit(
                id=f"unit_{start}_{content_hash[:12]}",
                start_char=start,
                end_char=stop,
                content_hash=content_hash,
                source_kind=kind,
                section_path=title,
                paragraphs=paragraphs,
            )
        )
        start, paragraphs, tokens = stop, [], 0

    for match in re.finditer(r"[^\n]+(?:\n|$)", prefix):
        line = match.group()
        next_kind = heading_kind(line, kind)
        is_heading = next_kind != kind or bool(re.fullmatch(r"\s*\d{1,3}\s*", line))
        if next_kind != kind:
            flush(match.start())
            kind = next_kind
        if is_heading:
            title = line.strip()[:160]
        offset = match.start()
        while offset < match.end():
            # Bound a single very long paragraph without throwing away its tail.
            stop = min(match.end(), offset + 18000)
            while estimate_tokens(text[offset:stop]) > 7800 and stop - offset > 100:
                stop = offset + max(100, (stop - offset) * 3 // 4)
            cost = estimate_tokens(text[offset:stop])
            if paragraphs and (tokens + cost > target_tokens or stop - start > 24000):
                flush(offset)
            span_hash = digest(text[offset:stop])[:10]
            paragraphs.append(
                SourceSpan(id=f"p_{offset}_{span_hash}", start_char=offset, end_char=stop)
            )
            tokens += cost
            offset = stop
    flush(end)
    return result


def coverage_valid(knowledge: MaterialKnowledge) -> bool:
    """A ready flag never substitutes for continuous, bounded source coverage."""
    units = knowledge.units
    if not units or units[0].start_char != 0 or units[-1].end_char != knowledge.scope_end:
        return False
    if len({unit.id for unit in units}) != len(units):
        return False
    if any(left.end_char != right.start_char for left, right in zip(units, units[1:])):
        return False
    for unit in units:
        if unit.start_char >= unit.end_char:
            return False
        if any(
            not (unit.start_char <= span.start_char < span.end_char <= unit.end_char)
            for span in unit.paragraphs
        ):
            return False
    return True


def safe_knowledge(knowledge: MaterialKnowledge, end: int) -> MaterialKnowledge:
    units = [unit for unit in knowledge.units if unit.end_char <= end]
    unit_ids = {unit.id for unit in units}
    spans = {span.id for unit in units for span in unit.paragraphs}
    notes = [
        note
        for note in knowledge.notes
        if note.unit_id in unit_ids
        and note.knowledge_end <= end
        and set(note.dependency_ids) <= unit_ids
        and set(note.support_ids) <= spans
    ]
    brief = (
        knowledge.brief
        if knowledge.brief and knowledge.brief.knowledge_end <= end and knowledge.scope_end == end
        else None
    )
    completed = [value for value in knowledge.completed_unit_ids if value in unit_ids]
    excluded = [value for value in knowledge.excluded_unit_ids if value in unit_ids]
    ready = (
        len(set(completed + excluded)) == len(units)
        and knowledge.scope_end == end
        and brief is not None
        and coverage_valid(knowledge)
    )
    return knowledge.model_copy(
        update={
            "scope_end": end,
            "units": units,
            "notes": notes,
            "brief": brief,
            "completed_unit_ids": completed,
            "excluded_unit_ids": excluded,
            "status": "ready" if ready else "partial",
        }
    )


def prime_turn_index(material: LearningMaterial) -> None:
    """Build the bounded in-memory term cache before the first typed turn.

    This is local CPU work only. The caller runs it off the UI thread; it does
    not select evidence, change reading permission or make a model request.
    """
    end = material.read_through
    end = len(material.content) if end is None else min(end, len(material.content))
    knowledge = material.analysis.knowledge if material.analysis else None
    units = (
        knowledge.units
        if knowledge and knowledge.scope_end == end
        else source_units(material.content, end)
    )
    for unit in units:
        for span in unit.paragraphs:
            if span.end_char <= end:
                cached_terms(material.content[span.start_char : span.end_char])
    for note in knowledge.notes if knowledge else []:
        if note.knowledge_end <= end:
            cached_terms(" ".join([note.text, *note.entities, *note.search_terms]))
            cached_terms(
                " ".join(
                    [
                        note.text,
                        *note.entities,
                        *note.search_terms,
                        *note.aliases.keys(),
                        *(alias for values in note.aliases.values() for alias in values),
                    ]
                )
            )


def assemble_turn_context(
    material: LearningMaterial,
    session: PracticeSession,
    query: str,
    *,
    include_auxiliary: bool = False,
) -> TurnContext:
    from lingualoop.core.material_context import _terms

    started = perf_counter()
    end = (
        session.options.read_through
        if session.options and session.options.read_through is not None
        else material.read_through
    )
    end = len(material.content) if end is None else min(end, len(material.content))
    text = material.content[:end]
    source_hash = material.source_hash or digest(material.content)
    knowledge = material.analysis.knowledge if material.analysis else None
    if knowledge and knowledge.source_hash != source_hash:
        knowledge = None
    knowledge = safe_knowledge(knowledge, end) if knowledge else None
    units = knowledge.units if knowledge else source_units(text, end)
    # There is always an original-source fallback, including the not-yet-prepared tail.
    if not units or units[-1].end_char < end:
        units = source_units(text, end)
    excluded = (
        set(knowledge.excluded_unit_ids)
        if knowledge
        else {unit.id for unit in units if unit.source_kind in AUXILIARY_KINDS}
        if any(unit.source_kind == "body" for unit in units)
        else set()
    )
    allowed = {unit.id for unit in units if include_auxiliary or unit.id not in excluded}
    notes = [note for note in (knowledge.notes if knowledge else []) if note.unit_id in allowed]
    recent = session.messages[-4:]
    previous = " ".join(message.content for message in recent)[-1800:]
    current_terms, previous_terms = _terms(query), _terms(previous)
    if (
        session.initial_focus
        and not any(message.role.value == "user" for message in session.messages)
        and len(current_terms) <= 3
    ):
        # A user-selected opening direction helps resolve a vague first reaction.
        # It is retrieval context, not a fabricated user message or fixed agenda.
        current_terms |= _terms(session.initial_focus)
    terms = current_terms | previous_terms
    note_terms = {
        note.id: cached_terms(" ".join([note.text, *note.entities, *note.search_terms]))
        for note in notes
    }
    frequency = Counter(term for values in note_terms.values() for term in values)

    def relevance(found):
        def weight(term):
            return 1 + math.log((len(notes) + 1) / (frequency.get(term, 0) + 1))

        return 4 * sum(weight(term) for term in found & current_terms) + sum(
            weight(term) for term in found & previous_terms
        )

    ranked = []
    for note in notes:
        searchable = " ".join(
            [
                note.text,
                *note.entities,
                *note.search_terms,
                *note.aliases.keys(),
                *(alias for values in note.aliases.values() for alias in values),
            ]
        )
        found = cached_terms(searchable)
        score = relevance(found) + 8 * len(_terms(" ".join(note.entities)) & current_terms)
        if score:
            ranked.append((score, note))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    selected = [note for _, note in ranked[:6]]
    paragraph_map = {
        span.id: (span, unit) for unit in units for span in unit.paragraphs if unit.id in allowed
    }
    candidates = {}
    # Search full paragraph text as well as semantic access terms; never an empty
    # summary-only packet. Keep counterevidence from distinct related passages.
    for span_id, (span, unit) in paragraph_map.items():
        excerpt = text[span.start_char : span.end_char]
        found = cached_terms(excerpt)
        score = relevance(found)
        exact = re.findall(r'["“]([^"”]{6,160})["”]', query)
        if any(phrase.casefold() in excerpt.casefold() for phrase in exact):
            score += 150
        if score:
            candidates[span_id] = (score, span, unit)
    for note in selected:
        for span_id in note.support_ids:
            if span_id in paragraph_map:
                span, unit = paragraph_map[span_id]
                score = candidates.get(span_id, (0,))[0] + 30
                candidates[span_id] = (score, span, unit)
                # A short adjacent paragraph may supply an antecedent, reply or
                # qualification whose wording does not repeat the current query.
                position = next(i for i, value in enumerate(unit.paragraphs) if value.id == span_id)
                for index in (position - 1, position + 1):
                    if 0 <= index < len(unit.paragraphs):
                        neighbor = unit.paragraphs[index]
                        if neighbor.end_char - neighbor.start_char <= 1000:
                            previous_score = candidates.get(neighbor.id, (0,))[0]
                            candidates[neighbor.id] = (
                                max(previous_score, score * 0.55),
                                neighbor,
                                unit,
                            )
    evidence = []
    total = 0
    for _, span, unit in sorted(candidates.values(), key=lambda item: item[0], reverse=True):
        if len(evidence) >= 4:
            break
        excerpt = text[span.start_char : span.end_char]
        # Preserve short paragraphs whole. Center long paragraphs on actual query
        # words, rather than always taking a detached opening sentence.
        offset = 0
        preserve_paragraph = len(excerpt) <= 6000 and estimate_tokens(excerpt) <= 1800
        if not preserve_paragraph:
            positions = [excerpt.casefold().find(term) for term in current_terms if len(term) > 2]
            positions = [position for position in positions if position >= 0]
            offset = max(0, min(positions, default=0) - 350)
            offset = max(0, excerpt.rfind(" ", 0, offset) + 1) if offset else 0
        if not preserve_paragraph:
            excerpt = excerpt[offset : offset + 4000]
        if total + estimate_tokens(excerpt) > 2200 and evidence:
            continue
        total += estimate_tokens(excerpt)
        evidence.append(
            TurnEvidence(
                id=span.id,
                text=excerpt,
                start_char=span.start_char + offset,
                end_char=span.start_char + offset + len(excerpt),
                source_kind=unit.source_kind,
            )
        )
    selected_ids = {item.id for item in evidence}
    selected = [note for note in selected if set(note.support_ids) <= selected_ids]
    brief = knowledge.brief.summary[:3200] if knowledge and knowledge.brief else ""
    gaps = []
    if not selected and not evidence and terms:
        gaps.append("missing_evidence")
    if (
        re.search(
            r"\b(compare|whereas|contradict|both scenes|earlier|later)\b|对比|两处|前面|矛盾|比較|矛盾",
            query,
            re.I,
        )
        and len({note.unit_id for note in selected}) < 2
    ):
        gaps.append("cross_section")
    if re.search(
        r"\b(you said|you claimed|only one|not what|are you sure|I read that|I thought that|I understood that|did you mean)\b|你刚才|你说的|不对|違う",
        query,
        re.I,
    ):
        gaps.append("challenge")
    if len(session.messages) > 12 and (
        not session.conversation_memory
        or session.conversation_memory.through_message_count < len(session.messages) - 10
    ):
        gaps.append("memory")
    key = digest("|".join(sorted({note.unit_id for note in selected} or selected_ids)))[:24]
    memory = session.conversation_memory.items[-8:] if session.conversation_memory else []
    earlier = sorted(
        session.messages[:-10],
        key=lambda message: len(_terms(message.content) & current_terms),
        reverse=True,
    )
    for message in earlier[:3]:
        if _terms(message.content) & current_terms:
            memory.append(
                MemoryItem(
                    text="Earlier actual message (may since have changed): "
                    + message.content[:350],
                    message_ids=[message.id],
                    speaker=message.role.value,
                    kind="stance",
                )
            )
    focus = session.focus_reference
    focus_points = []
    if (
        focus
        and focus.source_hash == source_hash
        and focus.knowledge_end <= end
        and focus.key == key
    ):
        # Local interpretations expire when the user changes/rebuts the premise;
        # underlying source facts stay cached independently.
        new_users = [
            message
            for message in session.messages
            if message.role.value == "user" and message.id not in focus.based_on_message_ids
        ]
        if len(new_users) <= 1 and "challenge" not in gaps:
            focus_points = [
                point for point in focus.points if set(point.support_ids) <= selected_ids
            ]
    return TurnContext(
        title=material.title,
        scope_end=end,
        source_hash=source_hash,
        brief=brief,
        notes=selected,
        evidence=evidence,
        memory=memory,
        focus_points=focus_points,
        focus_key=key,
        gaps=gaps,
        retrieval_ms=(perf_counter() - started) * 1000,
    )
