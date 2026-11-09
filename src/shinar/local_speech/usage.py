"""Read-only file-size accounting for a speech cache, separate from RAM budgets."""

from __future__ import annotations

from pathlib import Path
import stat

from .storage_inventory import scan_storage
from .storage_lease import (
    StorageBusyError, StorageMovedError, checked_root, is_reparse,
)


def cached_model_bytes(root: Path, artifacts) -> int:
    try:
        directory = checked_root(root / "downloads")
    except (OSError, ValueError):
        return 0
    total = 0
    for checksum in {artifact.sha256 for artifact in artifacts}:
        for suffix in ("", ".part"):
            path = directory / (checksum + suffix)
            try:
                info = path.lstat()
                if not is_reparse(info) and stat.S_ISREG(info.st_mode):
                    total += info.st_size
            except OSError:
                pass  # A concurrent transfer may rename its partial file.
    return total


def storage_usage(root: Path) -> dict:
    """Count logical file bytes once per hard link; never follow external links.

    Run on a background worker. This is a snapshot, not allocated NTFS sectors,
    a prediction of final installation size, or a process-memory measurement.
    """
    try:
        inventory = scan_storage(root)
    except (OSError, ValueError, StorageBusyError, StorageMovedError):
        return {"installedMiB": 0.0, "cacheMiB": 0.0, "otherMiB": 0.0,
                "totalMiB": 0.0, "incomplete": True}
    sizes = {"installed": inventory.installed_bytes, "cache": inventory.cache_bytes,
             "other": inventory.other_bytes}
    return {
        **{key + "MiB": round(value / 1024**2, 1) for key, value in sizes.items()},
        "totalMiB": round(inventory.total_bytes / 1024**2, 1),
        "incomplete": inventory.incomplete,
    }
