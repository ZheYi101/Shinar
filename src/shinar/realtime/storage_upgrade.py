"""Reuse pinned RTC downloads only when the user explicitly prepares components."""

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from uuid import uuid4

from shinar.local_speech.catalog import Artifact
from shinar.local_speech.downloads import DownloadCancelled, ModelStore, package_lock
from shinar.local_speech.installation import manifest, resource_package, runtime_spec
from shinar.local_speech.storage_lease import checked_root, is_reparse, storage_lease
from .continuous_assets import VAD_PACKAGE, server_package


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("speech_setup_cancelled")


def _known_assets(source, target):
    assets, installed = {}, set()
    store = ModelStore(target)

    def add(artifact, *paths):
        artifact = Artifact.model_validate(artifact)
        current = assets.setdefault(artifact.sha256, (artifact, []))
        current[1].extend((source / "downloads" / artifact.sha256, *paths))

    spec = runtime_spec("rtc-cpu")
    for wheel in spec.wheels:
        add(wheel, source / "wheelhouses" / spec.fingerprint / wheel["path"])
    for package in (
        *(resource_package(name) for name in ("python", *spec.resources)),
        VAD_PACKAGE,
        server_package(),
    ):
        folder = target / "models" / package.id / package.revision
        checked_root(folder)
        _file_info(folder / ".installed.json")
        if store.installed(package):
            installed.update(artifact.sha256 for artifact in package.files)
            continue
        for artifact in package.files:
            raw_file = source / "models" / package.id / package.revision / artifact.path
            paths = () if artifact.archive_root else (raw_file,)
            add(artifact, *paths)
    add(manifest()["uv"])
    for artifact in server_package().files:
        if artifact.sha256 not in installed:
            add(artifact, source / "sfu" / artifact.path)
    return tuple((artifact, tuple(dict.fromkeys(paths))) for artifact, paths in assets.values())


def _file_info(path):
    checked_root(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if is_reparse(info):
        raise ValueError("speech_storage_link_unsupported")
    if not stat.S_ISREG(info.st_mode) or not info.st_ino:
        raise ValueError("speech_storage_verification_failed")
    return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size


def _complete(path, artifact, cancel):
    before = _file_info(path)
    if before is None or before[-1] != artifact.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024**2):
            _check_cancel(cancel)
            digest.update(chunk)
    if _file_info(path) != before:
        raise RuntimeError("speech_storage_changed")
    return digest.hexdigest() == artifact.sha256


def _copy_asset(source, destination, artifact, cancel, *, partial=False):
    before = _file_info(source)
    if before is None or not 0 < before[-1] <= artifact.size:
        return 0
    if not partial and before[-1] != artifact.size:
        return 0
    previous = _file_info(destination)
    if partial and previous is not None and previous[-1] >= before[-1]:
        return 0
    temporary = destination.with_name(destination.name + ".reuse-" + uuid4().hex)
    digest, copied = hashlib.sha256(), 0
    try:
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            opened = os.fstat(incoming.fileno())
            if (opened.st_dev, opened.st_ino) != before[:2]:
                raise RuntimeError("speech_storage_changed")
            while chunk := incoming.read(1024**2):
                _check_cancel(cancel)
                copied += len(chunk)
                if copied > before[-1]:
                    raise RuntimeError("speech_storage_changed")
                outgoing.write(chunk)
                digest.update(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if _file_info(source) != before or copied != before[-1]:
            raise RuntimeError("speech_storage_changed")
        if not partial and digest.hexdigest() != artifact.sha256:
            return 0
        _check_cancel(cancel)
        if _file_info(destination) != previous:
            raise RuntimeError("speech_storage_changed")
        os.replace(temporary, destination)
        return copied
    finally:
        temporary.unlink(missing_ok=True)


def _reuse_asset(source, target, artifact, candidates, cancel):
    complete = target / "downloads" / artifact.sha256
    if _complete(complete, artifact, cancel):
        return 0, 0
    for candidate in candidates:
        current = target / candidate.relative_to(source)
        if current != complete and _complete(current, artifact, cancel):
            return 0, 0
    for candidate in candidates:
        if copied := _copy_asset(candidate, complete, artifact, cancel):
            return copied, 0
    copied = _copy_asset(
        source / "downloads" / (artifact.sha256 + ".part"),
        complete.with_suffix(".part"), artifact, cancel, partial=True,
    )
    return 0, copied


def reuse_legacy_assets(source, target, *, cancel=None) -> dict:
    """Seed verified blobs and longer bounded partials; never copy environments.

    Source content is retained. Partial bytes are not trusted as complete assets;
    ModelStore still validates the full pinned size and SHA before publication.
    """
    counts = {"completedFiles": 0, "completedBytes": 0, "partialFiles": 0, "partialBytes": 0}
    _check_cancel(cancel)
    source, target = checked_root(Path(source)), checked_root(Path(target))
    if source == target or not source.is_dir():
        return counts
    roots = sorted((source, target), key=lambda path: str(path).casefold())
    with ExitStack() as leases:
        for root in roots:
            leases.enter_context(storage_lease(root, cancel=cancel))
        downloads = checked_root(target / "downloads")
        downloads.mkdir(parents=True, exist_ok=True)
        for artifact, candidates in _known_assets(source, target):
            _check_cancel(cancel)
            with ExitStack() as locks:
                package = SimpleNamespace(id="asset-" + artifact.sha256)
                for root in roots:
                    checked_root(root / ".locks")
                    _file_info(root / ".locks" / (package.id + ".lock"))
                    locks.enter_context(package_lock(root, package, cancel=cancel))
                completed, partial = _reuse_asset(source, target, artifact, candidates, cancel)
            counts["completedFiles"] += bool(completed)
            counts["completedBytes"] += completed
            counts["partialFiles"] += bool(partial)
            counts["partialBytes"] += partial
    return counts
