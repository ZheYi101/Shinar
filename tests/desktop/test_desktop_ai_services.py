import asyncio
from threading import Event

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QInputMethodEvent
from PySide6.QtTest import QTest

from shinar.infrastructure import ai_configuration
from tests.support.qt import item, click, until
from tests.support.scenarios import workspace_of



def enter(window, name, value):
    field = item(window, name)
    field.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    event = QInputMethodEvent()
    event.setCommitString(value)
    QGuiApplication.sendEvent(field, event)
    QTest.qWait(20)
    assert field.property("text") == value


def controller(window):
    from PySide6.QtQml import qmlContext
    return qmlContext(window).contextProperty("aiServices")


def choose(window, name, index):
    """Use the actual non-editable popup and its keyboard navigation."""
    click(window, name, scroll="settingsOverview")
    QTest.keyClick(window, Qt.Key.Key_Home)
    for _ in range(index):
        QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    QTest.qWait(30)
    assert item(window, name).property("currentIndex") == index


def test_qml_configure_probe_save_and_next_start_use_saved_api(desktop, monkeypatch, tmp_path):
    from tests.support.configuration import fake_crypt
    from shinar.desktop import app

    vm, window, _, provider, _, _, database = desktop
    api = controller(window)
    assert api is not None
    monkeypatch.setattr(ai_configuration, "_crypt", fake_crypt)
    ws = workspace_of(window)
    ws.setCategory("services")
    ws.navigate("settings")
    QTest.qWait(60)
    enter(window, "aiBaseUrlInput", "https://models.example.test/v1")
    enter(window, "aiApiKeyInput", "fake-dummy-key-only")
    assert item(window, "aiReasoningModelChoice").isVisible()
    assert not item(window, "aiReasoningModelChoice").isEnabled()
    assert not item(window, "aiReasoningModelChoice").property("editable")
    assert not item(window, "saveAiConfigurationButton").isEnabled()

    async def probe(connection):
        assert connection.api_key == "fake-dummy-key-only"
        return ["chat-small", "reason-big"]

    api.probe = probe
    click(window, "testAiConnectionButton", scroll="settingsOverview")
    until(lambda: not api.busy)
    assert api.modelOptions == ["chat-small", "reason-big"]
    assert api.reasoningModel == ""  # Metadata never silently selects a model.
    assert not api.canSave
    choose(window, "aiReasoningModelChoice", 1)
    choose(window, "aiDialogueModelChoice", 1)
    assert api.reasoningModel == "reason-big" and api.dialogueModel == "chat-small"
    assert api.canSave
    assert "fake-dummy-key-only" not in item(window, "aiApiKeyInput").property("displayText")
    click(window, "saveAiConfigurationButton", scroll="settingsOverview")
    assert api.restartRequired and api.hasApiKey and not api.errorText
    assert item(window, "aiApiKeyInput").property("text") == ""
    assert "fake-dummy-key-only" not in api.store.path.read_text(encoding="utf-8")
    assert vm._workbench._provider is provider
    # Leaving and re-opening settings preserves the fields without exposing the key.
    ws.navigate("library")
    ws.navigate("settings")
    assert api.reasoningModel == "reason-big" and api.hasApiKey
    # A new real provider uses the saved fields ahead of conflicting environment.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHINAR_DATA_DIR", str(database.parent))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_REASONING_MODEL", "environment-model")
    work = app.create_workbench(use_mock=False)
    settings = work._provider._settings
    assert settings.base_url == "https://models.example.test/v1"
    assert settings.api_key.get_secret_value() == "fake-dummy-key-only"
    assert settings.reasoning_model == "reason-big" and settings.dialogue_model == "chat-small"
    asyncio.run(work.aclose())


def test_edited_connection_rejects_late_metadata_and_auth_errors_stay_inline(desktop):
    vm, window, _, _, _, _, _ = desktop
    api = controller(window)
    api.baseUrl, api.reasoningModel = "https://example.test/v1", "reason"
    api.setApiKey("fake-key")
    entered, release = Event(), Event()

    async def probe(connection):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return ["old-endpoint-model"]

    api.probe = probe
    api.testConnection()
    until(entered.is_set)
    api.baseUrl = "https://changed.example.test/v1"
    release.set()
    until(lambda: not api.busy)
    assert not api.modelOptions and "重新检查" in api.statusText

    async def denied(connection):
        raise ValueError("ai_api_auth_failed")

    api.probe = denied
    api.testConnection()
    until(lambda: not api.busy)
    assert "API Key" in api.errorText and "fake-key" not in api.errorText
    assert not vm.busy


def test_current_service_list_required_and_same_model_choice_is_saved(desktop, monkeypatch):
    from tests.support.configuration import fake_crypt

    _, window, _, _, _, _, _ = desktop
    api = controller(window)
    monkeypatch.setattr(ai_configuration, "_crypt", fake_crypt)
    ws = workspace_of(window)
    ws.setCategory("services")
    ws.navigate("settings")
    api.baseUrl = "https://example.test/v1"
    api.setApiKey("dummy-key")
    api.reasoningModel = "unlisted-model"
    api.save()
    assert not api.store.path.exists() and not api.canSave

    async def probe(connection):
        return ["listed-model"]

    api.probe = probe
    api.testConnection()
    until(lambda: not api.busy)
    assert not api.canSave and "重新选择" in api.modelSelectionHint
    choose(window, "aiReasoningModelChoice", 0)
    assert api.dialogueModel == "" and api.canSave
    click(window, "saveAiConfigurationButton", scroll="settingsOverview")
    saved = api.store.load()
    assert saved.reasoning_model == saved.dialogue_model == "listed-model"
    api.baseUrl = "https://other.example.test/v1"
    assert not api.modelsLoaded and not api.canSave and not api.modelOptions
    api.save()
    assert "当前服务" in api.errorText
    assert api.store.load() == saved  # An unverified endpoint cannot replace it.


def test_empty_catalog_retry_and_refresh_preserve_model_identity(desktop):
    _, window, _, _, _, _, _ = desktop
    api = controller(window)
    api.baseUrl = "https://example.test/v1"
    api.setApiKey("dummy-key")
    calls = []
    result = []

    async def probe(connection):
        calls.append(connection.base_url)
        return list(result)

    api.probe = probe
    api.testConnection()
    api.testConnection()
    until(lambda: not api.busy)
    assert len(calls) == 1
    assert api.modelsLoaded and not api.canSave and "没有可选模型" in api.errorText
    result[:] = ["a", "b"]
    api.testConnection()
    until(lambda: not api.busy)
    api.reasoningModel, api.dialogueModel = "b", "a"
    assert api.canSave and not api.errorText
    result[:] = ["b", "c"]
    api.testConnection()
    assert not api.canSave  # Refresh cannot save a list that is still in flight.
    until(lambda: not api.busy)
    assert api.reasoningModel == "b" and api.dialogueModel == "a"
    assert not api.canSave and "重新选择" in api.modelSelectionHint
    api.dialogueModel = ""
    assert api.canSave
    api.setApiKey("different-key")
    assert not api.modelsLoaded and not api.canSave
