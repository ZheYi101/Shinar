"""Cross-process maintenance leases for one managed speech directory."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import stat
import threading
import time


class StorageBusyError(RuntimeError):
    """An active model operation or maintenance owns the directory."""


class StorageCancelledError(RuntimeError):
    """The caller cancelled while waiting for a maintenance lease."""


class StorageMovedError(RuntimeError):
    """A committed migration retired this directory for new operations."""

    def __init__(self, destination: str):
        super().__init__("speech_storage_moved")
        self.destination = destination


@dataclass
class _HeldLease:
    stream: object
    exclusive: bool
    depth: int = 1


_held = threading.local()
_registry_lock = threading.RLock()


def checked_root(root: Path) -> Path:
    """Reject reparse points before resolving any user-supplied ancestor."""
    absolute = Path(os.path.abspath(root))
    for path in (*reversed(absolute.parents), absolute):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if is_reparse(info):
            raise ValueError("speech_storage_link_unsupported")
    return absolute


def is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _retired_destination(root: Path) -> str:
    try:
        marker = json.loads((root / ".storage-moved.json").read_text("utf-8"))
        destination, config_path = marker["destination"], marker["config_path"]
        if not isinstance(destination, str) or not isinstance(config_path, str):
            return ""
        config = json.loads(Path(config_path).read_text("utf-8"))
        saved = config.get("speech_directory")
        if isinstance(saved, str) and os.path.normcase(os.path.abspath(saved)) == (
            os.path.normcase(os.path.abspath(destination))
        ):
            return destination
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return ""


def _windows_lock(stream, exclusive: bool, *, unlock=False) -> None:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
    overlap = Overlapped()
    if unlock:
        function = kernel.UnlockFileEx
        function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(Overlapped)]
        arguments = (handle, 0, 1, 0, ctypes.byref(overlap))
    else:
        function = kernel.LockFileEx
        function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
        arguments = (handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlap))
    function.restype = wintypes.BOOL
    if not function(*arguments):
        error = ctypes.get_last_error()
        if error in {32, 33, 158, 997} and not unlock:
            raise BlockingIOError(errno.EACCES, "speech_storage_busy")
        raise ctypes.WinError(error)


def _file_lock(stream, exclusive: bool, *, unlock=False) -> None:
    if os.name == "nt":
        _windows_lock(stream, exclusive, unlock=unlock)
    else:
        import fcntl

        flag = fcntl.LOCK_UN if unlock else (
            (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        )
        fcntl.flock(stream, flag)


def _acquire(stream, root, exclusive, wait, cancel, on_wait):
    while True:
        if cancel is not None and cancel.is_set():
            raise StorageCancelledError("speech_storage_cancelled")
        if not exclusive and (destination := _retired_destination(root)):
            raise StorageMovedError(destination)
        try:
            _file_lock(stream, exclusive)
            if not exclusive and (destination := _retired_destination(root)):
                _file_lock(stream, exclusive, unlock=True)
                raise StorageMovedError(destination)
            return
        except BlockingIOError as error:
            if not wait:
                raise StorageBusyError("speech_storage_busy") from error
            on_wait()
            if cancel is not None:
                cancel.wait(0.05)
            else:
                time.sleep(0.05)


@contextmanager
def storage_lease(
    root: Path, *, exclusive=False, wait=False, cancel=None, on_wait=lambda: None
):
    """Shared operations coexist; maintenance excludes every participating process.

    Reentrancy belongs to the current thread. An exclusive owner may nest shared
    operations, including model preparation. Upgrading a shared owner is rejected.
    """
    root = checked_root(root)
    key = os.path.normcase(str(root))
    leases = getattr(_held, "leases", None)
    if leases is None:
        leases = _held.leases = {}
    with _registry_lock:
        lease = leases.get(key)
        if lease is not None:
            if exclusive and not lease.exclusive:
                raise StorageBusyError("speech_storage_busy")
            lease.depth += 1
    if lease is None:
        root.mkdir(parents=True, exist_ok=True)
        checked_root(root)
        lock = root / ".storage.lock"
        try:
            if is_reparse(lock.lstat()):
                raise ValueError("speech_storage_link_unsupported")
        except FileNotFoundError:
            pass
        stream = lock.open("a+b")
        try:
            _acquire(stream, root, exclusive, wait, cancel, on_wait)
        except BaseException:
            stream.close()
            raise
        lease = _HeldLease(stream, bool(exclusive))
        with _registry_lock:
            leases[key] = lease
    try:
        yield root
    finally:
        with _registry_lock:
            lease.depth -= 1
            if lease.depth == 0:
                del leases[key]
                try:
                    _file_lock(lease.stream, lease.exclusive, unlock=True)
                finally:
                    lease.stream.close()
