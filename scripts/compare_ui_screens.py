"""Compose design/before/after screenshots without changing their aspect ratio."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter


PAIRS = (
    ("appearance", "13-settings-appearance", "settings-appearance"),
    ("learning", "14-settings-learning", "settings-learning"),
    ("new", "05-new", "new"),
    ("chat", "06-chat", "chat"),
    ("source", "07-paragraph", "source"),
    ("import", "03-import", "import"),
    ("material", "02-material", "material"),
    ("scope", "04-scope", "scope"),
)


def panel(path: Path, width: int, height: int, label: str) -> QImage:
    source = QImage(str(path))
    if source.isNull():
        raise SystemExit(f"Missing screenshot: {path}")
    result = QImage(width, height + 32, QImage.Format.Format_RGB32)
    result.fill(QColor("#F7F3E9"))
    painter = QPainter(result)
    painter.setFont(QFont("Microsoft YaHei UI", 11))
    painter.setPen(QColor("#3F382F"))
    painter.drawText(12, 22, f"{label} · {source.width()} × {source.height()}")
    scaled = source.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawImage(0, 32, scaled)
    painter.end()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before", type=Path, default=Path("build/ui-plan-audit/visible-100-final")
    )
    parser.add_argument("--after", type=Path, default=Path("build/ui-visual-review/final"))
    parser.add_argument("--output", type=Path, default=Path("build/ui-visual-review/comparison"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    if os.name == "nt":
        QFontDatabase.addApplicationFont(
            str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc")
        )
    reference = Path(__file__).resolve().parents[1] / "docs/product/assets/ui-layout-v1/screens"
    overview = QImage(1800, len(PAIRS) * 432, QImage.Format.Format_RGB32)
    overview.fill(QColor("#D9CEBD"))
    overview_painter = QPainter(overview)
    html = [
        "<!doctype html><meta charset='utf-8'><title>QML visual comparison</title>",
        "<style>body{background:#f7f3e9;color:#3f382f;font:15px sans-serif;margin:24px}img{width:100%;height:auto}section{margin-bottom:36px}a{color:#56634f}</style>",
        "<h1>设计稿 / 修正前 / 修正后</h1><p>保持各图原始比例；内容和窗口高度不同，不使用像素相似度冒充审美评分。</p>",
    ]
    for index, (name, target, current) in enumerate(PAIRS):
        sources = (
            reference / f"{target}.png",
            args.before / f"1440-{current}.png",
            args.after / f"1440-{current}.png",
        )
        result = QImage(2880, 672, QImage.Format.Format_RGB32)
        result.fill(QColor("#D9CEBD"))
        painter = QPainter(result)
        for column, (path, label) in enumerate(zip(sources, ("设计稿", "修正前", "修正后"))):
            painter.drawImage(column * 960, 0, panel(path, 960, 640, label))
            overview_painter.drawImage(column * 600, index * 432, panel(path, 600, 400, label))
        painter.end()
        result.save(str(args.output / f"{name}.png"))
        html.append(
            f"<section><h2>{name}</h2><a href='{name}.png'><img src='{name}.png'></a></section>"
        )
    overview_painter.end()
    overview.save(str(args.output / "overview.png"))
    (args.output / "index.html").write_text("\n".join(html), encoding="utf-8")
    print(f"Wrote {len(PAIRS)} comparison sheets to {args.output}")
    app.quit()


if __name__ == "__main__":
    main()
