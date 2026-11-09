"""Explicit, identity-checked cleanup of disposable speech preparation files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat

from .storage_inventory import StorageFile, scan_storage
from .storage_lease import StorageCancelledError, checked_root, is_reparse, storage_lease


class StoragePlanChangedError(RuntimeError):
    """The reviewed cache snapshot no longer names exactly these files."""


@dataclass(frozen=True)
class CleanupPlan:
    id: str
    root: str
    reclaimable_bytes: int
    files: tuple[StorageFile, ...]
    incomplete: bool

    @property
    def plan_id(self) -> str:
        return self.id

    def to_dict(self) -> dict:
        return {"planId": self.id, "root": self.root,
                "reclaimableBytes": self.reclaimable_bytes,
                "fileCount": len(self.files), "incomplete": self.incomplete,
                "logicalEstimate": True}


def plan_cleanup(root: Path) -> CleanupPlan:
    inventory = scan_storage(root)
    return CleanupPlan(inventory.plan_id, inventory.root, inventory.reclaimable_bytes,
                       tuple(file for file in inventory.files if file.cache_candidate),
                       inventory.incomplete)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise StorageCancelledError("speech_storage_cancelled")


def _check_file(root: Path, file: StorageFile) -> Path:
    path = root / file.relative_path
    checked_root(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise StoragePlanChangedError("speech_storage_plan_changed") from None
    if is_reparse(info) or not stat.S_ISREG(info.st_mode) or (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    ) != (file.device, file.inode, file.size, file.modified_ns):
        raise StoragePlanChangedError("speech_storage_plan_changed")
    return path


def _remove_empty_parents(root: Path, folders: set[Path]) -> None:
    for parent in sorted(folders, key=lambda path: len(path.parts), reverse=True):
        if parent == root:
            continue
        try:
            checked_root(parent)
            parent.rmdir()
        except OSError:
            pass  # A resume file, an excluded entry or another retained item remains.


def clean_storage(root: Path, expected_plan_id: str, cancel=None) -> dict:
    """Reject a stale plan before any deletion; never touch installed or resume files."""
    root = checked_root(root)
    _check_cancel(cancel)
    with storage_lease(root, exclusive=True, cancel=cancel):
        plan = plan_cleanup(root)
        if plan.incomplete or plan.id != expected_plan_id:
            raise StoragePlanChangedError("speech_storage_plan_changed")
        # Preflight the whole approved set before removing its first member.
        for file in plan.files:
            _check_cancel(cancel)
            _check_file(root, file)
        deleted, folders = 0, set()
        for file in plan.files:
            _check_cancel(cancel)
            path = _check_file(root, file)
            path.unlink()
            deleted += 1
            folders.update(parent for parent in path.parents if parent != root and root in parent.parents)
        _remove_empty_parents(root, folders)
        return {"planId": plan.id, "deletedFiles": deleted,
                "reclaimedBytes": plan.reclaimable_bytes, "logicalEstimate": True}
