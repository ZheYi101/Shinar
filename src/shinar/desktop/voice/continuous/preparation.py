"""Owned component preparation and storage scans, independent of the call state."""

import asyncio
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QCoreApplication

from shinar.infrastructure.blocking_jobs import BlockingRequest, run_blocking
from shinar.local_speech.installation import managed_status, runtime_plan
from shinar.local_speech.usage import storage_usage
from shinar.realtime.continuous_assets import VAD_PACKAGE, prepared_assets, server_package
from shinar.desktop.voice.continuous.state import CallEvent, PreparationSnapshot
from shinar.desktop.voice.continuous.ports import CallRuntimePort


class CallPreparation:
    def __init__(self, runtime: CallRuntimePort):
        self.runtime = runtime
        self._snapshot = PreparationSnapshot()
        self._cancel = Event()
        self._closed = False
        self._sizes = None
        self._storage = {}
        self._storage_generation = 0
        self._storage_pending = False
        self._job = ""

    @property
    def snapshot(self) -> PreparationSnapshot:
        return self._snapshot

    @property
    def assets_ready(self) -> bool:
        return prepared_assets(self.runtime.root)

    @property
    def environment_ready(self) -> bool:
        try:
            return managed_status(self.runtime.root, "rtc-cpu").get("prepared", False)
        except (ImportError, ValueError):
            return False

    def clear_status(self) -> None:
        self._snapshot = PreparationSnapshot()

    def start(self) -> None:
        if self._closed or self._snapshot.active:
            return
        self._cancel = Event()
        identity, root, cancel = uuid4().hex, self.runtime.root, self._cancel
        self._snapshot = PreparationSnapshot(identity, active=True, stage="speech_setup_bootstrap")
        self.runtime.notify()

        async def run():
            def emit(kind, value):
                self.runtime.emit(identity, "setup_" + kind, value)

            try:
                root.mkdir(parents=True, exist_ok=True)
                await run_blocking(
                    BlockingRequest("runtime", (root, "rtc-cpu")), cancel=cancel, on_event=emit
                )
                emit("stage", "speech_setup_vad")
                await run_blocking(
                    BlockingRequest("continuous_assets", (root,)), cancel=cancel, on_event=emit
                )
                emit("stage", "speech_setup_server")
                await run_blocking(
                    BlockingRequest("server", (root / "sfu",), {"download": True}),
                    cancel=cancel,
                    on_event=emit,
                )
                if not cancel.is_set():
                    emit("prepared", None)
            except asyncio.CancelledError:
                raise
            except Exception:
                emit("failed", None)

        self._job = self.runtime.post(run)

    def handle(self, event: CallEvent) -> bool:
        if event.kind == "setup_storage":
            root, generation, usage = event.value
            if (
                not self._closed
                and root == str(self.runtime.root)
                and generation == self._storage_generation
            ):
                self._storage_pending = False
                self._storage = usage
                self.runtime.storage_changed()
            return True
        if (
            self._closed
            or event.identity != self._snapshot.identity
            or not self._snapshot.active
            or self._cancel.is_set()
        ):
            return False
        if event.kind == "setup_stage":
            self._snapshot = replace(self._snapshot, stage=event.value, transfer=None)
        elif event.kind == "setup_transfer":
            self._snapshot = replace(self._snapshot, transfer=event.value)
        elif event.kind == "setup_progress":
            done, total = event.value
            notice = QCoreApplication.translate("Desktop", "当前文件：%1 / %2 MiB；整项准备尚未完成。")
            self._snapshot = replace(self._snapshot, notice=notice.replace("%1", f"{done / 1048576:.1f}").replace("%2", f"{total / 1048576:.1f}"))
        elif event.kind == "setup_prepared":
            self._snapshot = replace(
                self._snapshot,
                active=False,
                notice=QCoreApplication.translate("Desktop", "连续语音组件已准备。"),
            )
            self.invalidate_sizes()
            self.refresh_storage()
        elif event.kind == "setup_failed":
            self._snapshot = replace(
                self._snapshot,
                active=False,
                failed=True,
                error=QCoreApplication.translate(
                    "Desktop", "本机语音连接未建立，请在音频设备中检查连续语音组件后重试。"
                ),
            )
            self.invalidate_sizes()
            self.refresh_storage()
        else:
            return False
        if event.kind in {"setup_prepared", "setup_failed"}:
            self.runtime.components_changed()
        self.runtime.notify()
        return True

    def cancel(self) -> None:
        self._cancel.set()
        self.runtime.worker.cancel_job(self._job)
        self._snapshot = replace(self._snapshot, active=False, identity="")

    def invalidate_sizes(self) -> None:
        self._sizes = None

    def sizes(self) -> dict:
        if self._sizes is None:
            root = self.runtime.root
            plan = runtime_plan(root, "rtc-cpu")
            assets = [*VAD_PACKAGE.files, *server_package().files]
            pending = sum(a.size for a in assets if not (root / "downloads" / a.sha256).is_file())
            self._sizes = {
                "downloadMiB": (plan.download_bytes + pending) / 1024**2,
                "requiredFreeMiB": (plan.disk_bytes + sum(a.size * 3 for a in assets)) / 1024**2,
            }
        return dict(self._sizes)

    @property
    def storage(self) -> dict:
        return dict(self._storage)

    def refresh_storage(self) -> None:
        if self._closed or self._storage_pending:
            return
        self._storage_pending = True
        root, generation = self.runtime.root, self._storage_generation

        async def collect():
            try:
                usage = await asyncio.to_thread(storage_usage, root)
            except OSError:
                usage = {"incomplete": True}
            self.runtime.emit("", "setup_storage", (str(root), generation, usage))

        self.runtime.post(collect)

    def root_changed(self, root: Path) -> None:
        self.cancel()
        self._storage_generation += 1
        self._storage_pending = False
        self._storage = {}
        self.invalidate_sizes()
        self.runtime.storage_changed()
        self.runtime.components_changed()

    def close(self) -> None:
        self._closed = True
        self.cancel()
        self._storage_generation += 1
