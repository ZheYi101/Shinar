from __future__ import annotations

import pytest

from shinar.infrastructure.material_import import import_material_file, normalize_material


def test_markdown_import_preserves_raw_and_normalizes_text(tmp_path) -> None:
    path = tmp_path / "market-note.md"
    path.write_text(
        "---\ntitle: Hidden\n---\n# Market Note\n\nI [went](https://example.com) to the market.\n",
        encoding="utf-8",
    )

    imported = import_material_file(path)

    assert imported.title == "market note"
    assert "title: Hidden" in imported.raw_content
    assert "Market Note" in imported.normalized_content
    assert "https://example.com" not in imported.normalized_content
    assert imported.diagnostics


def test_docx_import_extracts_paragraphs_and_tables(tmp_path) -> None:
    docx = pytest.importorskip("docx")
    path = tmp_path / "lesson.docx"
    document = docx.Document()
    document.add_paragraph("Yesterday I went to the market.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "chunk"
    table.rows[0].cells[1].text = "go shopping"
    document.save(path)

    imported = import_material_file(path)

    assert "Yesterday I went" in imported.normalized_content
    assert "chunk | go shopping" in imported.normalized_content


def test_unsupported_import_extension_fails_without_normalizing(tmp_path) -> None:
    path = tmp_path / "lesson.pdf"
    path.write_text("not supported", encoding="utf-8")

    with pytest.raises(ValueError, match="Supported materials"):
        import_material_file(path)


def test_normalize_material_removes_markdown_noise() -> None:
    normalized, diagnostics = normalize_material("# Title\n\n```\nKeep this sentence.\n```", ".md")

    assert normalized == "Title\n\nKeep this sentence."
    assert diagnostics
