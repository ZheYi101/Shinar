"""Chinese-first translation, OS-language resolution and learner-language separation."""

from PySide6.QtCore import QSettings, QTranslator, Qt
from PySide6.QtGui import QGuiApplication, QInputMethodEvent
from PySide6.QtTest import QTest

from shinar.desktop.i18n import resolve_display_language, suggested_native_language
from shinar.desktop.preferences import DesktopPreferences
from test_desktop_workflow import desktop, qt_app, item, load_and_start, workspace_of  # noqa: F401


def test_system_language_order_fallback_and_learning_language_mapping():
    assert resolve_display_language("zh_CN", ["en-US"]) == "zh_CN"
    assert resolve_display_language("system", ["en-US"]) == "zh_CN"
    assert resolve_display_language("system", ["ja-JP", "en-US"], ("zh_CN", "en_US")) == "en_US"
    assert resolve_display_language("system", ["zh-Hans-CN"]) == "zh_CN"
    assert suggested_native_language(["en-US"]) == "english"
    assert suggested_native_language(["ja-JP", "zh-CN"]) == "japanese"
    assert suggested_native_language(["de-DE"]) == "germany"
    assert suggested_native_language(["unknown"]) == "chinese"


def test_display_preference_persists_separately_from_native_language(tmp_path):
    path = str(tmp_path / "preferences.ini")
    prefs = DesktopPreferences(QSettings(path, QSettings.Format.IniFormat))
    assert prefs.displayLanguage == "zh_CN" and prefs.nativeLanguage == "chinese"
    prefs.setValue("nativeLanguage", "english")
    prefs.setValue("displayLanguage", "system")
    prefs.setValue("displayLanguage", "not-shipped")
    restored = DesktopPreferences(QSettings(path, QSettings.Format.IniFormat))
    assert restored.displayLanguage == "system" and restored.nativeLanguage == "english"


def test_qml_and_python_text_use_translator_without_changing_learning_data(desktop):
    vm, window, _, _, _, audio, _ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    vm.draft = "An unsent thought 😀."
    thread_id = vm._workbench.session.id
    source_text = vm._workbench.material.content
    audio.cleared = False

    class ProbeTranslator(QTranslator):
        def isEmpty(self):
            return False

        def translate(self, context, source, disambiguation=None, n=-1):
            return {
                ("WindowTitleBar", "原文"): "Source",
                ("Desktop", "新对话"): "New conversation",
            }.get((context, source), "")

    translator = ProbeTranslator()
    app = QGuiApplication.instance()
    assert app.installTranslator(translator)
    # The real engine's retranslation entry point also runs on future locale changes.
    engine = next(parent for parent in (ws.parent(),) if hasattr(parent, "retranslate"))
    try:
        engine.retranslate()
        ws.refresh()
        app.processEvents()
        assert item(window, "openSourceButton").property("text") == "Source"
        assert ws.threads[0]["title"] == "New conversation"
        assert vm._workbench.session.id == thread_id and vm.draft == "An unsent thought 😀."
        assert vm._workbench.material.content == source_text and not audio.cleared
    finally:
        app.removeTranslator(translator)
        engine.retranslate()
        ws.refresh()


def test_ime_composition_does_not_submit_with_control_enter(desktop):
    vm, window, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    vm.draft = "A thought before composing."
    editor = item(window, "messageInput")
    editor.forceActiveFocus()
    QGuiApplication.sendEvent(editor, QInputMethodEvent("未完", []))
    assert editor.property("inputMethodComposing")
    QTest.keyClick(window, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert not vm.busy and len(vm.messages) == 1
    event = QInputMethodEvent()
    event.setCommitString("中文😀")
    QGuiApplication.sendEvent(editor, event)
    assert "中文😀" in vm.draft and not vm.busy


def test_automatic_voice_ui_and_status_are_translatable(desktop):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    vm.draft = "An independent draft."
    ws = workspace_of(window)
    engine = ws.parent()

    class VoiceTranslator(QTranslator):
        def isEmpty(self):
            return False

        def translate(self, context, source, disambiguation=None, n=-1):
            return {
                ("ConversationPage", "结束并发送"): "Finish and send",
                ("Desktop", "正在录音 · 结束后自动发送"): "Recording; sends when finished",
            }.get((context, source), "")

    translator = VoiceTranslator()
    app = QGuiApplication.instance()
    app.installTranslator(translator)
    try:
        engine.retranslate()
        vm.startRecording()
        assert item(window, "recordButton").property("text") == "Finish and send"
        assert vm.voice.statusText == "Recording; sends when finished"
        assert vm.draft == "An independent draft."
    finally:
        vm.cancelRecording()
        app.removeTranslator(translator)
        engine.retranslate()
