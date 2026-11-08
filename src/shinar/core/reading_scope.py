"""Restrict model-visible data to an explicitly read prefix, including legacy caches."""
from __future__ import annotations

from shinar.core.domain import LearningMaterial, MaterialAnalysis
from shinar.core.knowledge_context import digest, safe_knowledge


def reading_end(material: LearningMaterial, end: int | None = None) -> int:
    boundary = material.read_through if end is None else end
    return len(material.content) if boundary is None else min(boundary, len(material.content))


def scope_material(material: LearningMaterial, end: int | None = None) -> LearningMaterial:
    boundary = reading_end(material, end)
    if boundary >= len(material.content):
        return material
    text = material.content[:boundary]
    analysis = material.analysis
    if analysis and analysis.knowledge:
        knowledge = safe_knowledge(analysis.knowledge, boundary)
        analysis = analysis.model_copy(update={"knowledge": knowledge,
            "summary": knowledge.brief.summary if knowledge.brief else "",
            "outline": [point.text for point in knowledge.brief.points] if knowledge.brief else [],
            "characters": [], "topics": [], "keywords": [], "expressions": [],
            "difficulties": [], "suggested_goals": [],
            "chunks": [chunk for chunk in analysis.chunks if chunk.end_char <= boundary
                       and chunk.analysis_payload.get("reference_kind") == "source"],
            "scope_end": boundary,
            "preparation_complete": knowledge.status == "ready", "overview_complete": knowledge.brief is not None})
    if analysis and analysis.scope_end != boundary:
        # Whole-book summaries/characters can reveal endings even when their quote is early.
        # Only notes produced from entirely contained sections are eligible for reuse.
        chunks = [chunk for chunk in analysis.chunks if chunk.end_char <= boundary
                  and chunk.analysis_payload.get("reference_kind") == "source"]
        analysis = MaterialAnalysis(
            summary="", chunks=chunks, preparation_complete=bool(chunks),
            preparation_strategy="scoped-legacy", scope_end=boundary,
        )
    return material.model_copy(update={
        "content": text, "raw_content": text, "normalized_content": text,
        "analysis": analysis, "read_through": boundary, "subtitle_cues": [],
        "source_hash": material.source_hash or digest(material.content),
    })


def paragraph_boundary(text: str, percent: int) -> int:
    if not 1 <= percent <= 100:
        raise ValueError("阅读进度须为 1 到 100。")
    if percent == 100:
        return len(text)
    end = len(text) * percent // 100
    # Percentages are approximate; always round DOWN and show the actual endpoint.
    boundary = text.rfind("\n", 0, end)
    return boundary + 1 if boundary >= 0 else end
