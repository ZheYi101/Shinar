"""One application worker, one asyncio loop, GUI delivery through queued signals."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from threading import Event, Thread
from typing import Any

from PySide6.QtCore import QObject, Signal, QCoreApplication

AsyncOperation = Callable[[], Awaitable[Any]]


class AsyncWorker(QObject):
    completed = Signal(object, str)
    jobCompleted = Signal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready = Event()
        self._loop = None
        self._thread = None
        self._closing = False
        self._jobs = {}
        self._shutdown_future = None

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        self._loop.run_until_complete(self._loop.shutdown_default_executor())
        self._loop.close()

    def submit(self, operation: AsyncOperation) -> Future:
        return self._submit(operation)

    def submit_job(self, job_id: str, operation: AsyncOperation) -> Future:
        """Deliver an identified operation without using the legacy callback."""
        if job_id in self._jobs:
            raise ValueError("duplicate_worker_job")
        future = self._submit(operation, job_id)
        self._jobs[job_id] = future
        return future

    def cancel_job(self, job_id: str) -> None:
        future = self._jobs.get(job_id)
        if future:
            future.cancel()

    def forget_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    def _submit(self, operation, job_id=None):
        if self._closing:
            raise RuntimeError(QCoreApplication.translate("Desktop", "应用正在关闭。"))
        self._start()

        async def execute():
            await self._execute(operation, job_id)

        return asyncio.run_coroutine_threadsafe(execute(), self._loop)

    def _start(self):
        if self._thread is None:
            self._thread = Thread(target=self._run, name="lingualoop-async", daemon=True)
            self._thread.start()
            if not self._ready.wait(5):
                raise RuntimeError(QCoreApplication.translate("Desktop", "后台任务启动失败。"))

    async def _execute(self, operation, job_id):
        try:
            result = await operation()
        except asyncio.CancelledError:
            if job_id and not self._closing:
                self.jobCompleted.emit(job_id, None, "cancelled")
            return
        except Exception as exc:
            # Never forward HTTP request bodies, authentication or user data.
            status = getattr(exc, "status_code", None)
            if str(exc) == "ai_service_unconfigured":
                message = QCoreApplication.translate(
                    "Desktop",
                    "AI 服务尚未配置。请在设置 → 模型与服务中保存连接信息，然后退出并重新打开软件。",
                )
            elif status == 402:
                message = QCoreApplication.translate(
                    "Desktop",
                    "模型服务余额不足（HTTP 402）。已保存的材料和段落会保留，补充服务余额后可继续整理或对话。",
                )
            elif status == 401:
                message = QCoreApplication.translate(
                    "Desktop", "模型服务认证失败（HTTP 401）。请检查本地 API Key 后重试。"
                )
            elif status == 429:
                message = QCoreApplication.translate(
                    "Desktop", "模型服务暂时限流（HTTP 429）。内容已保留，请稍后重试。"
                )
            else:
                message = (
                    str(exc)
                    if isinstance(exc, (ValueError, RuntimeError))
                    else QCoreApplication.translate(
                        "Desktop", "请求未完成，请检查网络、模型配置后重试。"
                    )
                )
            if not self._closing:
                if job_id:
                    self.jobCompleted.emit(job_id, None, message)
                else:
                    self.completed.emit(None, message)
        else:
            if not self._closing:
                if job_id:
                    self.jobCompleted.emit(job_id, result, "")
                else:
                    self.completed.emit(result, "")

    def begin_shutdown(self, cleanup: AsyncOperation) -> Future:
        if self._shutdown_future is not None:
            if not self._shutdown_future.done() or self._shutdown_future.exception() is None:
                return self._shutdown_future
            self._shutdown_future = None
        self._start()
        self._closing = True

        async def shutdown():
            pending = [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
                and not getattr(task, "_lingualoop_cleanup", False)
            ]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await cleanup()
            await self._loop.shutdown_asyncgens()
            await self._loop.shutdown_default_executor()

        self._shutdown_future = asyncio.run_coroutine_threadsafe(shutdown(), self._loop)
        return self._shutdown_future

    def finish_shutdown(self) -> bool:
        if self._thread is None or not self._thread.is_alive():
            return True
        if self._shutdown_future is None or not self._shutdown_future.done():
            return False
        self._shutdown_future.result()
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=0.01)
        self._jobs.clear()
        return not self._thread.is_alive()

    def close(self, cleanup: AsyncOperation) -> None:
        """Synchronous fallback for tests and external application teardown."""
        self.begin_shutdown(cleanup).result(timeout=15)
        from time import monotonic, sleep

        deadline = monotonic() + 1
        while not self.finish_shutdown():
            if monotonic() >= deadline:
                raise RuntimeError("background_worker_shutdown_failed")
            sleep(0.01)
