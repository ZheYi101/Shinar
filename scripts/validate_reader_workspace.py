"""Exercise the shipped reader in an isolated Mock workspace and capture its window.

On Windows this opens a separate visible test window. User settings, books, speech
devices and configured AI providers are not used. Offscreen checks prove DOM and
controller behavior only; WebEngine capture requires a native window on this host.
"""

from __future__ import annotations

import argparse
import asyncio
from inspect import isawaitable
import hashlib
from html import escape
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import traceback
from zipfile import ZipFile

os.environ["RUN_REAL_AI_TESTS"] = "0"

SAMPLES = {
    "english": (
        "The afternoon train",
        [
            "The station was almost empty when Mira arrived. A single suitcase stood beside the bench, and a folded letter rested on top of it.",
            "Her brother brought two cups of tea. She had planned to explain everything before the train arrived, but now the quiet between them seemed more useful.",
            "At the far end of the platform, someone laughed.",
            "Mira unfolded the letter. Its last line had bothered her all morning: return when you are ready. It did not say where to return, or whether anyone would still be waiting.",
            "Her brother moved the suitcase into the shade and sat beside her. They spoke about the weather, the garden, and a small dog that had learned to open the kitchen door.",
            "When the announcement finally sounded, she found that she no longer wanted to hurry.",
        ],
    ),
    "chinese": (
        "午后的车站",
        [
            "林走进车站时，站台上几乎没有人。长椅旁放着一只旧旅行箱，箱子上压着一封折好的信。窗外的树影落在地上，随着风缓缓移动。",
            "“你比我想的来得早。”哥哥端着两杯茶走过来。他走得很慢，仿佛这趟旅行的成败，全在于不要把茶洒出来。",
            "她原本打算在列车到站前，把所有事情解释清楚。可是当他真的站在面前，那些准备好的话却忽然失去了分量。她接过茶，看着热气飘向敞开的窗。",
            "站台尽头传来一阵笑声。",
            "她又展开那封信。最后一行只有一句：等你准备好，就回来。信里没有说该回到哪里，也没有说，是否还会有人等她。",
            "哥哥没有问信上写了什么。他把旅行箱移到阴凉处，在她身边坐下。他们聊起天气、院子，还有那只最近学会自己开厨房门的小狗。",
        ],
    ),
    "japanese": (
        "午後の駅",
        [
            "美良が駅に着いたとき、ホームにはほとんど誰もいなかった。ベンチのそばに古い旅行かばんが一つ置かれ、その上に折りたたまれた手紙があった。",
            "「思ったより早かったね」と兄が言った。両手にお茶のカップを持ち、一滴もこぼさないように、ゆっくり歩いてきた。",
            "列車が来る前に、すべてを説明するつもりだった。けれど、兄が目の前に立つと、用意していた言葉よりも、二人の間に流れる静けさのほうが大切に思えた。",
            "ホームの向こうで、誰かが笑った。",
            "美良はもう一度、手紙を開いた。最後の一行には「準備ができたら、帰っておいで」とだけ書いてあった。どこへ帰るのか、誰が待っているのかは書かれていなかった。",
            "兄は何も聞かなかった。ただ、かばんを日陰へ移し、隣に腰を下ろした。二人は天気や庭のこと、それから小さな犬の話をした。",
        ],
    ),
}


def write_book(path: Path, language: str) -> None:
    title, paragraphs = SAMPLES[language]
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "book.opf",
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:language>en</dc:language><dc:identifier id="id">reader-{language}</dc:identifier></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>',
        )
        for name, heading, texts in (
            ("one", title, paragraphs + ["Unicode: 中文、日本語、café、🌱."]),
            ("two", "Second chapter", ["UNREAD_MARKER", "A different event happens later."]),
        ):
            body = "".join(f"<p>{escape(text)}</p>" for text in texts)
            archive.writestr(
                name + ".xhtml",
                f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head><body><h1>{heading}</h1>{body}</body></html>',
            )
        archive.writestr(
            "nav.xhtml",
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol><li><a href="one.xhtml">{title}</a></li><li><a href="two.xhtml">Second chapter</a></li></ol></nav></body></html>',
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/reader-workspace"))
    parser.add_argument("--platform", default="windows" if os.name == "nt" else "offscreen")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = dict(
        platform=args.platform,
        real_ai_calls=0,
        synthetic_materials=True,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    (output / "report.json").write_text(
        json.dumps(dict(metadata, status="running")), encoding="utf-8"
    )
    os.environ["QT_QPA_PLATFORM"] = args.platform
    os.environ.pop("QT_QUICK_BACKEND", None)

    from shinar.desktop.app import _load_qt, create_engine

    _load_qt()
    from PySide6.QtCore import QSettings, QUrl, QMetaObject, Q_ARG, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QFontDatabase
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QTimer
    from shiboken6 import isValid
    from shinar.application import LearningWorkbench
    from shinar.desktop.preferences import DesktopPreferences
    from shinar.desktop.viewmodel import LearningViewModel
    from shinar.infrastructure import SQLiteStore
    from shinar.providers import MockLearningLLMProvider

    app = QGuiApplication([])
    if os.name == "nt":
        for name in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc"):
            QFontDatabase.addApplicationFont(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name)
            )
    with TemporaryDirectory(prefix="shinar-reader-validation-") as temporary:
        root = Path(temporary)
        prefs = DesktopPreferences(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
        prefs.setValue("autoSpeak", False)
        prefs.setValue("reducedMotion", True)
        wb = LearningWorkbench(
            MockLearningLLMProvider(), event_store=SQLiteStore(root / "library.sqlite3")
        )
        vm = LearningViewModel(wb, "Mock", preferences=prefs)
        engine = create_engine(
            vm, window_settings=QSettings(str(root / "window.ini"), QSettings.IniFormat)
        )
        window, ws = engine.rootObjects()[0], engine.workspace
        window.setPosition(20, 20)
        window.showNormal()
        window.raise_()
        window.requestActivate()
        print("Native window exposed:", QTest.qWaitForWindowExposed(window, 5000), flush=True)
        assert QTest.qWaitForWindowActive(window, 5000), "native test window must be active"
        helper_component = QQmlComponent(engine)
        helper_component.setData(
            b'import QtQuick\nQtObject { property var target; property string result: ""; property int sequence: 0; function evaluate(script) { const request = ++sequence; target.runJavaScript(script, value => { if (request === sequence) result=JSON.stringify(value) }) } }',
            QUrl(),
        )
        helper = helper_component.create()
        results = []

        async def until(condition, timeout=20):
            deadline = monotonic() + timeout
            while monotonic() < deadline:
                pending = [window.contentItem()]
                while pending:
                    item = pending.pop()
                    item.ensurePolished()
                    pending.extend(item.childItems())
                value = condition()
                if isawaitable(value):
                    value = await value
                if value:
                    return
                await asyncio.sleep(0.02)
            window.grabWindow().save(str(output / "failed-state.png"))
            raise AssertionError(("timeout", ws.readerError, ws.error))

        def find(name):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if (
                    item.objectName() == name
                    and item.isVisible()
                    and item.width() > 0
                    and item.height() > 0
                ):
                    return item
                pending.extend(item.childItems())
            return None

        async def evaluate(script):
            helper.setProperty("target", find("foliateReader"))
            helper.setProperty("result", "")
            deadline = monotonic() + 5
            while not helper.property("result") and monotonic() < deadline:
                QMetaObject.invokeMethod(helper, "evaluate", Q_ARG("QVariant", script))
                await asyncio.sleep(0.08)
            assert helper.property("result"), "reader JavaScript did not answer"
            return json.loads(helper.property("result"))

        async def ready():
            await until(lambda: ws.documentReady and find("foliateReader") is not None)
            await until(
                lambda: (
                    find("foliateReader") is not None
                    and find("foliateReader").property("documentIdentity") == ws.readerId
                    and bool(find("foliateReader").property("bookReady"))
                )
            )
            assert await evaluate("!!window.shinarReader.ready")
            await asyncio.sleep(0.25)

        def click(name):
            target = find(name)
            assert target is not None, name
            QTest.mouseClick(
                window,
                Qt.LeftButton,
                Qt.NoModifier,
                target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint(),
            )
            QTest.mouseMove(window, QPointF(10, 50).toPoint())

        async def capture(name):
            window.update()
            QTest.mouseMove(window, QPointF(10, 50).toPoint())
            await asyncio.sleep(0.4)
            ink = await evaluate(
                "window.shinarReader.view.renderer.getContents()[0].doc.defaultView.getComputedStyle(window.shinarReader.view.renderer.getContents()[0].doc.body).color.match(/[0-9]+/g).slice(0,3).map(Number)"
            )
            surface = find("foliateReader")
            origin = surface.mapToScene(QPointF(0, 0))
            for _ in range(8):
                assert window.isActive(), (
                    "refusing to capture another application's foreground window"
                )
                picture = window.grabWindow()
                scale = picture.width() / window.width()
                x0, y0 = int((origin.x() + 20) * scale), int((origin.y() + 20) * scale)
                x1 = min(picture.width(), int((origin.x() + surface.width() - 20) * scale))
                y1 = min(picture.height(), int((origin.y() + surface.height() - 20) * scale))
                ink_samples = 0
                for y in range(y0, y1, 6):
                    for x in range(x0, x1, 6):
                        color = picture.pixelColor(x, y)
                        if (
                            abs(color.red() - ink[0])
                            + abs(color.green() - ink[1])
                            + abs(color.blue() - ink[2])
                            < 20
                        ):
                            ink_samples += 1
                if ink_samples > 30:
                    break
                await asyncio.sleep(0.25)
            assert not picture.isNull() and picture.save(str(output / (name + ".png")))
            assert ink_samples > 30, (name, "reader pixels are blank", ink_samples)
            return ink_samples

        async def run_checks():
            try:
                window.setWidth(1600)
                window.setHeight(950)
                for language in SAMPLES:
                    path = root / (language + ".epub")
                    write_book(path, language)
                    ws.navigate("import")
                    ws.setImportMode("file")
                    ws.importLanguage = language
                    ws.inspectFile(str(path))
                    await until(lambda: not ws.inspecting)
                    ws.commitImport()
                    await until(lambda: not vm.busy and ws.route == "scope")
                    await ready()
                    # Select an exact last sentence; pending does not change persisted scope.
                    ws.locateSentence("Unicode: 中文、日本語、café、🌱.")
                    await until(lambda: ws.pendingEnd > 0)
                    assert not ws.material["confirmed"]
                    await asyncio.sleep(150 / 1000)
                    if language == "english":
                        assert await evaluate(
                            "!!window.shinarReader.view.renderer.getContents()[0].doc.querySelector('[data-reader-ui]')"
                        )
                        await capture("scope-boundary")
                    click("saveScopeButton")
                    await until(lambda: not vm.busy and ws.route == "material")
                    material_id = ws.browsingMaterialId
                    path.unlink()  # Rendering must now depend on the managed copy.
                    ws.newThreadPage()
                    ws.startThread()
                    await until(lambda: not vm.busy and ws.route == "chat")
                    ws.toggleSource()
                    await ready()
                    assert wb.session.material_id == material_id
                    assert len(ws.sections) == 1
                    state = await evaluate(
                        "({text:window.shinarReader.view.renderer.getContents()[0].doc.body.textContent,private:typeof qt.webChannelTransport==='object'})"
                    )
                    assert "UNREAD_MARKER" not in state["text"]

                    if language == "english":
                        handle = find("sourceSplitHandle")
                        await until(lambda: find("sourceSplitHandle") is not None)
                        handle = find("sourceSplitHandle")
                        prior_width = find("foliateReader").width()
                        grip = handle.mapToScene(
                            QPointF(handle.width() / 2, handle.height() / 2)
                        ).toPoint()
                        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, grip)
                        await asyncio.sleep(50 / 1000)
                        assert find("sourceSplitMouse").property("pressed"), (
                            "split handle did not receive the press"
                        )
                        QTest.mouseMove(window, grip + QPointF(90, 0).toPoint(), 90)
                        QTest.mouseRelease(
                            window, Qt.LeftButton, Qt.NoModifier, grip + QPointF(90, 0).toPoint()
                        )
                        await until(lambda: find("foliateReader").width() > prior_width + 40)
                        await asyncio.sleep(200 / 1000)
                        QTest.keyClick(window, Qt.Key_F, Qt.ControlModifier)
                        await until(lambda: find("sourceSearchInput") is not None)
                        click("sourceSearchInput")
                        QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
                        QGuiApplication.clipboard().setText("letter")
                        QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
                        await until(lambda: find("sourceSearchInput").property("text") == "letter")
                        await until(lambda: len(ws.searchResults) > 0)
                        QTest.keyClick(window, Qt.Key_Escape)
                        await until(lambda: find("sourceSearchInput") is None)
                        hit = ws.searchResults[0]
                        ws.showSearchResult(hit["start"], hit["end"])

                        async def search_selected():
                            return (
                                await evaluate(
                                    "window.shinarReader.view.renderer.getContents()[0].doc.defaultView.getSelection().toString()"
                                )
                                == "letter"
                            )

                        await until(search_selected)
                        results.append(dict(check="split_resize_and_search", passed=True))
                        # Real mouse drag, native clipboard, keyboard extension, then UI send.
                        coords = await evaluate(
                            "(() => {const r=window.shinarReader;const c=r.view.renderer.getContents()[0];const s=c.doc.querySelector('p [data-source-start]');const a=Number(s.dataset.sourceStart);const x=r.mappedRange(c.doc,a,a+11).getBoundingClientRect();const f=c.doc.defaultView.frameElement.getBoundingClientRect();return {x:x.x+f.x,y:x.y+f.y,w:x.width,h:x.height}})()"
                        )
                        surface = find("foliateReader")
                        point = lambda x: surface.mapToScene(
                            QPointF(x, coords["y"] + coords["h"] / 2)
                        ).toPoint()
                        QTest.mousePress(
                            window, Qt.LeftButton, Qt.NoModifier, point(coords["x"] + 1)
                        )
                        QTest.mouseMove(window, point(coords["x"] + coords["w"] - 1), 90)
                        QTest.mouseRelease(
                            window,
                            Qt.LeftButton,
                            Qt.NoModifier,
                            point(coords["x"] + coords["w"] - 1),
                        )
                        await until(
                            lambda: ws.snapshot() is not None and ws.snapshot().focus_kind == "text"
                        )
                        selected = ws.snapshot()
                        QTest.keyClick(window, Qt.Key_C, Qt.ControlModifier)
                        await until(lambda: QGuiApplication.clipboard().text() == selected.quote)
                        QTest.keyClick(window, Qt.Key_Left, Qt.ShiftModifier)
                        await asyncio.sleep(80 / 1000)
                        assert ws.snapshot().focus_kind == "text"
                        # Explicit Element-endpoint Range matches the paragraph's canonical span.
                        assert await evaluate(
                            "(() => {const r=window.shinarReader,c=r.view.renderer.getContents()[0],p=c.doc.querySelector('p'),x=c.doc.createRange();x.selectNodeContents(p);const s=p.querySelectorAll('[data-source-start]');return JSON.stringify(r.sourceSelection(x))===JSON.stringify([Number(s[0].dataset.sourceStart),Number(s[s.length-1].dataset.sourceEnd)])})()"
                        )
                        before = ws.snapshot()
                        click("messageInput")
                        QGuiApplication.clipboard().setText("What changed in her decision?")
                        QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
                        click("sendMessageButton")
                        await until(lambda: not vm.busy and len(vm.messages) == 3)
                        assert vm.messages[1]["source"]["quote"] == before.quote
                        ws.previewMessage(vm.messages[1]["id"])
                        await ready()
                        assert ws.historicalSource and ws.snapshot() == before
                        ws.closePreview()
                        await ready()
                        results.append(dict(check="mouse_copy_keyboard_send_history", passed=True))

                    for theme, width in (("light", 1600), ("dark", 680)):
                        prefs.setValue("themeMode", theme)
                        window.setWidth(width)
                        await ready()
                        metrics = await evaluate(
                            "(() => {const d=window.shinarReader.view.renderer.getContents()[0].doc;const family=d.defaultView.getComputedStyle(d.body).fontFamily;return {overflow:d.documentElement.scrollWidth>d.documentElement.clientWidth+2,font:family,fontLoaded:d.fonts.check('20px '+family),background:d.defaultView.getComputedStyle(d.documentElement).backgroundColor}})()"
                        )
                        assert not metrics["overflow"]
                        assert metrics["fontLoaded"]
                        if language == "chinese":
                            assert "ShinarSC" in metrics["font"]
                        elif language == "japanese":
                            assert "ShinarJP" in metrics["font"]
                        metrics["inkSamples"] = await capture(language + "-" + theme)
                        results.append(
                            dict(check=language + "-" + theme, width=width, **metrics, passed=True)
                        )
                    window.setWidth(1600)
                    prefs.setValue("themeMode", "light")
                    ws.toggleSource()
                assert engine.reader_runtime.profile.isOffTheRecord()
                results.append(dict(check="private_offline_profile", passed=True))
            finally:
                vm.close()
                ws.close()
                window.close()
                engine.deleteLater()
                app.processEvents()
            report = dict(metadata, status="passed", checks=results)
            (output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=True, indent=2))

        errors = []

        async def exercise():
            try:
                await run_checks()
            except BaseException as error:
                errors.append(error)
                traceback.print_exc()
                (output / "report.json").write_text(
                    json.dumps(
                        dict(metadata, status="failed", error=type(error).__name__, detail=str(error), checks=results),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            finally:
                app.quit()

        ui_loop = asyncio.new_event_loop()
        task = ui_loop.create_task(exercise())

        def pump():
            if isValid(window):
                window.update()
            ui_loop.call_soon(ui_loop.stop)
            ui_loop.run_forever()
            if task.done():
                timer.stop()
                app.exit(0)

        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(pump)
        timer.start()
        app.exec()
        timer.stop()
        if not task.done():
            task.cancel()
            ui_loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        ui_loop.close()
        if errors:
            raise errors[0]


if __name__ == "__main__":
    main()
