"""Relocate a built ZIP and verify its private interpreter, QML, icon and native launcher.

No microphone, real models or user application state is accessed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

PROBE = r"""
import asyncio, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
root, evidence = map(Path, sys.argv[1:])
assert Path(sys.prefix).is_relative_to(root), sys.prefix
import shinar.desktop.app as desktop
assert Path(desktop.__file__).is_relative_to(root)
from PySide6.QtCore import QSettings, QTimer, QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase, QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtQuick import QQuickItem
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from shinar.application import LearningWorkbench
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.desktop.shell.identity import set_windows_app_id
from shinar.local_speech.installation import _check_platform, runtime_spec
from shinar.realtime.audio_ipc import encode_message, read_file_message
import io
_check_platform()
assert runtime_spec('rtc-cpu').id == 'rtc-cpu'
message = encode_message({'kind': 'package-test'}, b'pcm')
assert read_file_message(io.BytesIO(message)) == ({'kind': 'package-test'}, b'pcm')
set_windows_app_id()
QtWebEngineQuick.initialize()
app = QGuiApplication([])
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(evidence / 'settings'))
prefs = DesktopPreferences(QSettings(str(evidence / 'preferences.ini'), QSettings.Format.IniFormat))
vm = LearningViewModel(LearningWorkbench(MockLearningLLMProvider(),
    event_store=SQLiteStore(evidence / 'smoke.sqlite3')), 'Mock', preferences=prefs)
engine = desktop.create_engine(vm, initial_visible=True,
    window_settings=QSettings(str(evidence / 'window.ini'), QSettings.Format.IniFormat))
window = engine.rootObjects()[0]
window.setTitle('Shinar · 安装包独立检查 · 本机模拟 API')
assert app.applicationName() == 'Shinar'
assert not app.windowIcon().isNull()
assert not window.icon().isNull()
assert len(app.windowIcon().availableSizes()) == 9
assert 'Noto Serif SC' in QFontDatabase.families()
assert 'Noto Serif JP' in QFontDatabase.families()
import ctypes
assert ctypes.windll.shell32.ExtractIconExW(str(root / 'Shinar.exe'), 0, None, None, 0) > 0
from livekit import rtc
import onnxruntime
import PySide6
qt_root = Path(PySide6.__file__).parent
for relative in ('QtWebEngineProcess.exe', 'resources/qtwebengine_resources.pak',
                 'resources/icudtl.dat', 'translations/qtwebengine_locales/en-US.pak',
                 'qml/QtWebEngine/qtwebenginequickplugin.dll', 'qml/QtWebChannel/qmldir'):
    assert (qt_root / relative).is_file(), relative
assert engine.reader_runtime.profile.isOffTheRecord()
requests = []
class Models(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        requests.append(self.path)
        assert self.path == '/v1/models'
        assert self.headers['Authorization'] == 'Bearer package-dummy-key'
        content = json.dumps({'data': [{'id': 'packaged-reasoner'}, {'id': 'packaged-chat'}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)
    def do_POST(self):
        requests.append('unexpected-generation')
        self.send_error(405)
server = ThreadingHTTPServer(('127.0.0.1', 0), Models)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

def wait(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate(), 'Packaged API settings action timed out'

def field(name):
    result = window.findChild(QQuickItem, name)
    assert result is not None, name
    return result

def enter(name, text):
    target = field(name)
    target.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    event = QInputMethodEvent()
    event.setCommitString(text)
    app.sendEvent(target, event)
    app.processEvents()
    assert target.property('text') == text

def click(name):
    QTest.qWait(100)
    target = field(name)
    point = target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()
    assert 0 <= point.y() < window.height(), (name, point)
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()

def choose(name, index):
    click(name)
    QTest.keyClick(window, Qt.Key.Key_Home)
    for _ in range(index):
        QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    QTest.qWait(50)
    assert field(name).property('currentIndex') == index
def capture():
    try:
        # Decode synthetic audio without opening a microphone or output device.
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioDecoder
        import wave
        wav = evidence / 'synthetic.wav'
        with wave.open(str(wav), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b'\x10\x00\xf0\xff' * 1600)
        decoder = QAudioDecoder()
        decoded = []
        decoder.bufferReady.connect(lambda: decoded.append(decoder.read().byteCount()))
        decoder.setSource(QUrl.fromLocalFile(str(wav)))
        decoder.start()
        wait(lambda: bool(decoded) or decoder.error() != QAudioDecoder.Error.NoError)
        assert decoded and sum(decoded) > 0, decoder.errorString()
        decoder.stop()
        apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True)
        apm.set_stream_delay_ms(80)
        apm.process_reverse_stream(rtc.AudioFrame(bytearray(960), 48000, 1, 480))
        apm.process_stream(rtc.AudioFrame(bytearray(960), 48000, 1, 480))
        engine.workspace.setCategory('services')
        engine.workspace.navigate('settings')
        window.setWidth(1180)
        window.setHeight(900)
        app.processEvents()
        url = 'http://127.0.0.1:' + str(server.server_port) + '/v1'
        enter('aiBaseUrlInput', url)
        enter('aiApiKeyInput', 'package-dummy-key')
        click('testAiConnectionButton')
        wait(lambda: not engine.ai_services.busy)
        assert engine.ai_services.modelOptions == ['packaged-chat', 'packaged-reasoner']
        assert not field('aiReasoningModelChoice').property('editable')
        assert not field('aiDialogueModelChoice').property('editable')
        assert not engine.ai_services.canSave
        choose('aiReasoningModelChoice', 1)
        choose('aiDialogueModelChoice', 1)
        assert engine.ai_services.canSave
        click('saveAiConfigurationButton')
        assert engine.ai_services.restartRequired and not engine.ai_services.errorText
        assert 'package-dummy-key' not in engine.ai_services.store.path.read_text(encoding='utf-8')
        assert field('aiApiKeyInput').property('text') == ''
        os.environ['SHINAR_DATA_DIR'] = str(evidence)
        reopened = desktop.create_workbench(use_mock=False)
        assert reopened._provider._settings.base_url == url
        assert reopened._provider._settings.dialogue_model == 'packaged-chat'
        assert reopened._provider._settings.reasoning_model == 'packaged-reasoner'
        asyncio.run(reopened.aclose())
        assert requests == ['/v1/models']
        for theme in ('light', 'dark'):
            prefs.setValue('themeMode', theme)
            window.setHeight(900)
            for width in (360, 600, 800, 1180, 1440):
                window.setWidth(width)
                QTest.qWait(120)
                app.processEvents()
                for name in ('aiBaseUrlInput', 'aiApiKeyInput', 'aiReasoningModelChoice', 'aiDialogueModelChoice', 'saveAiConfigurationButton'):
                    control = field(name)
                    p = control.mapToScene(QPointF())
                    assert p.x() >= 0 and p.x() + control.width() <= window.width() + 1, name
                image = window.grabWindow()
                assert not image.isNull()
                assert image.save(str(evidence / ('qml-' + theme + '-' + str(width) + '.png')))
                if theme == 'light' and width in (360, 1180):
                    click('aiReasoningModelChoice')
                    popup = window.findChild(QObject, 'aiReasoningModelChoice-popup')
                    assert popup is not None and popup.property('visible')
                    QTest.qWait(120)
                    assert window.grabWindow().save(str(evidence / ('model-picker-' + str(width) + '.png')))
                    QTest.keyClick(window, Qt.Key.Key_Escape)
        print(json.dumps({'ok': True, 'python': sys.version.split()[0],
            'application_version': app.applicationVersion(),
            'icon_sizes': [s.width() for s in app.windowIcon().availableSizes()],
            'private_runtime': True, 'local_speech_platform': True,
            'rtc_import': bool(rtc), 'onnxruntime': onnxruntime.__version__,
            'webengine_resources': True, 'reader_private_profile': True,
            'api_settings_gui': True, 'api_model_dropdowns': True, 'api_configuration_reload': True,
            'encrypted_credentials': True, 'audio_decoder': True, 'rtc_apm': True,
            'paid_model_calls': 0}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        vm.close()
        window.close()
        app.quit()
QTimer.singleShot(500, capture)
raise SystemExit(app.exec())
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--visible", action="store_true", help="Use a visible native Windows window")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    relocated = output / "移动 安装"
    with ZipFile(args.archive.resolve()) as archive:
        archive.extractall(relocated)
    app = relocated / "Shinar"
    evidence = output / "evidence"
    evidence.mkdir()
    probe = output / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "QML_IMPORT_PATH",
        "QML2_IMPORT_PATH",
    ):
        environment.pop(key, None)
    environment.update(
        RUN_REAL_AI_TESTS="0",
        QT_QPA_PLATFORM="windows" if args.visible else "offscreen",
        QT_QUICK_BACKEND="software",
        SHINAR_KIRIGAMI_MODE="off",
        SHINAR_DATA_DIR=str(evidence / "data"),
        SHINAR_SPEECH_DIR=str(evidence / "speech"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [str(app / "runtime/python.exe"), "-I", str(probe), str(app), str(evidence)],
        cwd=output,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    (evidence / "qml-output.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    reports = [line for line in result.stdout.splitlines() if line.startswith('{"ok":')]
    if not reports:
        raise SystemExit("QML smoke did not report successful completion")
    launcher = subprocess.run(
        [str(app / "Shinar.exe"), "--mock", "--smoke"], cwd=output, env=environment, timeout=45
    )
    if launcher.returncode:
        raise SystemExit(f"Native launcher failed: {launcher.returncode}")
    # Local model preparation relies on a real interpreter with offline venv bootstrap.
    child = evidence / "child-runtime"
    subprocess.run([str(app / "runtime/python.exe"), "-I", "-B", "-m", "venv", str(child)],
                   cwd=output, env=environment, check=True, timeout=90)
    subprocess.run([str(child / "Scripts/python.exe"), "-I", "-m", "pip", "--version"],
                   cwd=output, env=environment, check=True, timeout=30, capture_output=True)
    report = {
        **json.loads(reports[-1]),
        "native_launcher": True,
        "relocated_path_with_spaces_and_chinese": True,
        "model_venv_bootstrap": True,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
