"""Named business operations and callbacks with instance-local invalidation."""

from dataclasses import dataclass, replace
from uuid import uuid4


@dataclass(frozen=True)
class OperationIdentity:
    instance: str
    task: str
    generation: int
    session: str
    material: str


@dataclass(frozen=True)
class LearningOperationSnapshot:
    identity: OperationIdentity | None = None
    busy: bool = False
    status: str = ""
    speech_status: str = ""
    retryable: bool = False
    closed: bool = False


@dataclass(frozen=True)
class ProjectionChange:
    """A business-success notification, not permission to write Workbench data."""

    material: bool = False
    scope: bool = False
    review: bool = False


class LearningOperations:
    def __init__(self):
        self._instance, self._generation = uuid4().hex, 0
        self._snapshot = LearningOperationSnapshot()
        self._retry, self._callback = None, None

    @property
    def snapshot(self) -> LearningOperationSnapshot:
        return self._snapshot

    @property
    def retry(self):
        return self._retry

    def status(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, status=value)

    def speech_status(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, speech_status=value)

    def start(self, status, operation, callback, session, material):
        if self._snapshot.closed or self._snapshot.busy:
            return None
        self._generation += 1
        identity = OperationIdentity(
            self._instance, "learning-" + uuid4().hex, self._generation, session, material
        )
        self._retry, self._callback = (status, operation, callback), callback
        self._snapshot = replace(
            self._snapshot, identity=identity, busy=True, status=status, retryable=True
        )
        return identity

    def complete(self, task: str, error: str):
        identity = self._snapshot.identity
        if (
            self._snapshot.closed
            or not self._snapshot.busy
            or not identity
            or task != identity.task
        ):
            return False, None
        callback, self._callback = self._callback, None
        self._snapshot = replace(self._snapshot, busy=False)
        if not error:
            self.clear_retry()
        return True, callback

    def clear_retry(self):
        self._retry = None
        self._snapshot = replace(self._snapshot, retryable=False)

    def close(self):
        self._callback, self._retry = None, None
        self._snapshot = replace(
            self._snapshot, closed=True, busy=False, identity=None, retryable=False
        )
