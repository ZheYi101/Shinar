"""Resource scan lifetime is separate from library operations and filtering."""

from threading import Thread
from uuid import uuid4

from shinar.desktop.presentation.conversation_presentation import freeze
from shinar.local_speech.resources import resource_snapshot
from shinar.desktop.speech_library.state import LibraryEvent


class ResourceMonitor:
    def __init__(self):
        self._identity = ""
        self._enabled = False
        self._closed = False
        self._threads = []
        self._snapshot = freeze({})

    @property
    def snapshot(self):
        return self._snapshot

    def enable(self, enabled):
        self._enabled = enabled and not self._closed
        self._identity = uuid4().hex

    def poll(self, pids, gpu_pids, emit):
        if not self._enabled or not self.finished():
            return
        identity, processes, gpu = self._identity, tuple(pids), tuple(gpu_pids)
        self._threads = []

        def collect():
            try:
                value = resource_snapshot(processes, gpu)
                emit(LibraryEvent(identity, "resources", freeze(value)))
            except Exception:
                emit(LibraryEvent(identity, "resources", error="resource_scan_failed"))

        thread = Thread(target=collect, daemon=True, name="shinar-speech-resources")
        self._threads.append(thread)
        thread.start()

    def accept(self, event):
        if self._closed or not self._enabled or event.identity != self._identity or event.error:
            return False
        self._snapshot = freeze(event.value)
        return True

    def finished(self):
        return all(not thread.is_alive() for thread in self._threads)

    def close(self):
        self._closed = True
        self.enable(False)

    def wait(self, timeout):
        from time import monotonic

        end = monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0, end - monotonic()))
