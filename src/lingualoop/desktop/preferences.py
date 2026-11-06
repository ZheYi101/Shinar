from PySide6.QtCore import QObject, Property, QSettings, Signal, Slot


class DesktopPreferences(QObject):
    changed = Signal()
    CHOICES = {
        "displayLanguage": ("zh_CN", "system"),
        "themeMode": ("system", "light", "dark"),
        "targetLanguage": ("japanese", "english", "chinese", "french", "germany", "spanish"),
        "nativeLanguage": ("chinese", "english", "japanese", "french", "germany", "spanish"),
        "difficulty": ("unknown", "A1", "A2", "B1", "B2", "C1", "C2"),
        "feedbackTiming": ("end", "immediate", "off"),
        "correctionIntensity": ("low", "medium", "high"),
        "voicePauseMs": ("650", "1000"),
    }
    DEFAULTS = {key: choices[0] for key, choices in CHOICES.items()}

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else QSettings("LinguaLoop", "Desktop")

    def _get(self, key):
        value = self._settings.value(key, self.DEFAULTS.get(key, False))
        return value if value in self.CHOICES.get(key, ()) else self.DEFAULTS[key]

    @Property(str, notify=changed)
    def displayLanguage(self):
        return self._get("displayLanguage")

    @Property(str, notify=changed)
    def themeMode(self):
        return self._get("themeMode")

    @Property(bool, notify=changed)
    def reducedMotion(self):
        return str(self._settings.value("reducedMotion", "false")).lower() in {"true", "1"}

    @Property(bool, notify=changed)
    def autoReadReplies(self):
        return str(self._settings.value("autoReadReplies", "true")).lower() in {"true", "1"}

    @Property(str, notify=changed)
    def voicePauseMs(self):
        return self._get("voicePauseMs")

    @Property(str, notify=changed)
    def targetLanguage(self):
        return self._get("targetLanguage")

    @Property(str, notify=changed)
    def nativeLanguage(self):
        return self._get("nativeLanguage")

    @Property(str, notify=changed)
    def difficulty(self):
        return self._get("difficulty")

    @Property(str, notify=changed)
    def feedbackTiming(self):
        return self._get("feedbackTiming")

    @Property(str, notify=changed)
    def correctionIntensity(self):
        return self._get("correctionIntensity")

    @Slot(str, "QVariant")
    def setValue(self, key, value):
        if key in {"reducedMotion", "autoReadReplies"}:
            value = bool(value)
        elif key not in self.CHOICES or value not in self.CHOICES[key]:
            return
        self._settings.setValue(key, value)
        self._settings.sync()
        self.changed.emit()
