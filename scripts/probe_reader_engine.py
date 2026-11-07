"""Probe Qt Quick / foliate-js with synthetic EPUBs, without the application or user data."""

from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
from threading import Thread
from time import monotonic
import zipfile

os.environ["RUN_REAL_AI_TESTS"] = "0"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickView
from PySide6.QtWebEngineQuick import QtWebEngineQuick

REPOSITORY = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--library", type=Path, default=REPOSITORY / "build/reader-evaluation/foliate-js"
)
parser.add_argument("--output", type=Path, default=REPOSITORY / "build/reader-evaluation")
args = parser.parse_args()
ROOT = args.output.resolve()
library = args.library.resolve()
if not (library / "view.js").is_file():
    parser.error("--library must point to an existing foliate-js checkout")
ROOT.mkdir(parents=True, exist_ok=True)
if library != ROOT / "foliate-js":
    shutil.copytree(
        library, ROOT / "foliate-js", dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
    )
FONT_ROOT = REPOSITORY / "src/lingualoop/desktop/qml/assets/fonts"
shutil.copytree(FONT_ROOT, ROOT / "fonts", dirs_exist_ok=True)
CHAPTERS = [
    (
        "en",
        "The afternoon train",
        [
            "The station was almost empty when Mira arrived. A single suitcase stood beside the bench, and a folded letter rested on top of it.",
            "“You came earlier than I expected,” her brother said. He was carrying two cups of tea, carefully, as if the journey depended on them.",
            "She had planned to explain everything before the train arrived. Now that he was here, the explanation seemed less useful than the quiet between them. She took a cup and watched the steam drift toward the open window.",
            "At the far end of the platform, someone laughed.",
            "Mira unfolded the letter. Its last line had bothered her all morning: return when you are ready. It did not say where to return, or whether anyone would still be waiting.",
            "Her brother did not ask what it said. Instead, he moved the suitcase into the shade and sat beside her. For a few minutes they spoke about the weather, the garden, and a small dog that had learned to open the kitchen door.",
            "When the announcement finally sounded, she found that she no longer wanted to hurry.",
        ],
    ),
    (
        "zh-CN",
        "午后的车站",
        [
            "林走进车站时，站台上几乎没有人。长椅旁放着一只旧旅行箱，箱子上压着一封折好的信。窗外的树影落在地上，随着风缓缓移动。",
            "“你比我想的来得早。”哥哥端着两杯茶走过来。他走得很慢，仿佛这趟旅行的成败，全在于不要把茶洒出来。",
            "她原本打算在列车到站前，把所有事情解释清楚。可是当他真的站在面前，那些准备好的话却忽然失去了分量。她接过茶，看着热气飘向敞开的窗。",
            "站台尽头传来一阵笑声。",
            "她又展开那封信。最后一行只有一句：等你准备好，就回来。信里没有说该回到哪里，也没有说，是否还会有人等她。",
            "哥哥没有问信上写了什么。他把旅行箱移到阴凉处，在她身边坐下。他们聊起天气、院子，还有那只最近学会自己开厨房门的小狗。",
            "广播终于响起时，她发现自己已经不再急着出发了。",
        ],
    ),
    (
        "ja",
        "午後の駅",
        [
            "美良が駅に着いたとき、ホームにはほとんど誰もいなかった。ベンチのそばに古い旅行かばんが一つ置かれ、その上に折りたたまれた手紙があった。",
            "「思ったより早かったね」と兄が言った。両手にお茶のカップを持ち、一滴もこぼさないように、ゆっくり歩いてきた。",
            "列車が来る前に、すべてを説明するつもりだった。けれど、兄が目の前に立つと、用意していた言葉よりも、二人の間に流れる静けさのほうが大切に思えた。",
            "ホームの向こうで、誰かが笑った。",
            "美良はもう一度、手紙を開いた。最後の一行には「準備ができたら、帰っておいで」とだけ書いてあった。どこへ帰るのか、誰が待っているのかは書かれていなかった。",
            "兄は何も聞かなかった。ただ、かばんを日陰へ移し、隣に腰を下ろした。二人は天気や庭のこと、それから台所の扉を開けるようになった小さな犬の話をした。",
            "やがてアナウンスが流れたとき、美良はもう急ぐ必要がないことに気づいた。",
        ],
    ),
]

with zipfile.ZipFile(ROOT / "sample.epub", "w") as archive:
    archive.writestr("mimetype", "application/epub+zip")
    archive.writestr(
        "META-INF/container.xml",
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
    )
    items = '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    spine = ""
    toc = ""
    for index, (language, title, paragraphs) in enumerate(CHAPTERS):
        name = f"chapter{index}.xhtml"
        items += f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>'
        spine += f'<itemref idref="c{index}"/>'
        toc += f'<li><a href="{name}">{title}</a></li>'
        body = "".join(f'<p id="p{n}">{paragraph}</p>' for n, paragraph in enumerate(paragraphs))
        archive.writestr(
            name,
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{language}"><head><title>{title}</title></head><body><h1>{title}</h1>{body}<p>Unicode check: café, 中文、日本語、🌱.</p></body></html>',
        )
    archive.writestr(
        "nav.xhtml",
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol>{toc}</ol></nav></body></html>',
    )
    archive.writestr(
        "book.opf",
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">lingualoop-synthetic-reader-probe</dc:identifier><dc:title>A letter at the station</dc:title><dc:language>en</dc:language></metadata><manifest>{items}</manifest><spine>{spine}</spine></package>',
    )

(ROOT / "index.html").write_text(
    """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self' blob: data:; connect-src 'self' blob:; frame-src blob:">
<style>html,body{margin:0;height:100%;background:#f8f5ed;color:#302d28;font-family:'Segoe UI',sans-serif}body{display:flex;flex-direction:column}header{height:56px;padding:0 24px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #dcd8ce;font-size:14px}header span{color:#77776c;margin-left:auto;font-size:12px}foliate-view{display:block;flex:1;min-height:0}footer{height:36px;padding:0 24px;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:#77776c}body.dark{background:#20231f;color:#e1e3d9}body.dark header{border-color:#41453c}body.dark header span,body.dark footer{color:#a9afa0}</style></head>
<body><header>A letter at the station <span>LinguaLoop · 阅读引擎技术小样</span></header><foliate-view></foliate-view><footer><span id="chapter"></span><span>合成材料 · foliate-js</span></footer><script type="module" src="probe.js"></script></body></html>""",
    encoding="utf-8",
)

(ROOT / "probe.js").write_text(
    """import './foliate-js/view.js'
const view = document.querySelector('foliate-view')
const params = new URLSearchParams(location.search)
const index = Number(params.get('chapter') || 0)
const dark = params.has('dark')
document.body.classList.toggle('dark', dark)
globalThis.probeError = null
addEventListener('error', event => globalThis.probeError = event.message)
addEventListener('unhandledrejection', event => globalThis.probeError = String(event.reason))
try {
 await view.open('sample.epub')
 view.renderer.setAttribute('flow', 'scrolled')
 view.renderer.setAttribute('max-inline-size', '680px')
 view.renderer.setAttribute('gap', '8%')
 view.renderer.setStyles(`@font-face{font-family:'Probe SC';src:url('${location.origin}/fonts/NotoSerifSC-Regular.otf')}@font-face{font-family:'Probe JP';src:url('${location.origin}/fonts/NotoSerifJP-Regular.otf')}html {color-scheme:${dark?'dark':'light'};background:${dark?'#20231f':'#f8f5ed'};color:${dark?'#e1e3d9':'#302d28'}} body{font-family:${index===2?"'Probe JP'":index===1?"'Probe SC'":"Georgia"},serif;font-size:20px;line-height:1.8;padding:20px 0 48px}h1{font-size:1.6em;font-weight:500;line-height:1.3;margin:0 0 1.25em}p{margin:0 0 0.85em;text-align:start}::selection{background:#b6c6a4;color:#20231f}`)
 await view.goTo(index)
 document.querySelector('#chapter').textContent = view.book.toc[index].label
 const {doc} = view.renderer.getContents()[0]
 const paragraph = doc.querySelector('#p0')
 const range = doc.createRange()
 range.setStart(paragraph.firstChild, 0)
 range.setEnd(paragraph.firstChild, paragraph.firstChild.length)
 const cfi = view.getCFI(index, range)
 const resolved = view.resolveCFI(cfi)
 const restoredRange = resolved.anchor(doc)
 const unicodeRange = doc.createRange()
 const last = doc.querySelector('p:last-child').firstChild
 unicodeRange.setStart(last, 0)
 unicodeRange.setEnd(last, last.length)
 const unicodeCFI = view.getCFI(index, unicodeRange)
 const unicodeRestored = view.resolveCFI(unicodeCFI).anchor(doc)
 await doc.fonts.ready
 await new Promise(resolve => setTimeout(resolve, 300))
 globalThis.probeResult = {
  scenarioTag: params.get('scenario'),
  title: view.book.metadata.title,
  toc: view.book.toc.map(item => item.label),
  chapter: doc.querySelector('h1').textContent,
  paragraphCount: doc.querySelectorAll('p').length,
  cfi, selectedText: range.toString(),
  cfiRoundTrip: restoredRange.toString() === range.toString(),
  unicodeRoundTrip: unicodeRestored.toString() === unicodeRange.toString(),
  fontLoaded: doc.fonts.check('20px ' + (index===2?'"Probe JP"':index===1?'"Probe SC"':'Georgia')),
  flow: view.renderer.getAttribute('flow'),
  engine: 'foliate-js', dark,
  bodyWidth: doc.body.getBoundingClientRect().width,
  horizontalOverflow: doc.documentElement.scrollWidth > doc.documentElement.clientWidth + 2,
 }
} catch(error) {globalThis.probeError = String(error)}
""",
    encoding="utf-8",
)

handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT))
server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
Thread(target=server.serve_forever, daemon=True).start()
QtWebEngineQuick.initialize()
app = QGuiApplication([])
for font in FONT_ROOT.glob("*.ttf"):
    QFontDatabase.addApplicationFont(str(font))
for font in FONT_ROOT.glob("*.otf"):
    QFontDatabase.addApplicationFont(str(font))
window = QQuickView()
window.setResizeMode(QQuickView.SizeRootObjectToView)
qml = ROOT / "Probe.qml"
qml.write_text(
    """import QtQuick
import QtWebEngine
Rectangle {
    width: 1120; height: 840
    color: "#f8f5ed"
    property string result: ""
    property string probeUrl: ""
    WebEngineView { id: web; anchors.fill: parent; url: parent.probeUrl; profile: WebEngineProfile { offTheRecord: true } }
    Timer { interval: 100; running: true; repeat: true; onTriggered: web.runJavaScript("JSON.stringify({result: globalThis.probeResult, error: globalThis.probeError})", value => { if (value) result = value }) }
}""",
    encoding="utf-8",
)
window.setSource(QUrl.fromLocalFile(str(qml)))
window.show()
scenarios = [
    ("english-light", 1120, 840, 0, False),
    ("english-narrow", 520, 840, 0, False),
    ("chinese-light", 840, 840, 1, False),
    ("chinese-dark", 840, 840, 1, True),
    ("japanese-light", 840, 840, 2, False),
    ("japanese-narrow-dark", 520, 840, 2, True),
]
results = []
scenario = -1
started = monotonic()
capture_after = 0.0
pending = None


def advance():
    global scenario, started, capture_after, pending
    scenario += 1
    if scenario >= len(scenarios):
        (ROOT / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
        app.exit(
            0
            if all(
                item.get("cfiRoundTrip")
                and item.get("unicodeRoundTrip")
                and item.get("fontLoaded")
                and item.get("screenshotSaved")
                and item.get("paragraphCount") == 8
                and len(item.get("toc", [])) == 3
                and item.get("chapter") == CHAPTERS[target[3]][1]
                and item.get("dark") == target[4]
                and item.get("scenarioTag") == target[0]
                and not item.get("horizontalOverflow")
                for item, target in zip(results, scenarios, strict=True)
            )
            else 1
        )
        return
    name, width, height, index, dark = scenarios[scenario]
    window.resize(width, height)
    window.rootObject().setProperty("result", "")
    window.rootObject().setProperty(
        "probeUrl",
        f"http://127.0.0.1:{server.server_port}/index.html?chapter={index}&scenario={name}"
        + ("&dark=1" if dark else ""),
    )
    started = monotonic()
    capture_after = 0.0
    pending = None


def poll():
    global capture_after, pending
    raw = window.rootObject().property("result")
    if raw and not pending:
        value = json.loads(raw)
        if value.get("error"):
            print(value, flush=True)
            app.exit(2)
            return
        if value.get("result") and value["result"].get("scenarioTag") == scenarios[scenario][0]:
            pending = value["result"]
            capture_after = monotonic() + 0.8
    if pending and monotonic() >= capture_after:
        name, width, height, _, _ = scenarios[scenario]
        saved = window.grabWindow().save(str(ROOT / f"{name}.png"))
        pending.update(scenario=name, width=width, height=height, screenshotSaved=saved)
        results.append(pending)
        advance()
    elif monotonic() - started > 25:
        print("Timeout", scenarios[scenario][0], raw, flush=True)
        app.exit(3)


timer = QTimer()
timer.setInterval(100)
timer.timeout.connect(poll)
timer.start()
advance()
code = app.exec()
server.shutdown()
raise SystemExit(code)
