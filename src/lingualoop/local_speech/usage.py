"""Read-only file-size accounting for a speech cache, separate from RAM budgets."""

from __future__ import annotations

import os
from pathlib import Path


def cached_model_bytes(root: Path, artifacts) -> int:
    total = 0
    for checksum in {artifact.sha256 for artifact in artifacts}:
        for suffix in ("", ".part"):
            path = root / "downloads" / (checksum + suffix)
            try:
                if not path.is_symlink() and path.is_file():
                    total += path.stat().st_size
            except OSError:
                pass  # A concurrent transfer may rename its partial file.
    return total


def storage_usage(root: Path) -> dict:
    """Count logical file bytes once per hard link; never follow external links.

    Run on a background worker. This is a snapshot, not allocated NTFS sectors,
    a prediction of final installation size, or a process-memory measurement.
    """
    sizes = {"installed": 0, "cache": 0, "other": 0}
    seen = set()
    incomplete = False
    if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        return {"installedMiB": 0.0, "cacheMiB": 0.0, "otherMiB": 0.0,
                "totalMiB": 0.0, "incomplete": True}
    if not root.exists():
        return {"installedMiB": 0.0, "cacheMiB": 0.0, "otherMiB": 0.0,
                "totalMiB": 0.0, "incomplete": False}

    def failed(_error):
        nonlocal incomplete
        incomplete = True

    installed_folders = {"models", "runtimes", "bootstrap", "sfu"}
    for folder, directories, filenames in os.walk(root, followlinks=False, onerror=failed):
        parent = Path(folder)
        # Attribute links shared by installed files and caches to the installation;
        # deleting the cache link alone would not reclaim those bytes.
        order = sorted(directories, key=lambda name: (name not in installed_folders, name))
        directories[:] = [name for name in order if not (
            (parent / name).is_symlink()
            or getattr(parent / name, "is_junction", lambda: False)()
        )]
        for name in filenames:
            path = parent / name
            try:
                if path.is_symlink():
                    continue
                info = path.stat()
                identity = (info.st_dev, info.st_ino)
                if info.st_ino and identity in seen:
                    continue
                if info.st_ino:
                    seen.add(identity)
                category = path.relative_to(root).parts[0]
                group = (
                    "cache" if category in {"downloads", "wheelhouses", "installer-cache"}
                    else "installed" if category in installed_folders
                    else "other"
                )
                sizes[group] += info.st_size
            except OSError:
                incomplete = True
    return {
        **{key + "MiB": round(value / 1024**2, 1) for key, value in sizes.items()},
        "totalMiB": round(sum(sizes.values()) / 1024**2, 1),
        "incomplete": incomplete,
    }
