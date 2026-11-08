"""Synthetic input helpers shared across adapter regressions."""
from zipfile import ZipFile
from shinar.infrastructure.material_import import import_material_file

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
