"""Source tasks use named existing-worker jobs; callbacks stay on the main thread."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass

from shinar.infrastructure.blocking_jobs import BlockingRequest, run_blocking


@dataclass(frozen=True)
class PendingSource:
    identity: object
    lane: object
    callback: object
    failed: object


class WorkspaceJobs:
    def __init__(self, submit, cancel, forget):
        self._submit, self._cancel, self._forget = submit, cancel, forget
        self._pending = {}
        self._closed = False

    def start(self, lane, request, callback, failed, material, session):
        if self._closed:
            return
        for task, previous in list(self._pending.items()):
            if previous.lane is lane:
                self._cancel(task)
                self._forget(task)
                self._pending.pop(task)
        identity = lane.request(material, session)
        if identity is None:
            return
        frozen_input = deepcopy(request)
        self._pending[identity.task] = PendingSource(identity, lane, callback, failed)

        async def operation():
            return (
                await run_blocking(frozen_input)
                if isinstance(frozen_input, BlockingRequest)
                else await asyncio.to_thread(frozen_input)
            )

        try:
            self._submit(identity.task, operation)
        except RuntimeError as error:
            self.deliver(identity.task, None, str(error))

    def deliver(self, task, value, error):
        pending = self._pending.pop(task, None)
        if not pending:
            return False
        self._forget(task)
        if self._closed or not pending.lane.accepts(pending.identity):
            return False
        if error:
            pending.failed(error)
        else:
            pending.callback(value)
        return True

    def close(self):
        self._closed = True
        for task, pending in self._pending.items():
            pending.lane.close()
            self._cancel(task)
            self._forget(task)
        self._pending.clear()
