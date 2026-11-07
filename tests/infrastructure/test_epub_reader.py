from __future__ import annotations

import asyncio
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from lingualoop.application import LearningWorkbench
from lingualoop.core import LanguageEnum, ProficiencyLevel
from lingualoop.infrastructure import SQLiteStore
from lingualoop.infrastructure.epub_reader import build_reader_book, load_epub_asset
from lingualoop.infrastructure.material_import import import_material_file
from lingualoop.providers import MockLearningLLMProvider


def make_epub(path, bodies: list[str], labels: list[str] | None = None):
    labels = labels or [f"Chapter {n + 1}" for n in range(len(bodies))]
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        manifest = (
            '<item id="toc" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>'
        )
        for n, body in enumerate(bodies):
            manifest += f'<item id="c{n}" href="c{n}.xhtml" media-type="application/xhtml+xml"/>'
            archive.writestr(
                f"OPS/c{n}.xhtml",
                f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Book</title></head><body>{body}</body></html>',
            )
        spine = "".join(f'<itemref idref="c{n}"/>' for n in range(len(bodies)))
        archive.writestr(
            "OPS/book.opf",
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title><dc:language>en</dc:language><dc:identifier id="id">reader-test</dc:identifier></metadata><manifest>{manifest}</manifest><spine>{spine}</spine></package>',
        )
        toc = "".join(
            f'<li><a href="c{n}.xhtml">{label}</a></li>' for n, label in enumerate(labels)
        )
        archive.writestr(
            "OPS/nav.xhtml",
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol>{toc}</ol></nav></body></html>',
        )
    return import_material_file(path)


def source_spans(book, member="OPS/c0.xhtml"):
    with ZipFile(BytesIO(book.data)) as archive:
        document = ET.fromstring(archive.read(member))
    return [node for node in document.iter() if "data-source-start" in node.attrib]


@pytest.mark.parametrize(
    "body",
    [
        "<h1>One</h1><p>First  paragraph.\n  More text.</p><p>Second <em>paragraph</em> 😀.</p>",
        "<p>日本語<ruby>漢字<rt>かんじ</rt></ruby>と中文。&amp; café。</p><p>Repeated.</p><p>Repeated.</p>",
        "<div>\n\n\n <h2>Title</h2>  <p>A\t\t B\r\nC</p></div>",
        "<p>Multiple\u2028lines\u0085remain.</p><p>Text with \u00a0 spaces.</p>",
    ],
)
def test_display_spans_reproduce_exact_saved_offsets(tmp_path, body):
    material = make_epub(tmp_path / "book.epub", [body])
    book = build_reader_book(material.epub_content, material.normalized_content)
    spans = source_spans(book)
    assert spans
    prior = 0
    for node in spans:
        a, b = int(node.attrib["data-source-start"]), int(node.attrib["data-source-end"])
        assert a >= prior and a < b
        assert node.text == material.normalized_content[a:b]
        prior = b
    assert book.sections[0].label == "Chapter 1"


def test_partial_display_clips_inside_a_text_node_and_rejects_unread_chapters(tmp_path):
    material = make_epub(
        tmp_path / "book.epub", ["<p>Allowed 😀 sentence. UNREAD SECRET.</p>", "<p>Later plot.</p>"]
    )
    end = material.normalized_content.index(" UNREAD")
    book = build_reader_book(material.epub_content, material.normalized_content, end=end)
    spans = source_spans(book)
    assert "".join(node.text for node in spans) == "Allowed 😀 sentence."
    assert max(int(node.attrib["data-source-end"]) for node in spans) == end
    assert not source_spans(book, "OPS/c1.xhtml")
    assert [section.label for section in book.sections] == ["Chapter 1"]
    with pytest.raises(ValueError, match="source version"):
        build_reader_book(material.epub_content, material.normalized_content + " changed")


def test_static_markup_cannot_execute_scripts_or_load_external_assets(tmp_path):
    material = make_epub(
        tmp_path / "book.epub",
        [
            '<h1 onclick="alert(1)">Title</h1><p>A <a href="javascript:alert(1)">link</a><img src="https://example.test/track.png" onerror="alert(1)"/>.</p><script>alert(1)</script><iframe src="https://example.test/">frame</iframe>'
        ],
    )
    book = build_reader_book(material.epub_content, material.normalized_content)
    with ZipFile(BytesIO(book.data)) as archive:
        html = archive.read("OPS/c0.xhtml").decode()
    for forbidden in ("onclick", "onerror", "javascript:", "https://", "<script", "<iframe"):
        assert forbidden not in html


def test_duplicate_toc_labels_and_repeated_text_keep_distinct_structural_positions(tmp_path):
    material = make_epub(
        tmp_path / "book.epub", ["<p>Repeated.</p>", "<p>Repeated.</p>"], ["Same", "Same"]
    )
    book = build_reader_book(material.epub_content, material.normalized_content)
    assert [section.label for section in book.sections] == ["Same", "Same"]
    assert book.sections[0].start_char != book.sections[1].start_char
    first, second = source_spans(book)[0], source_spans(book, "OPS/c1.xhtml")[0]
    assert first.text == second.text == "Repeated."
    assert first.attrib["data-source-start"] != second.attrib["data-source-start"]


def test_import_preserves_original_epub_after_move_and_restart(tmp_path):
    path = tmp_path / "original.epub"
    imported = make_epub(path, ["<p>Already read.</p>"])
    raw = path.read_bytes()
    database = tmp_path / "library.sqlite3"

    async def scenario():
        workbench = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(database))
        material = await workbench.store_imported_material(
            imported,
            source_language=LanguageEnum.ENGLISH,
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1,
        )
        path.unlink()
        assert load_epub_asset(workbench.source_asset_directory, material.content, str(path)) == raw
        await workbench.aclose()
        restored = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(database))
        material = restored.get_material(material.id)
        book = build_reader_book(
            load_epub_asset(
                restored.source_asset_directory, material.content, material.source_path
            ),
            material.content,
        )
        assert source_spans(book)[0].text == "Already read."
        await restored.aclose()

    asyncio.run(scenario())
