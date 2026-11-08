"""Bounded, independently cancellable model preparation jobs for QML."""

from __future__ import annotations

from shinar.desktop.tasks.preparation_progress import preparation_error, preparation_error_text, preparation_phase_text, preparation_transfer_text

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractListModel,
    QCoreApplication,
    QModelIndex,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from shinar.local_speech.downloads import DownloadCancelled, TransferEvent

PreparationOperation = Callable[
    [Event, Callable[[str], None], Callable[[TransferEvent], None]], None
]










@dataclass
class PreparationJob:
    model_id: str
    name: str
    task: str
    language: str
    operation: PreparationOperation
    id: str = field(default_factory=lambda: uuid4().hex)
    cancel: Event = field(default_factory=Event)
    state: str = "queued"
    stage: str = ""
    component: str = ""
    phase: str = ""
    completed: int = 0
    total: int = 0
    speed: float = 0
    sampled_at: float = 0
    sampled_bytes: int = 0
    error: str = ""
    thread: Thread | None = None


class SpeechPreparationJobs(QAbstractListModel):
    activityChanged = Signal()
    finished = Signal(str)
    _done = Signal(str, str)
    ROLES = (
        "jobId",
        "modelId",
        "name",
        "task",
        "language",
        "state",
        "phaseText",
        "component",
        "completedBytes",
        "totalBytes",
        "progress",
        "transferText",
        "errorText",
        "errorCode",
        "active",
    )
    TERMINAL = {"completed", "cancelled", "failed"}

    def __init__(self, parent=None, *, concurrency: int = 3):
        super().__init__(parent)
        self.concurrency = concurrency
        self._jobs: list[PreparationJob] = []
        self._rows: list[dict] = []
        self._lock = Lock()
        self._closing = False
        self._done.connect(self._finish)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._publish)

    def roleNames(self):
        return {
            Qt.ItemDataRole.UserRole + i + 1: role.encode() for i, role in enumerate(self.ROLES)
        }

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        offset = role - Qt.ItemDataRole.UserRole - 1
        if not index.isValid() or not 0 <= offset < len(self.ROLES):
            return None
        return self._rows[index.row()].get(self.ROLES[offset])

    def rows(self) -> list[dict]:
        return [dict(row) for row in self._rows]

    @property
    def active_count(self) -> int:
        return sum(job.state not in self.TERMINAL for job in self._jobs)

    def contains_active(self, model_id: str) -> bool:
        return any(
            job.model_id == model_id and job.state not in self.TERMINAL for job in self._jobs
        )

    def enqueue(
        self, model_id: str, name: str, task: str, language: str, operation: PreparationOperation
    ) -> str:
        for job in self._jobs:
            if job.model_id == model_id and job.state not in self.TERMINAL:
                return job.id
        if self._closing:
            return ""
        # Replace only old terminal rows for this model; active controls stay stable.
        for i in reversed(range(len(self._jobs))):
            if self._jobs[i].model_id == model_id or (
                len(self._jobs) >= 24 and self._jobs[i].state in self.TERMINAL
            ):
                self.beginRemoveRows(QModelIndex(), i, i)
                self._jobs.pop(i)
                self._rows.pop(i)
                self.endRemoveRows()
        job = PreparationJob(model_id, name, task.upper(), language, operation)
        position = len(self._jobs)
        self.beginInsertRows(QModelIndex(), position, position)
        self._jobs.append(job)
        self._rows.append(self._view(job))
        self.endInsertRows()
        self._schedule()
        self.activityChanged.emit()
        return job.id

    def _schedule(self):
        running = sum(job.state in {"running", "cancelling"} for job in self._jobs)
        for job in self._jobs:
            if running >= self.concurrency or self._closing:
                break
            if job.state != "queued":
                continue
            job.state = "running"
            job.thread = Thread(
                target=self._run, args=(job,), daemon=True, name="speech-prepare-" + job.id[:8]
            )
            job.thread.start()
            running += 1
        self._publish()
        if self.active_count:
            self._timer.start()

    def _run(self, job):
        def stage(value):
            with self._lock:
                job.stage, job.component, job.phase = value, "", ""
                job.completed = job.total = 0

        def transfer(event: TransferEvent):
            with self._lock:
                now = monotonic()
                if event.component != job.component or event.completed < job.completed:
                    job.sampled_at, job.sampled_bytes, job.speed = now, event.completed, 0
                elif now - job.sampled_at >= 0.3:
                    job.speed = max(0, event.completed - job.sampled_bytes) / (now - job.sampled_at)
                    job.sampled_at, job.sampled_bytes = now, event.completed
                job.component, job.phase = event.component, event.phase
                job.completed, job.total = event.completed, event.total

        error = ""
        try:
            job.operation(job.cancel, stage, transfer)
            if job.cancel.is_set():
                raise DownloadCancelled()
        except Exception as exc:
            error = preparation_error(exc)
        if not self._closing:
            self._done.emit(job.id, error)

    @Slot(str, str)
    def _finish(self, job_id, error):
        if self._closing:
            return
        job = next((j for j in self._jobs if j.id == job_id), None)
        if job is None:
            return
        job.error = error
        job.state = (
            "cancelled" if error == "speech_setup_cancelled" else "failed" if error else "completed"
        )
        self._schedule()
        if not self.active_count:
            self._timer.stop()
        self.activityChanged.emit()
        self.finished.emit(job_id)

    @Slot(str)
    def cancel(self, job_id):
        job = next((j for j in self._jobs if j.id == job_id), None)
        if job is None or job.state in self.TERMINAL:
            return
        job.cancel.set()
        if job.state == "queued":
            self._finish(job.id, "speech_setup_cancelled")
        else:
            job.state = "cancelling"
            self._publish()

    @Slot(str)
    def retry(self, job_id):
        job = next((j for j in self._jobs if j.id == job_id), None)
        if job and job.state in {"failed", "cancelled"}:
            self.enqueue(job.model_id, job.name, job.task, job.language, job.operation)

    @Slot()
    def clearFinished(self):
        for i in reversed(range(len(self._jobs))):
            if self._jobs[i].state in self.TERMINAL:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._jobs.pop(i)
                self._rows.pop(i)
                self.endRemoveRows()

    def _view(self, job):
        phases = {
            "queued": QCoreApplication.translate("Desktop", "等待下载名额"),
            "cancelling": QCoreApplication.translate("Desktop", "正在取消…"),
            "completed": QCoreApplication.translate("Desktop", "准备完成，可测速并选用"),
            "cancelled": QCoreApplication.translate("Desktop", "已取消，可继续"),
            "failed": QCoreApplication.translate("Desktop", "准备失败"),
        }
        phase = job.state if job.state != "running" else job.phase or job.stage
        phase_text = phases.get(phase) or preparation_phase_text(phase)
        if job.state == "running" and job.phase and job.stage:
            phase_text = preparation_phase_text(job.stage) + " · " + phase_text
        progress = job.completed / job.total if job.total else 0
        text = preparation_transfer_text(job.completed, job.total)
        if job.total:
            if job.speed and job.phase == "downloading":
                text += QCoreApplication.translate("Desktop", " · %1 MiB/s").replace(
                    "%1", f"{job.speed / 1024**2:.1f}"
                )
        return dict(
            jobId=job.id,
            modelId=job.model_id,
            name=job.name,
            task=job.task,
            language=job.language,
            state=job.state,
            phaseText=phase_text,
            component=job.component,
            completedBytes=job.completed,
            totalBytes=job.total,
            progress=progress,
            transferText=text,
            errorText=preparation_error_text(job.error) if job.error else "",
            errorCode=job.error,
            active=job.state not in self.TERMINAL,
        )

    def _publish(self):
        with self._lock:
            for i, job in enumerate(self._jobs):
                value = self._view(job)
                if value != self._rows[i]:
                    self._rows[i] = value
                    index = self.index(i, 0)
                    self.dataChanged.emit(index, index)

    def begin_shutdown(self):
        self._closing = True
        self._timer.stop()
        for job in self._jobs:
            job.cancel.set()

    def finish_shutdown(self) -> bool:
        return all(job.thread is None or not job.thread.is_alive() for job in self._jobs)

    def close(self):
        self.begin_shutdown()
        # Give installer subprocesses time to observe cancellation and terminate.
        deadline = monotonic() + 2
        for job in self._jobs:
            if job.thread:
                job.thread.join(timeout=max(0, deadline - monotonic()))
