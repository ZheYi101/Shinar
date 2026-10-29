"""Local source structure, independent of AI preparation and desktop rendering."""
from __future__ import annotations

from hashlib import sha256
import re

from lingualoop.core.domain import LearningMaterial
from lingualoop.core.knowledge import SourceSection, SourceSpan
from lingualoop.core.source_reference import sections_from_titles

INDEX_VERSION = "source-view-v1"


def document_sections(material: LearningMaterial, end: int) -> list[SourceSection]:
    text = material.content
    sections = material.source_sections
    if not sections:
        # Explicit standalone chapter names only. A bare page number is not a chapter.
        titles = [(m.group().strip(), 1) for m in re.finditer(
            r"(?im)^(?:chapter\s+[^\n]{1,80}|part\s+[^\n]{1,80}|第[^\n]{1,20}[章部篇])\s*$", text)]
        sections = sections_from_titles(text, titles)
    return [s.model_copy(update={"end_char": min(s.end_char, end)})
            for s in sections if 0 <= s.start_char < min(s.end_char, end) <= len(text)
            and text[s.start_char:s.end_char].startswith(s.label)]


def document_paragraphs(text: str, start: int = 0, end: int | None = None) -> list[SourceSpan]:
    end = len(text) if end is None else min(end, len(text))
    result = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text[start:end]):
        a, b = start + match.start(), start + match.end()
        if text[a:b].strip():
            result.append(SourceSpan(id=f"p_{a}", start_char=a, end_char=b))
    return result


def source_hash(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def utf16_to_python(text: str, offset: int) -> int:
    if offset < 0:
        raise ValueError("Invalid text position")
    units = text.encode("utf-16-le")
    if offset * 2 > len(units):
        raise ValueError("Invalid text position")
    try:
        return len(units[:offset*2].decode("utf-16-le"))
    except UnicodeDecodeError as exc:
        raise ValueError("Position splits a Unicode character") from exc


def python_to_utf16(text: str, offset: int) -> int:
    return len(text[:offset].encode("utf-16-le")) // 2
