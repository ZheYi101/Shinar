"""EPUB display assets mapped to the unchanged, normalized source character ranges.

Publisher markup is reduced to static semantic HTML. Foliate owns EPUB loading,
navigation and layout; this adapter owns the application's source coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path
from posixpath import dirname, join, normpath
import re
from tempfile import NamedTemporaryFile
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from lingualoop.core.knowledge import SourceSection
from lingualoop.infrastructure.material_import import ReadableHTML, normalize_material

MAX_EPUB_BYTES = 60 * 1024 * 1024
MAX_EXPANDED_BYTES = 120 * 1024 * 1024
DISPLAY_VERSION = "epub-display-v1"
_TAGS = {
    "p",
    "div",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ul",
    "ol",
    "blockquote",
    "em",
    "strong",
    "b",
    "i",
    "u",
    "s",
    "small",
    "span",
    "a",
    "img",
    "ruby",
    "rt",
    "rp",
    "sub",
    "sup",
    "hr",
    "section",
    "article",
    "aside",
    "figure",
    "figcaption",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "pre",
    "code",
}
_VOID = {"br", "hr", "img"}
_ATTRIBUTES = {"id", "name", "href", "src", "alt", "title", "lang", "dir", "colspan", "rowspan"}


def _local_url(value: str) -> bool:
    parsed = urlsplit(value.strip())
    return not parsed.scheme and not parsed.netloc and not value.startswith(("/", "\\"))


def _normalized_parts(parts: list[str]) -> tuple[str, dict[int, tuple[int, int]]]:
    """Apply exactly normalize_material(..., '.epub'), retaining each data token's origin."""
    text = "".join(parts)
    origins = [index for index, part in enumerate(parts) for _ in part]

    def replace(pattern: str, replacement: str) -> None:
        nonlocal text, origins
        output, mapped, cursor = [], [], 0
        for match in re.finditer(pattern, text):
            output.extend((text[cursor : match.start()], replacement))
            mapped.extend(origins[cursor : match.start()])
            mapped.extend(origins[match.start() : match.start() + len(replacement)])
            cursor = match.end()
        output.append(text[cursor:])
        mapped.extend(origins[cursor:])
        text, origins = "".join(output), mapped

    replace(r"\r\n|\r", "\n")
    replace(r"[ \t]+", " ")
    replace(r"\n{3,}", "\n\n")
    output, mapped, cursor = [], [], 0
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        clean = line.strip()
        left = len(line) - len(line.lstrip())
        output.append(clean)
        mapped.extend(origins[cursor + left : cursor + left + len(clean)])
        if index < len(lines) - 1:
            output.append("\n")
            mapped.append(origins[cursor + len(line) - 1])
        cursor += len(line)
    text = "".join(output)
    left = len(text) - len(text.lstrip())
    stripped = text.strip()
    mapped = mapped[left : left + len(stripped)]
    ranges: dict[int, tuple[int, int]] = {}
    for offset, origin in enumerate(mapped):
        previous = ranges.get(origin)
        ranges[origin] = (previous[0] if previous else offset, offset + 1)
    expected, _ = normalize_material("".join(parts), ".epub")
    if stripped != expected:
        raise ValueError("EPUB normalization mapping mismatch")
    return stripped, ranges


class _MappedHTML(ReadableHTML):
    def __init__(self) -> None:
        super().__init__()
        self.output: list[str | int | tuple[str, int, bool]] = []
        self.body_depth = 0
        self.blocked = 0
        self.anchors: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.body_depth += 1
        if tag in {"script", "style", "iframe", "object", "embed", "form", "template", "svg"}:
            self.blocked += 1
        super().handle_starttag(tag, attrs)
        for key, value in attrs:
            if key in {"id", "name"} and value:
                self.anchors[value] = len(self.parts)
        if not self.body_depth or self.blocked or tag not in _TAGS:
            return
        safe = []
        for key, value in attrs:
            if key not in _ATTRIBUTES or value is None:
                continue
            if key in {"href", "src"} and not _local_url(value):
                continue
            safe.append(f' {key}="{escape(value, quote=True)}"')
        image_attribute = ' data-source-image=""' if tag == "img" else ""
        markup = f"<{tag}{''.join(safe)}{image_attribute}{' /' if tag in _VOID else ''}>"
        self.output.append((markup, len(self.parts), True) if tag == "img" else markup)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.body_depth and not self.blocked and tag in _TAGS and tag not in _VOID:
            self.output.append(f"</{tag}>")
        super().handle_endtag(tag)
        if tag in {"script", "style", "iframe", "object", "embed", "form", "template", "svg"}:
            self.blocked = max(0, self.blocked - 1)
        if tag == "body":
            self.body_depth = max(0, self.body_depth - 1)

    def handle_data(self, data: str) -> None:
        token = len(self.parts)
        if self.body_depth and not self.blocked and not self.hidden:
            self.output.append(token)
        # Ruby annotations retain their semantics but have no source coordinates.
        elif self.body_depth and not self.blocked and self.hidden:
            self.output.append((escape(data), len(self.parts) - 1, False))
        super().handle_data(data)

    def render(
        self, text: str, ranges: dict[int, tuple[int, int]], offset: int, start: int, end: int
    ) -> str:
        output = []
        for part in self.output:
            if isinstance(part, tuple):
                markup, token, forward = part
                candidates = [
                    (index, a, b)
                    for index, (a, b) in ranges.items()
                    if (index >= token if forward else index <= token)
                ]
                if candidates:
                    _, a, b = candidates[0] if forward else candidates[-1]
                    if start <= offset + a and offset + b <= end:
                        output.append(markup)
                continue
            if isinstance(part, str):
                output.append(part)
                continue
            if part not in ranges:
                continue
            a, b = ranges[part]
            a, b = max(a, start - offset), min(b, end - offset)
            if a < b:
                output.append(
                    f'<span data-source-start="{offset + a}" data-source-end="{offset + b}">'
                    f"{escape(text[a:b])}</span>"
                )
        # Empty publisher paragraphs and front matter should not create blank pages.
        body = "".join(output)
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title></title></head>'
            f"<body>{body}</body></html>"
        )


@dataclass(frozen=True)
class ReaderBook:
    data: bytes
    sections: list[SourceSection]
    chapters: list[dict[str, str | int]]


def save_epub_asset(directory: Path, data: bytes, content: str) -> Path:
    """Atomically preserve an inspected EPUB snapshot, without paths or keys in its name."""
    if len(data) > MAX_EPUB_BYTES:
        raise ValueError("EPUB exceeds the source asset limit")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sha256(content.encode()).hexdigest() + ".epub")
    if path.is_file() and path.read_bytes() == data:
        return path
    temporary = None
    try:
        with NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def load_epub_asset(directory: Path | None, content: str, source_path: str | None) -> bytes | None:
    if directory is not None:
        path = directory / (sha256(content.encode()).hexdigest() + ".epub")
        if path.is_file() and path.stat().st_size <= MAX_EPUB_BYTES:
            return path.read_bytes()
    # Legacy libraries can build a verified display without rewriting their material/history.
    if source_path and Path(source_path).suffix.lower() == ".epub":
        path = Path(source_path)
        if path.is_file() and path.stat().st_size <= MAX_EPUB_BYTES:
            return path.read_bytes()
    return None


def build_reader_book(
    data: bytes, content: str, start: int = 0, end: int | None = None
) -> ReaderBook:
    """Reject any EPUB that does not reproduce the saved canonical text exactly."""
    end = len(content) if end is None else end
    if not 0 <= start < end <= len(content) or len(data) > MAX_EPUB_BYTES:
        raise ValueError("Invalid EPUB display range")
    with ZipFile(BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
            raise ValueError("Expanded EPUB exceeds the source asset limit")
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            e.attrib["full-path"] for e in container.iter() if e.tag.endswith("rootfile")
        )
        package = ET.fromstring(archive.read(rootfile))
        if any(
            element.attrib.get("property") == "rendition:layout"
            and (element.text or "").strip() == "pre-paginated"
            for element in package.iter()
        ):
            raise ValueError("Fixed-layout EPUB requires the text fallback")
        manifest = {e.attrib.get("id"): e.attrib for e in package.iter() if e.tag.endswith("}item")}
        spine = [e.attrib.get("idref") for e in package.iter() if e.tag.endswith("itemref")]
        chapters, canonical, offset = {}, [], 0
        for identifier in spine:
            item = manifest.get(identifier)
            if not item or not item.get("href"):
                continue
            # Match the existing importer; do not silently change legacy normalization.
            member = normpath(join(dirname(rootfile), item["href"].split("#")[0]))
            parser = _MappedHTML()
            parser.feed(archive.read(member).decode("utf-8-sig"))
            text, ranges = _normalized_parts(parser.parts)
            if not text:
                continue
            if canonical:
                offset += 2
            chapters[member] = (parser, text, ranges, offset)
            canonical.append(text)
            offset += len(text)
        if "\n\n".join(canonical) != content:
            raise ValueError("EPUB does not match the saved source version")

        labels, navigation_path = _navigation_labels(archive, manifest, rootfile)
        sections = _reader_sections(labels, chapters, start, end)
        rendered = _render_projection(archive, chapters, navigation_path, start, end)
        visible_chapters = [
            dict(href=member, start=max(start, offset), end=min(end, offset + len(text)))
            for member, (parser, text, ranges, offset) in chapters.items()
            if offset < end
            and offset + len(text) > start
            and any(
                isinstance(token, int)
                and token in ranges
                and offset + ranges[token][0] < end
                and offset + ranges[token][1] > start
                and text[ranges[token][0] : ranges[token][1]].strip()
                for token in parser.output
            )
        ]
        if not visible_chapters:
            raise ValueError("EPUB has no mapped body text in this range")
        return ReaderBook(rendered.getvalue(), sections, visible_chapters)


def _navigation_labels(archive, manifest, rootfile):
    path = None
    # Resolve actual nav / NCX destinations to mapped source positions, including duplicates.
    labels: list[tuple[str, str, int]] = []
    nav = next(
        (item for item in manifest.values() if "nav" in item.get("properties", "").split()),
        None,
    )
    ncx = next(
        (
            item
            for item in manifest.values()
            if item.get("media-type") == "application/x-dtbncx+xml"
        ),
        None,
    )
    entry = nav or ncx
    if entry:
        path = normpath(join(dirname(rootfile), unquote(entry["href"].split("#")[0])))
        doc = ET.fromstring(archive.read(path))
        if nav:
            nodes = [
                node
                for node in doc.iter()
                if node.tag.endswith("}nav")
                and "toc" in node.attrib.get("{http://www.idpf.org/2007/ops}type", "").split()
            ]
            for node in nodes:
                for link in node.iter():
                    if link.tag.endswith("}a") and link.attrib.get("href"):
                        labels.append(
                            ("".join(link.itertext()).strip(), link.attrib["href"], 1)
                        )
        else:
            for point in doc.iter():
                if point.tag.endswith("}navPoint"):
                    label = next(
                        (
                            "".join(n.itertext()).strip()
                            for n in point
                            if n.tag.endswith("}navLabel")
                        ),
                        "",
                    )
                    target = next(
                        (n.attrib.get("src", "") for n in point if n.tag.endswith("}content")),
                        "",
                    )
                    labels.append((label, target, 1))
        labels = [
            (
                label,
                normpath(join(dirname(path), unquote(href.split("#")[0])))
                + ("#" + unquote(href.split("#", 1)[1]) if "#" in href else ""),
                level,
            )
            for label, href, level in labels
            if label and _local_url(href)
        ]
    return labels, path if nav else None


def _reader_sections(labels, chapters, start, end):
    sections = []
    for label, target, level in labels:
        member, _, fragment = target.partition("#")
        chapter = chapters.get(member)
        if chapter is None:
            continue
        parser, text, ranges, offset = chapter
        token = parser.anchors.get(fragment, 0) if fragment else 0
        local = next((a for index, (a, _) in ranges.items() if index >= token), 0)
        a = offset + local
        if start <= a < end and not any(s.start_char == a for s in sections):
            sections.append(
                SourceSection(
                    id=f"reader_{a}",
                    label=label,
                    level=level,
                    start_char=a,
                    end_char=min(end, offset + len(text)),
                )
            )
    if not sections:
        for parser, text, ranges, offset in chapters.values():
            if offset < end and offset + len(text) > start:
                label = next(
                    (title for title, _ in parser.headings if title), text.splitlines()[0]
                )
                sections.append(
                    SourceSection(
                        id=f"reader_{offset}",
                        label=label[:160],
                        level=1,
                        start_char=max(start, offset),
                        end_char=min(end, offset + len(text)),
                    )
                )
    sections.sort(key=lambda s: s.start_char)
    for index, section in enumerate(sections[:-1]):
        section.end_char = min(section.end_char, sections[index + 1].start_char)

    return sections


def _render_projection(archive, chapters, navigation_path, start, end):
    rendered = BytesIO()
    with ZipFile(rendered, "w", ZIP_DEFLATED) as output:
        for item in archive.infolist():
            if item.is_dir():
                continue
            chapter = chapters.get(item.filename)
            if chapter:
                parser, text, ranges, offset = chapter
                payload = parser.render(text, ranges, offset, start, end).encode()
            elif item.filename.lower().endswith((".xhtml", ".html", ".htm")) and not (
                item.filename == navigation_path
            ):
                # No unindexed HTML is allowed to bypass the source boundary via links.
                payload = b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title></title></head><body></body></html>'
            else:
                payload = archive.read(item)
            output.writestr(item.filename, payload)
    return rendered
