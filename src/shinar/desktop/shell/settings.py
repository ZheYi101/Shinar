"""Read former preferences without copying or modifying the legacy store."""

from PySide6.QtCore import QSettings


class ProductSettings:
    def __init__(self, section: str) -> None:
        self.current = QSettings("Shinar", section)
        self.legacy = QSettings("LinguaLoop", section)

    def value(self, key: str, default=None):
        source = self.current if self.current.contains(key) else self.legacy
        return source.value(key, default)

    def setValue(self, key: str, value) -> None:
        self.current.setValue(key, value)

    def sync(self) -> None:
        self.current.sync()
