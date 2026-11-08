"""Zero-model-cost, resumable source references for open conversation."""
from __future__ import annotations

from hashlib import sha256
from collections import Counter
import re

from shinar.core.domain import LearningMaterial, MaterialAnalysis, PreparedChunk
from shinar.core.reading_scope import scope_material

SOURCE_INDEX_VERSION = "source-index-v1"


def build_source_index(material: LearningMaterial) -> MaterialAnalysis:
    scoped = scope_material(material)
    if not scoped.content.strip():
        raise ValueError("请先确认已读到哪里；尚未阅读的内容不会交给 AI。")
    from shinar.application.material_preparation import split_material
    from shinar.core.material_context import _terms

    words = re.findall(r"[A-Za-z][A-Za-z’'-]{2,}", scoped.content)
    total = Counter(word.casefold() for word in words)
    capitals = Counter(word.casefold() for word in words if word[0].isupper())
    names = [name for name, count in capitals.most_common(120)
             if count >= 3 and count / total[name] > 0.8 and name in _terms(name)]
    headings = [(match.start(), match.group(0).strip()) for match in re.finditer(
        r"(?im)^(?:part (?:one|two|three|[0-9]+)|foreword|afterword|introduction|notes|commentary|about the author|[^\n]{0,60}on a book entitled[^\n]*|[A-Z][^\n]{0,65}(?:foreword|afterword|introduction))\s*$",
        scoped.content)]
    chunks = []
    for start, end, text in split_material(scoped.content, size=1800):
        digest = sha256(text.encode("utf-8")).hexdigest()
        section = next((title for position, title in reversed(headings) if position <= start), "Unlabeled source passage")
        chunks.append(PreparedChunk(
            id="source_" + digest[:16] + "_" + str(start), start_char=start, end_char=end,
            summary="", source_excerpt=text[:200], content_hash=digest,
            analysis_payload={"reference_kind": "source", "search_terms": sorted(_terms(text)), "source_section": section},
        ))
    return MaterialAnalysis(
        summary="已建立本地原文索引。聊天时按你的发言选取相关段落，需要时再补充简短参考。",
        keywords=names,
        chunks=chunks, preparation_complete=True, overview_complete=False,
        preparation_strategy=SOURCE_INDEX_VERSION, scope_end=len(scoped.content),
    )
