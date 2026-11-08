"""Render deterministic demo data; never loads .env or the user's database."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["SHINAR_KIRIGAMI_MODE"] = "off"

from PySide6.QtCore import QObject, QEventLoop, QSettings, QTimer
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickWindow  # Registers the concrete window wrapper.

from shinar.application import LearningWorkbench
from shinar.core import LanguageEnum, ProficiencyLevel
from shinar.desktop.app import create_engine
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider


class PreviewProvider(MockLearningLLMProvider):
    async def stream_reply(self, **kwargs):
        reply = await self.generate_reply(**kwargs)
        for position in range(0, len(reply), 8):
            yield reply[position:position + 8]
            await asyncio.sleep(0.12)


def main():
    app = QGuiApplication([])
    if os.name == "nt":
        for name in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    output = Path("build/ui-preview")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        work = LearningWorkbench(PreviewProvider(), event_store=SQLiteStore(Path(directory) / "demo.sqlite3"))

        async def seed():
            await work.load_material(title="放課後の小さな約束", source_language=LanguageEnum.JAPANESE,
                target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE,
                learner_level=ProficiencyLevel.B1,
                content="放課後、二人はいつもの喫茶店で会った。春香は遠い町に引っ越すことを迷っている。蓮は「離れていても、友達でいられるよ」と言った。")
            await work.start_session()
            await work.send_message("離れていても、友達でいられると思います。私も同じような経験があります。")

        asyncio.run(seed())
        prefs = DesktopPreferences(QSettings(str(Path(directory) / "preferences.ini"), QSettings.Format.IniFormat))
        vm = LearningViewModel(work, "Mock 调试", preferences=prefs)
        engine = create_engine(vm, window_settings=QSettings(str(Path(directory) / "window.ini"), QSettings.Format.IniFormat))
        window = engine.rootObjects()[0]
        scaffold = next(item for item in window.findChildren(QObject) if item.metaObject().indexOfProperty("currentPage") >= 0)
        try:
            for name, page, width, height, theme in [
                ("desktop-light", 1, 1440, 960, "light"), ("desktop-dark", 1, 1440, 960, "dark"),
                ("materials", 0, 1180, 900, "light"), ("narrow", 1, 800, 780, "light"),
                ("material-topics", 0, 1180, 900, "light"), ("material-compact", 0, 360, 800, "light"),
                ("compact", 1, 360, 800, "light"), ("compact-short", 1, 360, 560, "light"),
                ("streaming", 1, 1180, 900, "light"),
                ("review", 2, 1180, 900, "light"), ("settings-light", 3, 1180, 900, "light"),
                ("settings-dark", 3, 800, 900, "dark"),
            ]:
                if page == 2 and vm.sessionActive:
                    vm.finishPractice()
                    loop = QEventLoop()
                    QTimer.singleShot(250, loop.quit)
                    loop.exec()
                    assert not vm.busy and not vm.sessionActive
                prefs.setValue("themeMode", theme)
                window.setProperty("width", width)
                window.setProperty("height", height)
                scaffold.setProperty("currentPage", page)
                scroll = window.findChild(QObject, "materialScroll")
                flick = scroll.property("contentItem")
                flick.setProperty("contentY", 480 if name == "material-topics" else 0)
                if name == "streaming":
                    vm.draft = "物語の中で、友達の気持ちを尊重することが大切だと思います。"
                    vm.sendMessage(vm.draft)
                    while not vm.streamingText and vm.busy:
                        loop = QEventLoop()
                        QTimer.singleShot(20, loop.quit)
                        loop.exec()
                loop = QEventLoop()
                QTimer.singleShot(250, loop.quit)
                loop.exec()
                assert window.grabWindow().save(str(output / (name + ".png")))
                print(f"Rendered {name}: {width}x{height}")
                if name == "streaming":
                    while vm.busy:
                        loop = QEventLoop()
                        QTimer.singleShot(50, loop.quit)
                        loop.exec()
        finally:
            vm.close()
            window.close()
            engine.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    main()
