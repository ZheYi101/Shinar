"""Structured response parsing, independent of network clients."""

from __future__ import annotations
import json
from typing import Any
from shinar.core.domain import FeedbackItem, FeedbackType, MaterialAnalysis, MaterialExpression, ReviewItem, ReviewItemKind, SessionReview, DiscussionTopic, MaterialCharacter


def _parse_feedback_items(content: str) -> list[FeedbackItem]:
    try:
        payload = _load_json_response(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "LLM returned non-JSON feedback content"
        ) from exc
    if not isinstance(payload, list):
        raise ValueError("feedback response must be a JSON array")

    items: list[FeedbackItem] = []
    for raw_item in payload:
        if not isinstance(raw_item, dict):
            continue
        original = str(raw_item.get("original", "")).strip()
        corrected = str(raw_item.get("corrected", "")).strip()
        explanation = str(raw_item.get("explanation", "")).strip()
        if original and corrected and explanation:
            items.append(
                FeedbackItem(
                    error_type=str(raw_item.get("error_type", FeedbackType.OTHER)),
                    original=original,
                    corrected=corrected,
                    explanation=explanation,
                    source_message_id=raw_item.get("source_message_id"),
                )
            )
    return items

def _parse_material_analysis(content: str) -> MaterialAnalysis:
    try:
        payload = _load_json_response(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "LLM returned non-JSON material analysis"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("material analysis response must be a JSON object")

    raw_expressions = payload.get("expressions", [])
    expressions: list[MaterialExpression] = []
    if isinstance(raw_expressions, list):
        for raw_expression in raw_expressions:
            if not isinstance(raw_expression, dict):
                continue
            text = str(raw_expression.get("text", "")).strip()
            if not text:
                continue
            meaning = raw_expression.get("meaning")
            example = raw_expression.get("example")
            expressions.append(
                MaterialExpression(
                    text=text,
                    meaning=str(meaning).strip() if meaning is not None else None,
                    example=str(example).strip() if example is not None else None,
                )
            )

    def text_list(key: str) -> list[str]:
        value = payload.get(key, [])
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    return MaterialAnalysis(
        summary=str(payload.get("summary", "")).strip(),
        keywords=text_list("keywords"),
        expressions=expressions,
        difficulties=text_list("difficulties"),
        suggested_goals=text_list("suggested_goals"),
        topics=[DiscussionTopic.model_validate(item) for item in payload.get("topics", [])
                if isinstance(item, dict)],
        outline=text_list("outline"),
        characters=[MaterialCharacter.model_validate(item) for item in payload.get("characters", []) if isinstance(item, dict)],
    )

def _parse_review_items(content: str) -> list[ReviewItem]:
    try:
        payload = _load_json_response(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "LLM returned non-JSON review content"
        ) from exc
    if not isinstance(payload, list):
        raise ValueError("review response must be a JSON array")

    items: list[ReviewItem] = []
    for raw_item in payload:
        if not isinstance(raw_item, dict):
            continue
        prompt = str(raw_item.get("prompt", "")).strip()
        answer = str(raw_item.get("answer", "")).strip()
        if prompt and answer:
            items.append(
                ReviewItem(
                    kind=_review_item_kind(raw_item.get("kind")),
                    prompt=prompt,
                    answer=answer,
                    source_message_id=raw_item.get("source_message_id"),
                    source_feedback_id=raw_item.get("source_feedback_id"),
                )
            )
    return items

def _parse_session_review(content: str) -> SessionReview:
    try:
        payload = _load_json_response(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM returned non-JSON session review content") from exc
    if not isinstance(payload, dict):
        raise ValueError("session review response must be a JSON object")
    feedback_payload = json.dumps(payload.get("feedback_items", []), ensure_ascii=False)
    review_payload = json.dumps(payload.get("review_items", []), ensure_ascii=False)
    feedback = _parse_feedback_items(feedback_payload)
    review_items = _parse_review_items(review_payload)[:3]
    return SessionReview(
        summary=str(payload.get("summary", "")).strip() or "Session completed.",
        focus_areas=[
            str(item).strip()
            for item in payload.get("focus_areas", [])
            if str(item).strip()
        ],
        feedback_items=feedback,
        review_items=review_items,
        next_action=str(payload.get("next_action", "")).strip() or None,
    )

def _review_item_kind(value: Any) -> ReviewItemKind:
    if isinstance(value, str):
        try:
            return ReviewItemKind(value)
        except ValueError:
            return ReviewItemKind.CLOZE
    return ReviewItemKind.CLOZE

def _load_json_response(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        array_start = text.find("[")
        array_end = text.rfind("]")
        object_start = text.find("{")
        object_end = text.rfind("}")
        if array_start != -1 and array_end > array_start:
            return json.loads(text[array_start : array_end + 1])
        if object_start != -1 and object_end > object_start:
            return json.loads(text[object_start : object_end + 1])
        raise
