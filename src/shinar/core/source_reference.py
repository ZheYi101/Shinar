"""Validated, provider-neutral source selection. All offsets are Python [start, end)."""
from __future__ import annotations

from hashlib import sha256
from collections import Counter
import re

from shinar.core.knowledge import TurnSourceSnapshot, SourceSection


def freeze_source_context(
    context: TurnSourceSnapshot, *, material_id: str, text: str, read_through: int,
) -> TurnSourceSnapshot:
    if context.material_id != material_id or context.source_hash != sha256(text.encode()).hexdigest():
        raise ValueError("原文版本已改变，请重新定位。")
    if context.index_version != "source-view-v1" or context.read_through != read_through:
        raise ValueError("本次对话的阅读边界不匹配，请重新定位。")
    for span in (context.base, context.focus):
        if span and not 0 <= span.start_char < span.end_char <= read_through:
            raise ValueError("原文指向超出本次会话的已读范围。")
    if context.base and context.focus and not (
        context.base.start_char <= context.focus.start_char < context.focus.end_char <= context.base.end_char
    ):
        raise ValueError("所选文字不属于当前章节。")
    selected = context.focus or context.base
    quote = text[selected.start_char:selected.end_char] if selected else ""
    if context.quote and context.quote != quote:
        raise ValueError("所选引文与原文位置不匹配。")
    return context.model_copy(update={"quote": quote}, deep=True)


def sections_from_titles(text: str, titles: list[tuple[str, int]]) -> list[SourceSection]:
    """Only map unambiguous, ordered structural headings into unchanged normalized text."""
    lines = list(re.finditer(r"[^\n]+", text))
    wanted = Counter(title.strip() for title, _ in titles)
    actual = Counter(match.group().strip() for match in lines)
    cursor = 0
    sections = []
    for title, level in titles:
        title = title.strip()
        if actual[title] != wanted[title]:
            continue
        match = next((m for m in lines if m.start() >= cursor and m.group().strip() == title), None)
        if match is None:
            continue
        cursor = match.end()
        sections.append(SourceSection(id=f"section_{match.start()}", label=title,
                                      level=level, start_char=match.start(), end_char=len(text)))
    for index, section in enumerate(sections):
        following = next((s for s in sections[index+1:] if s.level <= section.level), None)
        if following:
            section.end_char = following.start_char
    return sections
