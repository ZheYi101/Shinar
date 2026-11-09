"""Parent-side isolated RTC/DSP process, on the application's asyncio worker."""

import asyncio
from contextlib import ExitStack
from pathlib import Path
import sys
import os
import subprocess
from uuid import uuid4
from collections.abc import Callable
from typing import Any

from shinar.local_speech.runtime import child_environment
from shinar.local_speech.processes import terminate_tree
from shinar.local_speech.storage_lease import checked_root, storage_lease
from .audio_ipc import encode_message, read_message


class AudioSessionProcess:
    def __init__(
        self,
        voice_session_id: str,
        on_event: Callable[[dict, bytes], None],
        *,
        python: str | None = None,
    ) -> None:
        self.id, self.on_event = voice_session_id, on_event
        self.python = python or sys.executable
        self.process = self.reader = None
        self.pending = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._spawn_task = None
        self._close_task = None
        self._storage_roots: tuple[Path, ...] = ()
        self._storage_leases = None

    @property
    def storage_roots(self) -> tuple[Path, ...]:
        return self._storage_roots

    def configure_storage(self, roots) -> None:
        """Freeze the directories used by this process before it is spawned."""
        if self._spawn_task is not None or self._closed:
            raise RuntimeError("audio_worker_already_started")
        self._storage_roots = tuple(dict.fromkeys(checked_root(Path(root)) for root in roots))

    def _retain_storage(self) -> None:
        if self._storage_leases is not None:
            return
        with ExitStack() as leases:
            for root in self._storage_roots:
                leases.enter_context(storage_lease(root))
            self._storage_leases = leases.pop_all()

    def _release_storage(self) -> None:
        if self._storage_leases is not None:
            leases, self._storage_leases = self._storage_leases, None
            leases.close()

    async def start(self, config: dict) -> dict:
        if self._closed or self._close_task:
            raise RuntimeError("audio_worker_closed")
        self._retain_storage()
        try:
            return await self._start(config)
        except BaseException:
            await self.close()
            raise

    async def _start(self, config: dict) -> dict:
        # Absolute bootstrap works in a checkout and a wheel, without relying on PYTHONPATH.
        self._spawn_task = asyncio.create_task(
            asyncio.create_subprocess_exec(
                self.python,
                str(Path(__file__).with_name("audio_worker.py")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=child_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                limit=256 * 1024,
            )
        )
        try:
            self.process = await asyncio.shield(self._spawn_task)
        except asyncio.CancelledError:
            self.process = await self._spawn_task
            await self.close()
            raise
        if self._closed or self._close_task:
            await self.close()
            raise RuntimeError("audio_worker_closed")
        self.reader = asyncio.create_task(self._read())
        return await self.request("start", config=config, timeout=40)

    async def send(self, kind: str, payload: bytes = b"", **fields) -> None:
        if self._closed or not self.process or self.process.returncode is not None:
            raise RuntimeError("audio_worker_closed")
        async with self._lock:
            self.process.stdin.write(
                encode_message({"kind": kind, "voice_session": self.id, **fields}, payload)
            )
            await self.process.stdin.drain()

    async def request(
        self, kind: str, payload: bytes = b"", *, timeout: float = 10, **fields: Any
    ) -> dict:
        if self.reader is not None and self.reader.done():
            raise RuntimeError("audio_worker_disconnected")
        operation = uuid4().hex
        result = asyncio.get_running_loop().create_future()
        self.pending[operation] = result
        try:
            await self.send(kind, payload, operation=operation, **fields)
            async with asyncio.timeout(timeout):
                return await result
        finally:
            self.pending.pop(operation, None)

    async def _read(self):
        try:
            while True:
                event, payload = await read_message(self.process.stdout)
                if event.get("voice_session") != self.id:
                    continue
                operation = event.get("operation")
                if operation in self.pending:
                    future = self.pending[operation]
                    if not future.done():
                        if event.get("error"):
                            future.set_exception(RuntimeError(event["error"]))
                        else:
                            future.set_result(event)
                elif not self._closed:
                    self.on_event(event, payload)
        except (Exception, asyncio.CancelledError):
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("audio_worker_disconnected"))
            if not self._closed:
                self.on_event({"kind": "disconnected", "voice_session": self.id}, b"")

    async def close(self) -> None:
        if self._close_task:
            await asyncio.shield(self._close_task)
            return
        self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        try:
            await self._close_resources()
        finally:
            if self.process is None or self.process.returncode is not None:
                self._release_storage()

    async def _close_resources(self):
        if self._closed:
            return
        if self._spawn_task and self.process is None:
            try:
                self.process = await asyncio.shield(self._spawn_task)
            except Exception:
                return
        try:
            if (
                self.process
                and self.process.returncode is None
                and self.reader
                and not self.reader.done()
            ):
                try:
                    await self.request("close", timeout=3)
                except Exception:
                    pass
        finally:
            self._closed = True
            if self.process:
                if self.process.stdin:
                    self.process.stdin.close()
                try:
                    async with asyncio.timeout(3):
                        await self.process.wait()
                except TimeoutError:
                    await asyncio.to_thread(terminate_tree, self.process.pid)
                    await self.process.wait()
            if self.reader:
                self.reader.cancel()
                await asyncio.gather(self.reader, return_exceptions=True)
            if self.process:
                if self.process.stdin:
                    try:
                        await self.process.stdin.wait_closed()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                transport = getattr(self.process, "_transport", None)
                if transport:
                    transport.close()
