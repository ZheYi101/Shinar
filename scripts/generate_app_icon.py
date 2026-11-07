"""Render the original SVG into deterministic PNG and multi-size Windows ICO assets."""

from __future__ import annotations

import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def render_icon(source: Path, size: int) -> bytes:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG: {source}")
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(0)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not canvas.save(buffer, "PNG"):
        raise RuntimeError("PNG encoding failed")
    return bytes(data)


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    root = Path(__file__).resolve().parents[1] / "src/lingualoop/desktop/assets"
    source = root / "app-icon.svg"
    root.joinpath("app-icon.png").write_bytes(render_icon(source, 512))
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    payloads = [render_icon(source, size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, payload in zip(sizes, payloads, strict=True):
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset)
        )
        offset += len(payload)
    root.joinpath("app-icon.ico").write_bytes(header + b"".join(entries + payloads))
    print(f"Generated PNG and {len(sizes)} ICO sizes in {root}")
    del app


if __name__ == "__main__":
    main()
