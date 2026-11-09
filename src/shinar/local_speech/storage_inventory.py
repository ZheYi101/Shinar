"""Immutable logical-byte accounting and cache identities for maintenance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .storage_lease import checked_root, is_reparse, storage_lease


CACHE_FOLDERS = frozenset({"downloads", "wheelhouses", "installer-cache"})
INSTALLED_FOLDERS = frozenset({"models", "runtimes", "bootstrap", "sfu"})
_BLOB_NAME = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class StorageFile:
    relative_path: str
    size: int
    device: int
    inode: int
    links: int
    modified_ns: int

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode

    @property
    def cache_candidate(self) -> bool:
        parts = self.relative_path.split("/")
        if len(parts) < 2 or parts[0] not in CACHE_FOLDERS:
            return False
        return parts[0] != "downloads" or (
            len(parts) == 2 and _BLOB_NAME.fullmatch(parts[1]) is not None
        )


@dataclass(frozen=True)
class StorageCategory:
    name: str
    logical_bytes: int
    unique_bytes: int
    files: int

    def to_dict(self) -> dict:
        return {"name": self.name, "logicalBytes": self.logical_bytes,
                "uniqueBytes": self.unique_bytes, "fileCount": self.files}


@dataclass(frozen=True)
class StorageInventory:
    root: str
    root_identity: tuple[int, int]
    plan_id: str
    total_bytes: int
    installed_bytes: int
    cache_bytes: int
    other_bytes: int
    reclaimable_bytes: int
    categories: tuple[StorageCategory, ...]
    files: tuple[StorageFile, ...]
    excluded: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def incomplete(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict:
        return {
            "root": self.root, "planId": self.plan_id, "totalBytes": self.total_bytes,
            "installedBytes": self.installed_bytes, "cacheBytes": self.cache_bytes,
            "otherBytes": self.other_bytes, "reclaimableBytes": self.reclaimable_bytes,
            "categories": [category.to_dict() for category in self.categories],
            "fileCount": len(self.files), "excludedCount": len(self.excluded),
            "incomplete": self.incomplete, "logicalEstimate": True,
        }


def _file_record(path: Path, relative: str, info) -> StorageFile:
    return StorageFile(relative, info.st_size, info.st_dev, info.st_ino,
                       info.st_nlink, info.st_mtime_ns)


def _walk(root: Path) -> tuple[tuple[StorageFile, ...], tuple[str, ...], tuple[str, ...]]:
    files, excluded, errors = [], [], []
    pending = [root]
    while pending:
        parent = pending.pop()
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    if relative == ".storage.lock":
                        continue
                    try:
                        info = os.stat(path, follow_symlinks=False)
                        if is_reparse(info):
                            excluded.append(relative)
                        elif stat.S_ISDIR(info.st_mode):
                            pending.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            if not info.st_ino:
                                errors.append(relative + ":file_identity_unavailable")
                            files.append(_file_record(path, relative, info))
                        else:
                            excluded.append(relative)
                    except OSError as error:
                        errors.append(relative + ":" + type(error).__name__)
        except OSError as error:
            errors.append(parent.relative_to(root).as_posix() + ":" + type(error).__name__)
    return (tuple(sorted(files, key=lambda item: item.relative_path)),
            tuple(sorted(excluded)), tuple(sorted(errors)))


def _group_name(file: StorageFile) -> str:
    return file.relative_path.split("/", 1)[0]


def _category(name: str) -> str:
    return "installed" if name in INSTALLED_FOLDERS else (
        "cache" if name in CACHE_FOLDERS else "other"
    )


def _counts(files: tuple[StorageFile, ...]):
    identities, groups = defaultdict(list), defaultdict(list)
    for file in files:
        identities[file.identity].append(file)
        groups[_group_name(file)].append(file)
    totals, reclaimable = {"installed": 0, "cache": 0, "other": 0}, 0
    priorities = {"installed": 0, "other": 1, "cache": 2}
    for aliases in identities.values():
        category = min((_category(_group_name(file)) for file in aliases), key=priorities.get)
        totals[category] += aliases[0].size
        if all(file.cache_candidate for file in aliases) and len(aliases) == aliases[0].links:
            reclaimable += aliases[0].size
    categories = tuple(
        StorageCategory(name, sum(file.size for file in rows),
                        sum(file.size for file in {f.identity: f for f in rows}.values()), len(rows))
        for name, rows in sorted(groups.items())
    )
    return totals, reclaimable, categories


def _plan_id(root, identity, files, excluded, errors) -> str:
    digest = hashlib.sha256()
    for value in (str(root), identity, excluded, errors):
        digest.update(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    for file in files:
        digest.update(json.dumps(tuple(file.__dict__.values())).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def scan_storage(root: Path) -> StorageInventory:
    """Count identities once, with installed links preferred over cache aliases.

    Reclaimable bytes assume all recognized completed-cache aliases are removed
    together. Resume files, external links and unknown download files are retained.
    These are logical bytes, not NTFS allocated sectors or a disk-space promise.
    """
    root = checked_root(root)
    if not root.exists():
        return StorageInventory(str(root), (0, 0), _plan_id(root, (0, 0), (), (), ()),
                                0, 0, 0, 0, 0, (), (), (), ())
    with storage_lease(root):
        info = root.stat()
        identity = info.st_dev, info.st_ino
        files, excluded, errors = _walk(root)
        totals, reclaimable, categories = _counts(files)
        return StorageInventory(
            str(root), identity, _plan_id(root, identity, files, excluded, errors),
            sum(totals.values()), totals["installed"], totals["cache"], totals["other"],
            reclaimable, categories, files, excluded, errors,
        )
