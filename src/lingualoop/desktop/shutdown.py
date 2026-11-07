"""Keep the Qt loop responsive until application-owned resources are released."""

from dataclasses import dataclass
from time import monotonic
from typing import Callable

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot


@dataclass(frozen=True)
class ShutdownParticipant:
    name: str
    begin: Callable
    finished: Callable[[], bool]


class ShutdownCoordinator(QObject):
    changed = Signal()
    finished = Signal()

    def __init__(self, application, parent=None):
        super().__init__(parent)
        self.application = application
        self.participants: list[ShutdownParticipant] = []
        self._state = "running"
        self._error = ""
        self._deadline = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self.poll)

    @Property(str, notify=changed)
    def state(self) -> str:
        return self._state

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    def register(self, name, begin, finished) -> None:
        self.participants.append(ShutdownParticipant(name, begin, finished))

    @Slot()
    def quit(self) -> None:
        if self._state == "closed" or self._timer.isActive():
            return
        self._state, self._error = "closing", ""
        self._deadline = monotonic() + 15
        try:
            for participant in self.participants:
                participant.begin()
        except Exception:
            self._error = self.tr("后台清理未完成，请重试退出。")
        self.changed.emit()
        if not self._error:
            self._timer.start()

    @Slot()
    def poll(self) -> None:
        try:
            ready = [participant.finished() for participant in self.participants]
        except Exception:
            ready = [False]
            self._error = self.tr("后台清理未完成，请重试退出。")
        if all(ready):
            self._timer.stop()
            self._state = "closed"
            self.changed.emit()
            self.finished.emit()
            self.application.quit()
        elif self._error or monotonic() >= self._deadline:
            self._timer.stop()
            self._error = self.tr("后台任务仍在清理，程序尚未退出。请重试。")
            self.changed.emit()
