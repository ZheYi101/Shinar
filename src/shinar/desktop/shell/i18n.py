"""Qt translation entry point. UI locale and the learner's native language are separate."""

from __future__ import annotations

from importlib.resources import files
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QLocale, QObject, Property, QTranslator, Signal


SOURCE_LOCALE = "zh_CN"
AVAILABLE_LOCALES = (SOURCE_LOCALE,)
LEARNING_LANGUAGES = {
    "zh": "chinese",
    "en": "english",
    "ja": "japanese",
    "fr": "french",
    "de": "germany",
    "es": "spanish",
}


def resolve_display_language(
    preference: str,
    system_languages: Sequence[str],
    available: Sequence[str] = AVAILABLE_LOCALES,
) -> str:
    """Use OS preference order when requested, with a shipped-language fallback."""
    candidates = system_languages if preference == "system" else (preference,)
    for candidate in candidates:
        normalized = candidate.replace("-", "_")
        if normalized in available:
            return normalized
        language = normalized.split("_")[0]
        match = next((item for item in available if item.split("_")[0] == language), None)
        if match:
            return match
    return SOURCE_LOCALE


def suggested_native_language(system_languages: Sequence[str]) -> str:
    """Future first-run suggestion only; never overwrite an explicit learner preference."""
    for candidate in system_languages:
        language = LEARNING_LANGUAGES.get(candidate.replace("-", "_").split("_")[0])
        if language:
            return language
    return "chinese"


class DesktopLanguageController(QObject):
    changed = Signal()

    def __init__(self, preferences, engine, parent=None):
        super().__init__(parent)
        self._preferences, self._engine = preferences, engine
        self._system_languages = QLocale.system().uiLanguages()
        self._translator = None
        self._effective = ""
        preferences.changed.connect(self._reload)
        self._reload()

    @Property(str, notify=changed)
    def effectiveLanguage(self) -> str:
        return self._effective

    @Property(str, constant=True)
    def systemLanguage(self) -> str:
        return self._system_languages[0] if self._system_languages else QLocale.system().name()

    @Property(str, constant=True)
    def suggestedNativeLanguage(self) -> str:
        return suggested_native_language(self._system_languages)

    def _reload(self) -> None:
        requested = resolve_display_language(
            self._preferences.displayLanguage, self._system_languages
        )
        if requested == self._effective:
            return
        app = QCoreApplication.instance()
        if self._translator:
            app.removeTranslator(self._translator)
            self._translator = None
        if requested != SOURCE_LOCALE:
            translator = QTranslator(self)
            path = files("shinar.desktop").joinpath(f"translations/shinar_{requested}.qm")
            if translator.load(str(path)):
                app.installTranslator(translator)
                self._translator = translator
            else:
                requested = SOURCE_LOCALE
        self._effective = requested
        self._engine.retranslate()
        self.changed.emit()
