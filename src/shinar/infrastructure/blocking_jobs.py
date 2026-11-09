"""Owned, cancellable process boundary for document and installation work.

Only named package operations and plain data cross this boundary. The child
never receives a QObject, a database connection or a learning-state writer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import multiprocessing as mp
import re
from time import monotonic
from typing import Any, Callable
from weakref import WeakKeyDictionary

_slots = WeakKeyDictionary()


@dataclass(frozen=True)
class BlockingRequest:
    operation: str
    args: tuple = ()
    options: dict | None = None


def _execute(request: BlockingRequest, cancel, emit):
    options = dict(request.options or {})
    if request.operation == "import":
        from shinar.infrastructure.material_import import import_material_file

        return import_material_file(*request.args, **options)
    if request.operation == "index":
        from shinar.core.knowledge_context import build_turn_index

        return build_turn_index(*request.args)
    if request.operation == "save_source":
        from shinar.infrastructure.epub_reader import save_epub_asset

        return save_epub_asset(*request.args)
    if request.operation == "source":
        from shinar.application.source_loading import load_source

        return load_source(*request.args, **options)
    if request.operation == "search":
        from shinar.application.source_loading import search_source

        return search_source(*request.args, **options)
    if request.operation == "runtime":
        from shinar.local_speech.installation import prepare_managed_runtime

        return prepare_managed_runtime(
            *request.args,
            **options,
            cancel=cancel,
            stage=lambda value: emit("stage", value),
            progress=lambda done, total: emit("progress", (done, total)),
            on_transfer=lambda value: emit("transfer", value),
        )
    if request.operation == "continuous_assets":
        from shinar.realtime.continuous_assets import prepare_assets

        return prepare_assets(
            *request.args,
            **options,
            cancel=cancel,
            on_transfer=lambda value: emit("transfer", value),
        )
    if request.operation == "continuous_reuse":
        from shinar.realtime.storage_upgrade import reuse_legacy_assets

        return reuse_legacy_assets(*request.args, cancel=cancel)
    if request.operation == "server":
        from shinar.realtime.local_server import ensure_server

        return ensure_server(
            *request.args,
            **options,
            cancel=cancel,
            on_transfer=lambda value: emit("transfer", value),
        )
    if request.operation.startswith("speech_storage_"):
        return _storage_operation(request, cancel, emit)
    raise ValueError("unknown_blocking_operation")


def _storage_operation(request, cancel, emit):
    from shinar.local_speech.storage_inventory import scan_storage

    if request.operation == "speech_storage_scan":
        return scan_storage(*request.args).to_dict()
    if request.operation == "speech_storage_clean":
        from shinar.local_speech.storage_cleanup import clean_storage

        return clean_storage(*request.args, cancel=cancel)
    if request.operation == "speech_storage_preview":
        from shinar.local_speech.storage_migration import preview_migration

        return preview_migration(*request.args).to_dict()
    if request.operation == "speech_storage_migrate":
        from shinar.local_speech.storage_migration import migrate_storage

        last_stage = None

        def stage(value):
            nonlocal last_stage
            if value != last_stage:
                last_stage = value
                emit("stage", value)

        return migrate_storage(
            *request.args, **dict(request.options or {}), cancel=cancel,
            on_stage=stage,
        )
    raise ValueError("unknown_blocking_operation")


def _child(connection, cancel, request):
    try:
        result = _execute(request, cancel, lambda kind, value: connection.send((kind, value)))
        connection.send(("result", result))
    except BaseException as error:
        # Provider bodies, source content and paths are not diagnostics.
        code = str(error)
        connection.send(
            (
                "error",
                (
                    type(error).__name__,
                    code
                    if re.fullmatch(r"speech_[a-z_]+", code)
                    else "background_operation_failed",
                ),
            )
        )
    finally:
        connection.close()


async def _stop(process, cancel, grace: float) -> None:
    cancel.set()
    deadline = monotonic() + grace
    while process.is_alive() and monotonic() < deadline:
        await asyncio.sleep(0.02)
    if process.is_alive():
        from shinar.local_speech.processes import terminate_tree

        await asyncio.to_thread(terminate_tree, process.pid)
    process.join(timeout=0)
    if process.is_alive():
        raise RuntimeError("background_process_shutdown_failed")


async def _run_owned(
    request: BlockingRequest,
    *,
    on_event: Callable[[str, Any], None] | None = None,
    cancel=None,
) -> Any:
    """Cancellation waits for the actual owned process, including its children."""
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    stopped = context.Event()
    process = context.Process(target=_child, args=(sender, stopped, request), daemon=False)
    process.start()
    sender.close()
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            if receiver.poll():
                kind, value = receiver.recv()
                if kind == "result":
                    return value
                if kind == "error":
                    raise RuntimeError(value[1])
                if on_event:
                    on_event(kind, value)
            elif not process.is_alive():
                raise RuntimeError("background_process_exited")
            else:
                await asyncio.sleep(0.01)
    finally:
        try:
            cleanup = asyncio.create_task(_stop(process, stopped, 5))
            cleanup._shinar_cleanup = True
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
        finally:
            receiver.close()
            if not process.is_alive():
                process.close()


async def run_blocking(
    request: BlockingRequest,
    *,
    on_event: Callable[[str, Any], None] | None = None,
    cancel=None,
) -> Any:
    loop = asyncio.get_running_loop()
    slots = _slots.setdefault(loop, asyncio.Semaphore(2))
    async with slots:
        return await _run_owned(request, on_event=on_event, cancel=cancel)


def prepare_runtime_owned(
    root,
    runtime_id,
    *,
    cancel=None,
    stage=lambda value: None,
    progress=lambda done, total: None,
    on_transfer=lambda value: None,
    **options,
):
    """Synchronous adapter for the existing bounded speech preparation threads."""

    def event(kind, value):
        if kind == "stage":
            stage(value)
        elif kind == "progress":
            progress(*value)
        elif kind == "transfer":
            on_transfer(value)

    try:
        return asyncio.run(
            run_blocking(
                BlockingRequest("runtime", (root, runtime_id), options),
                on_event=event,
                cancel=cancel,
            )
        )
    except asyncio.CancelledError:
        from shinar.local_speech.downloads import DownloadCancelled

        raise DownloadCancelled("speech_setup_cancelled") from None
