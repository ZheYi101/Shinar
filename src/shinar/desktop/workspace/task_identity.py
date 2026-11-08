"""Independent import, document and search identities over the existing worker."""

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class SourceTask:
    instance: str
    task: str
    generation: int
    material: str
    session: str


class TaskLane:
    def __init__(self):
        self._instance = uuid4().hex
        self._generation, self._current, self._closed = 0, None, False

    @property
    def generation(self):
        return self._generation

    def invalidate(self):
        self._generation += 1
        self._current = None

    def request(self, material="", session=""):
        if self._closed:
            return None
        self._generation += 1
        self._current = SourceTask(
            self._instance, "source-" + uuid4().hex, self._generation, material, session
        )
        return self._current

    def accepts(self, identity):
        return not self._closed and self._current == identity

    def close(self):
        self.invalidate()
        self._closed = True
