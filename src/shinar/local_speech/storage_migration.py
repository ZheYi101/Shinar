"""Verified speech-library relocation; source assets are never removed here."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from uuid import uuid4

from shinar.configuration_location import location_file, save_speech_location

from .catalog import ModelPackage, load_catalog, safe_relative
from .compute import load_compute
from .downloads import DownloadCancelled, is_volatile_python_file
from .installation import managed_status, manifest, prepare_managed_runtime, runtime_plan
from .storage import atomic_json
from .storage_lease import storage_lease, StorageMovedError


_TREES = frozenset({"models", "downloads", "reports", "bootstrap", "wheelhouses"})
_SETTINGS = frozenset({"compute.json", "selections.json", "voices.json", "voice-terms.json", "settings.json"})
_JOURNAL = ".storage-migration.json"
_INTERNAL = frozenset({"runtimes", "installer-cache", "staging", ".locks", ".storage.lock", ".storage-moved.json", _JOURNAL})


@dataclass(frozen=True)
class MigrationFile:
    relative: str
    size: int
    identity: tuple[int, int, int]


@dataclass(frozen=True)
class MigrationPlan:
    source: Path
    destination: Path
    files: tuple[MigrationFile, ...]
    runtime_ids: tuple[str, ...]
    copy_bytes: int
    required_bytes: int
    retained_only: tuple[str, ...] = ()
    resume: bool = False

    def to_dict(self) -> dict:
        return {
            "source": str(self.source), "destination": str(self.destination),
            "copyBytes": self.copy_bytes, "requiredBytes": self.required_bytes,
            "runtimeIds": list(self.runtime_ids), "sourceRetained": True,
            "restartRequired": True,
            "retainedOnly": list(self.retained_only), "resumable": self.resume,
        }


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("speech_setup_cancelled")


def _is_reparse(path: Path) -> bool:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def _checked_path(value: Path) -> Path:
    path = Path(value).expanduser().absolute()
    if path == Path(path.anchor) or path.drive.startswith("\\\\"):
        raise ValueError("speech_storage_invalid_destination")
    if any(_is_reparse(parent) for parent in (path, *path.parents)):
        raise ValueError("speech_storage_invalid_destination")
    return path.resolve()


def _paths(root: Path, destination: Path) -> tuple[Path, Path]:
    source, target = _checked_path(root), _checked_path(destination)
    if (
        (source.exists() and not source.is_dir()) or source == target or source.is_relative_to(target)
        or target.is_relative_to(source)
    ):
        raise ValueError("speech_storage_invalid_destination")
    if target.exists() and (
        not target.is_dir() or (
            any(p.name != ".storage.lock" for p in target.iterdir())
            and not _resume_record(source, target)
        )
    ):
        raise ValueError("speech_storage_destination_not_empty")
    return source, target


def _resume_record(source: Path, target: Path) -> dict:
    try:
        path = target / _JOURNAL
        if _is_reparse(path):
            raise ValueError
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            record.get("version") != 1 or record.get("source") != str(source)
            or record.get("destination") != str(target)
        ):
            raise ValueError
        return record
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _file_fingerprint(selected: tuple[MigrationFile, ...]) -> str:
    value = [(item.relative, item.size, item.identity) for item in selected]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _managed_packages() -> tuple[ModelPackage, ...]:
    resources = tuple(ModelPackage.model_validate(item) for item in manifest().get("resources", {}).values())
    return (*load_catalog(), *resources)


def _quarantines(source: Path) -> tuple[Path, ...]:
    result = []
    for package in _managed_packages():
        parent = source / "models" / package.id
        if not parent.is_dir():
            continue
        pattern = re.compile(re.escape(package.revision) + r"\.invalid-[0-9a-f]{32}\Z")
        for candidate in parent.iterdir():
            if not pattern.fullmatch(candidate.name) or not candidate.is_dir():
                continue
            marker = candidate / ".installed.json"
            if _is_reparse(candidate) or _is_reparse(marker):
                raise ValueError("speech_storage_invalid_destination")
            try:
                content = json.loads(marker.read_text(encoding="utf-8"))
                if isinstance(content, dict) and content.get("fingerprint") == package.fingerprint:
                    result.append(candidate)
            except (OSError, ValueError):
                continue
    return tuple(sorted(result))


def _files(source: Path, quarantines: tuple[Path, ...] = ()) -> tuple[MigrationFile, ...]:
    result = []
    if not source.exists():
        return ()

    def failed(error):
        raise RuntimeError("speech_storage_verification_failed") from error

    for folder, directories, filenames in os.walk(source, followlinks=False, onerror=failed):
        parent = Path(folder)
        directories[:] = sorted(
            name for name in directories
            if (parent != source or name in _TREES) and parent / name not in quarantines
        )
        for name in directories:
            if _is_reparse(parent / name):
                raise ValueError("speech_storage_invalid_destination")
        for name in sorted(filenames):
            path = parent / name
            if parent == source and name not in _SETTINGS:
                continue
            if _is_reparse(path):
                raise ValueError("speech_storage_invalid_destination")
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("speech_storage_invalid_destination")
            result.append(MigrationFile(
                path.relative_to(source).as_posix(), info.st_size,
                (info.st_dev, info.st_ino, info.st_mtime_ns),
            ))
    return tuple(result)


def preview_migration(root: Path, destination: Path) -> MigrationPlan:
    source, target = _paths(root, destination)
    quarantines = _quarantines(source)
    selected = _files(source, quarantines)
    runtime_ids = []
    for name in manifest()["runtimes"]:
        status = managed_status(source, name)
        if status.get("prepared") or status.get("repairRequired") == "speech_runtime_nltk_missing":
            runtime_ids.append(name)
    runtimes = tuple(sorted(runtime_ids))
    copied = sum(item.size for item in selected)
    required = copied + sum(runtime_plan(source, name, repair=True).disk_bytes for name in runtimes)
    retained = tuple(sorted((
        item.name for item in source.iterdir()
        if item.name not in _TREES | _SETTINGS | _INTERNAL
    ))) if source.exists() else ()
    retained = tuple(sorted((*retained, *(path.relative_to(source).as_posix() for path in quarantines))))
    record = _resume_record(source, target)
    if record and (record.get("files") != _file_fingerprint(selected) or record.get("runtimeIds") != list(runtimes)):
        raise RuntimeError("speech_storage_plan_changed")
    return MigrationPlan(source, target, selected, runtimes, copied, required + 64 * 1024**2, retained, bool(record))


def _digest(path: Path, cancel) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024**2):
            _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def _copy(plan: MigrationPlan, cancel, stage) -> None:
    links = {}
    for item in plan.files:
        _check_cancel(cancel)
        source, target = plan.source / item.relative, plan.destination / item.relative
        info = source.stat()
        if (info.st_dev, info.st_ino, info.st_mtime_ns) != item.identity or info.st_size != item.size:
            raise RuntimeError("speech_storage_plan_changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        identity = (info.st_dev, info.st_ino)
        if plan.resume and target.exists():
            if _is_reparse(target) or not target.is_file():
                raise ValueError("speech_storage_invalid_destination")
            if target.stat().st_size == item.size and _digest(source, cancel) == _digest(target, cancel):
                links[identity] = target
                continue
            target.unlink()
        if info.st_ino and identity in links:
            os.link(links[identity], target)
        else:
            digest = hashlib.sha256()
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                while chunk := incoming.read(1024**2):
                    _check_cancel(cancel)
                    outgoing.write(chunk)
                    digest.update(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            after = source.stat()
            if (after.st_dev, after.st_ino, after.st_mtime_ns) != item.identity or after.st_size != item.size:
                raise RuntimeError("speech_storage_plan_changed")
            if digest.hexdigest() != _digest(target, cancel):
                raise RuntimeError("speech_storage_verification_failed")
            links[identity] = target
        stage("speech_storage_copying")


def _verify_models(root: Path, cancel) -> None:
    packages = {(package.id, package.revision): package for package in _managed_packages()}
    quarantines = set(_quarantines(root))
    for marker in (root / "models").glob("*/*/.installed.json"):
        if marker.parent in quarantines:
            continue
        _check_cancel(cancel)
        try:
            content = json.loads(marker.read_text(encoding="utf-8"))
            inventory = content["files"]
            if not isinstance(inventory, dict) or not inventory:
                raise ValueError
            package = packages.get((marker.parent.parent.name, marker.parent.name))
            for name, expected in inventory.items():
                path = marker.parent / safe_relative(name)
                if package is not None and is_volatile_python_file(package, name):
                    continue
                if path.stat().st_size != expected["size"] or _digest(path, cancel) != expected["sha256"]:
                    raise ValueError
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("speech_storage_verification_failed") from error


def _prepare(plan: MigrationPlan, cancel, stage) -> None:
    _verify_models(plan.destination, cancel)
    for blob in (plan.destination / "downloads").glob("*"):
        if blob.is_file() and re.fullmatch("[a-f0-9]{64}", blob.name) and _digest(blob, cancel) != blob.name:
            raise RuntimeError("speech_storage_verification_failed")
    _rewrite_reports(plan)
    for name in plan.runtime_ids:
        _check_cancel(cancel)
        stage("speech_storage_rebuilding_runtime")
        prepared = prepare_managed_runtime(
            plan.destination, name, cancel=cancel, stage=stage,
            gpu_index=load_compute(plan.destination).gpu_index,
        )
        if not prepared.get("prepared"):
            raise RuntimeError("speech_storage_verification_failed")


def _rewrite_reports(plan: MigrationPlan) -> None:
    for path in (plan.destination / "reports").glob("*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            preview = report.get("preview")
            if not isinstance(preview, str) or not preview:
                continue
            original = Path(preview)
            if original.is_absolute() and original.is_relative_to(plan.source / "reports"):
                report["preview"] = str(plan.destination / original.relative_to(plan.source))
                atomic_json(path, report)
        except (ValueError, TypeError, AttributeError):
            continue  # Preserve unrecognized historical report payloads unchanged.


def _journal(plan: MigrationPlan, config: Path) -> dict:
    return {
        "version": 1, "source": str(plan.source), "destination": str(plan.destination),
        "config_path": str(config), "transaction": uuid4().hex,
        "files": _file_fingerprint(plan.files), "runtimeIds": list(plan.runtime_ids),
    }


def _validate_target(plan: MigrationPlan) -> None:
    allowed_root = {Path(item.relative).parts[0] for item in plan.files} | {_JOURNAL, ".storage.lock"}
    generated = {"runtimes", "installer-cache", "staging", ".locks", "bootstrap", "wheelhouses", "downloads"}
    allowed_files = {item.relative for item in plan.files}
    for folder, directories, filenames in os.walk(plan.destination, followlinks=False):
        parent = Path(folder)
        for name in (*directories, *filenames):
            path = parent / name
            relative = path.relative_to(plan.destination)
            if _is_reparse(path) or (parent == plan.destination and name not in allowed_root | generated):
                raise ValueError("speech_storage_destination_not_empty")
            if path.is_file() and len(relative.parts) > 1 and relative.parts[0] not in generated:
                if relative.as_posix() not in allowed_files:
                    raise ValueError("speech_storage_destination_not_empty")


def _nearest_existing(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path


def _assert_source_active(source: Path) -> None:
    try:
        record = json.loads((source / ".storage-moved.json").read_text(encoding="utf-8"))
        saved = json.loads(Path(record["config_path"]).read_text(encoding="utf-8"))
        destination = record["destination"]
        if os.path.normcase(os.path.abspath(saved["speech_directory"])) == (
            os.path.normcase(os.path.abspath(destination))
        ):
            raise StorageMovedError(destination)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass


def _configuration_committed(config: Path, destination: Path) -> bool:
    try:
        saved = json.loads(config.read_text(encoding="utf-8"))
        return os.path.normcase(os.path.abspath(saved["speech_directory"])) == (
            os.path.normcase(os.path.abspath(destination))
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _rollback(target: Path) -> None:
    # The open root lease owns .storage.lock until the outer context exits.
    for child in target.iterdir():
        if child.name in {".storage.lock", _JOURNAL}:
            continue
        if _is_reparse(child):
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (target / _JOURNAL).unlink(missing_ok=True)


def migrate_storage(root, destination, config_path=None, *, cancel=None, on_stage=None) -> dict:
    stage = on_stage or (lambda value: None)
    initial = preview_migration(root, destination)
    _check_cancel(cancel)
    committed, prepared_marker = False, False
    marker = initial.source / ".storage-moved.json"
    if _is_reparse(marker):
        raise ValueError("speech_storage_invalid_destination")
    previous_marker = marker.read_bytes() if marker.is_file() else None
    config = location_file(config_path)
    with ExitStack() as leases:
        for folder in sorted((initial.source, initial.destination), key=lambda path: str(path).casefold()):
            leases.enter_context(storage_lease(folder, exclusive=True, cancel=cancel))
        _assert_source_active(initial.source)
        plan = preview_migration(initial.source, initial.destination)
        if plan.resume and _resume_record(plan.source, plan.destination).get("config_path") != str(config):
            raise RuntimeError("speech_storage_plan_changed")
        _validate_target(plan)
        if shutil.disk_usage(_nearest_existing(plan.destination)).free < plan.required_bytes:
            raise RuntimeError("speech_storage_insufficient_space")
        atomic_json(plan.destination / _JOURNAL, _journal(plan, config))
        try:
            _copy(plan, cancel, stage)
            _prepare(plan, cancel, stage)
            _check_cancel(cancel)
            atomic_json(marker, {
                "destination": str(plan.destination), "config_path": str(config),
                "transaction": uuid4().hex,
            })
            prepared_marker = True
            try:
                save_speech_location(plan.destination, config)
            except BaseException:
                # Atomic replacement is the commit. A late interruption must never
                # roll back the now-active library or report an uncommitted failure.
                if not _configuration_committed(config, plan.destination):
                    raise
            committed = True
            return {**plan.to_dict(), "runtimes": list(plan.runtime_ids)}
        finally:
            if not committed:
                if prepared_marker:
                    if previous_marker is None:
                        marker.unlink(missing_ok=True)
                    else:
                        marker.write_bytes(previous_marker)
                _rollback(plan.destination)
