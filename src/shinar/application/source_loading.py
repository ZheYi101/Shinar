"""Plain-data source loading and bounded search; no Qt or conversation writes."""

from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import re
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from shinar.application.source_document import document_sections
from shinar.core.domain import LearningMaterial
from shinar.core.knowledge import SourceSection
from shinar.infrastructure.epub_reader import (
    ReaderBook,
    build_reader_book,
    load_epub_asset,
    save_epub_asset,
)


@dataclass(frozen=True)
class SourceLoadRequest:
    material: LearningMaterial
    end: int
    section_id: str
    asset_directory: Path | None


@dataclass(frozen=True)
class SourceLoadResult:
    sections: list[SourceSection]
    book: ReaderBook | None
    error_code: str = ""


def load_source(request: SourceLoadRequest) -> SourceLoadResult:
    material, end = request.material, request.end
    sections = document_sections(material, end)
    try:
        data = load_epub_asset(request.asset_directory, material.content, material.source_path)
        if data is None:
            return SourceLoadResult(sections, None)
        full = build_reader_book(data, material.content, end=end)
        if request.asset_directory is not None:
            save_epub_asset(request.asset_directory, data, material.content)
        sections = full.sections or sections
        selected = next((section for section in sections if section.id == request.section_id), None)
        book = (
            build_reader_book(data, material.content, selected.start_char, selected.end_char)
            if selected
            else full
        )
        return SourceLoadResult(sections, book)
    except (ValueError, OSError, KeyError, StopIteration, BadZipFile, ParseError):
        return SourceLoadResult(sections, None, "reader_projection_unavailable")


def search_source(text: str, end: int, query: str) -> list[dict]:
    if not query.strip():
        return []
    matches = re.compile(re.escape(query), re.I).finditer(text, 0, end)
    return [
        {
            "start": match.start(),
            "end": match.end(),
            "text": text[max(0, match.start() - 25) : min(end, match.end() + 70)],
        }
        for match in islice(matches, 100)
    ]
