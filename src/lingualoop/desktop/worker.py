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

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
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
        if self._thread is None:
            self._thread = Thread(target=self._run, name="lingualoop-async", daemon=True)
            self._thread.start()
            if not self._ready.wait(5):
                raise RuntimeError(QCoreApplication.translate("Desktop", "后台任务启动失败。"))

        async def execute():
            try:
                result = await operation()
            except asyncio.CancelledError:
                if job_id and not self._closing:
                    self.jobCompleted.emit(job_id, None, "cancelled")
                return
            except Exception as exc:
                # Never forward HTTP request bodies, authentication or user data.
                status = getattr(exc, "status_code", None)
                if status == 402:
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

        return asyncio.run_coroutine_threadsafe(execute(), self._loop)

    def close(self, cleanup: AsyncOperation) -> None:
        if self._closing:
            return
        self._closing = True
        if self._loop is None:
            return

        async def shutdown():
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await cleanup()

        try:
            # RTC process shutdown and model-tree cleanup have their own bounded
            # waits; keep the loop alive long enough to close their pipe handles.
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(timeout=15)
        except Exception:
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._jobs.clear()
