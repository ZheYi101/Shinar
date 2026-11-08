"""Immutable operation inputs and main-thread-owned speech-library state."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4
from typing import Any, Literal
import re
import httpx

from shinar.desktop.presentation.conversation_presentation import freeze


@dataclass(frozen=True)
class LibraryRequest:
    root: Path
    catalog: tuple[str, ...]
    language: str
    scenario: str
    settings: str


@dataclass(frozen=True)
class LibraryEvent:
    identity: str
    kind: Literal["progress", "stage", "completed", "resources"]
    value: Any = None
    error: str = ""
    detail: Any = None


@dataclass(frozen=True)
class OperationSnapshot:
    identity: str = ""
    busy: bool = False
    status: str = ""
    operation: str = ""
    progress: float = 0
    error: Any = field(default_factory=lambda: freeze({}))
    closed: bool = False


class LibraryOperations:
    def __init__(self):
        self._snapshot = OperationSnapshot()
        self._cancel = Event()
        self._threads = []

    @property
    def snapshot(self) -> OperationSnapshot:
        return self._snapshot

    def status(self, value: str) -> None:
        self._snapshot = replace(self._snapshot, status=value)

    def start(self, title, operation, emit) -> bool:
        if self._snapshot.busy or self._snapshot.closed:
            return False
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        identity, cancel = uuid4().hex, Event()
        self._cancel = cancel
        self._snapshot = OperationSnapshot(identity, True, title, title)

        def run():
            try:
                result = operation(
                    cancel, lambda kind, value: emit(LibraryEvent(identity, kind, value))
                )
                if cancel.is_set():
                    raise RuntimeError("speech_setup_cancelled")
                event = LibraryEvent(identity, "completed", freeze(result))
            except Exception as error:
                message = str(error)
                if type(error).__name__ == "DownloadCancelled":
                    message = "speech_setup_cancelled"
                elif isinstance(error, httpx.TransportError):
                    message = "library_network_error"
                elif isinstance(error, httpx.HTTPStatusError):
                    message = "library_http_error"
                elif not isinstance(error, (ValueError, RuntimeError)):
                    message = "library_unknown_error"
                event = LibraryEvent(
                    identity, "completed", error=message, detail=type(error).__name__
                )
            emit(event)

        thread = Thread(target=run, name="shinar-speech-library", daemon=True)
        self._threads.append(thread)
        thread.start()
        return True

    def accept(self, event: LibraryEvent) -> bool:
        if (
            self._snapshot.closed
            or not self._snapshot.busy
            or event.identity != self._snapshot.identity
        ):
            return False
        if event.kind == "progress":
            done, total = event.value
            self._snapshot = replace(self._snapshot, progress=done / total if total else 0)
        elif event.kind == "completed":
            code = (
                event.error
                if re.fullmatch(r"speech_[a-z_]+", event.error)
                else "speech_setup_failed"
            )
            error = {"type": event.detail, "code": code} if event.error else {}
            self._snapshot = replace(self._snapshot, busy=False, error=freeze(error))
        return True

    def cancel(self) -> None:
        self._cancel.set()

    def close(self) -> None:
        self._cancel.set()
        self._snapshot = replace(self._snapshot, identity="", busy=False, closed=True)

    def finished(self) -> bool:
        return all(not thread.is_alive() for thread in self._threads)

    def wait(self, timeout) -> None:
        from time import monotonic

        end = monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0, end - monotonic()))


class CatalogProjection:
    def __init__(self):
        self._snapshot = freeze(
            {
                "rows": [],
                "hardware": {},
                "storageUsage": {},
                "runtimes": {
                    name: {"prepared": False, "downloadMiB": 0.0, "diskMiB": 0.0}
                    for name in ("cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu")
                },
            }
        )
        self._language, self._scenario = "ja", "conversation"
        self._refresh_pending = False
        self._packages = ()
        self._revision = 0

    @property
    def packages(self):
        return self._packages

    def configure(self, packages):
        self._packages = tuple(package.model_dump_json() for package in packages)

    @property
    def revision(self):
        return self._revision

    def download_changed(self):
        self._revision += 1

    @property
    def snapshot(self):
        return self._snapshot

    @property
    def language(self):
        return self._language

    @property
    def scenario(self):
        return self._scenario

    def filter(self, language, scenario):
        self._language, self._scenario = language, scenario

    def apply(self, value):
        self._snapshot = freeze(value)

    def select(self, identity, task):
        from shinar.desktop.presentation.conversation_presentation import display_value

        value = display_value(self._snapshot)
        for row in value["rows"]:
            if row["task"].lower() == task:
                row["selected"] = row["id"] == identity
        self.apply(value)

    def defer_refresh(self):
        self._refresh_pending = True

    def take_refresh(self):
        pending, self._refresh_pending = self._refresh_pending, False
        return pending
