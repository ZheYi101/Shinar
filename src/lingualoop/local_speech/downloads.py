from __future__ import annotations

import hashlib
import os
import re
import shutil
import tarfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4
from types import SimpleNamespace

import httpx

from .catalog import ModelPackage, safe_relative
from .storage import atomic_json, read_json


class DownloadCancelled(RuntimeError):
    pass


@contextmanager
def package_lock(root: Path, package: ModelPackage):
    locks = root / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / (package.id + ".lock")).open("a+b") as stream:
        try:
            # Windows byte-range locks also prohibit reads by a competing handle.
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "模型正在被下载、测速或已加载的语音进程使用；请先释放模型。"
            ) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _check_cancel(cancel):
    if cancel and cancel.is_set():
        raise DownloadCancelled("已取消，已下载部分保留以便继续。")


def _digest(path: Path, cancel=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


class ModelStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _owned(self, path):
        target = path.resolve()
        if target == self.root or not target.is_relative_to(self.root):
            raise ValueError("模型缓存路径越界。")
        return target

    def model_path(self, package):
        return self.root / "models" / package.id / package.revision

    def fetch_artifact(self, artifact, *, cancel=None, progress=lambda done, total: None):
        """Share verified blobs across runtime/model jobs, including concurrent app instances."""
        with package_lock(self.root, SimpleNamespace(id="asset-" + artifact.sha256)):
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=30)) as client:
                return self._fetch(artifact, client, cancel, progress)

    def installed(self, package):
        path = self.model_path(package)
        marker = read_json(path / ".installed.json", {})
        if not isinstance(marker, dict) or marker.get("fingerprint") != package.fingerprint:
            return False
        expected = marker.get("files", {})
        try:
            return (
                isinstance(expected, dict)
                and bool(expected)
                and set(package.required_files).issubset(expected)
                and all(
                    self._owned(path / safe_relative(name)).is_file()
                    and not (path / name).is_symlink()
                    and (path / name).stat().st_size == meta["size"]
                    for name, meta in expected.items()
                )
            )
        except (ValueError, OSError, KeyError, TypeError):
            return False

    def install(
        self,
        package: ModelPackage,
        *,
        cancel=None,
        progress=lambda done, total: None,
        client: httpx.Client | None = None,
    ):
        if not package.files:
            raise ValueError("此候选尚未提供已校验的安装包。")
        with package_lock(self.root, package):
            if self.installed(package):
                return self.model_path(package)
            # Same-package lock proves these staging trees have no live owner.
            # Recover crash leftovers without touching another model's task.
            for abandoned in (self.root / "staging").glob(package.id + "-*"):
                if abandoned.is_symlink():
                    raise ValueError("模型临时目录不能是链接。")
                if abandoned.is_dir():
                    shutil.rmtree(self._owned(abandoned))
            # Keep enough space for both the downloaded package and staging tree.
            required = sum(f.size + f.unpacked_limit for f in package.files) + 256 * 1024**2
            if shutil.disk_usage(self.root).free < required:
                raise RuntimeError("模型缓存盘空间不足。")
            with (
                httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=30))
                if client is None
                else _borrow(client) as transport
            ):
                downloads = []
                offset = 0
                for artifact in package.files:
                    _check_cancel(cancel)
                    blob = self._fetch(
                        artifact,
                        transport,
                        cancel,
                        lambda done, _total: progress(offset + done, package.download_bytes),
                    )
                    downloads.append((artifact, blob))
                    offset += artifact.size
            staging = self.root / "staging" / (package.id + "-" + uuid4().hex)
            staging.mkdir(parents=True)
            try:
                for artifact, blob in downloads:
                    _check_cancel(cancel)
                    if artifact.archive_root:
                        self._extract(blob, artifact, staging, cancel)
                    else:
                        target = staging / artifact.path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(blob, target)
                if not all((staging / name).is_file() for name in package.required_files):
                    raise ValueError("模型包缺少运行必需文件。")
                inventory = {}
                for path in staging.rglob("*"):
                    if path.is_file():
                        inventory[path.relative_to(staging).as_posix()] = {
                            "size": path.stat().st_size,
                            "sha256": _digest(path, cancel),
                        }
                atomic_json(
                    staging / ".installed.json",
                    {"fingerprint": package.fingerprint, "files": inventory},
                )
                destination = self.model_path(package)
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Failed or corrupt copies are quarantined first, never merged.
                if destination.exists():
                    destination.rename(
                        destination.with_name(destination.name + ".invalid-" + uuid4().hex)
                    )
                staging.rename(destination)
                return destination
            finally:
                if staging.exists():
                    shutil.rmtree(self._owned(staging))

    def _fetch(self, artifact, client, cancel, progress):
        for attempt in range(3):
            _check_cancel(cancel)
            try:
                return self._fetch_once(artifact, client, cancel, progress)
            except httpx.TransportError:
                if attempt == 2:
                    raise
            except httpx.HTTPStatusError as error:
                if attempt == 2 or error.response.status_code < 500:
                    raise
        raise RuntimeError("speech_download_incomplete")

    def _fetch_once(self, artifact, client, cancel, progress):
        cache = self.root / "downloads"
        cache.mkdir(parents=True, exist_ok=True)
        complete = cache / artifact.sha256
        part = cache / (artifact.sha256 + ".part")
        if complete.exists():
            if (
                complete.stat().st_size == artifact.size
                and _digest(complete, cancel) == artifact.sha256
            ):
                progress(artifact.size, artifact.size)
                return complete
            complete.unlink()
        start = part.stat().st_size if part.exists() else 0
        if start > artifact.size:
            part.unlink()
            start = 0
        if start != artifact.size:
            headers = {"Accept-Encoding": "identity"}
            if start:
                headers["Range"] = f"bytes={start}-"
            with client.stream("GET", artifact.url, headers=headers) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", "")
                    )
                    if not match or tuple(map(int, match.groups())) != (
                        start,
                        artifact.size - 1,
                        artifact.size,
                    ):
                        raise ValueError("下载服务返回的续传范围不正确。")
                elif response.status_code == 200:
                    start = 0  # Server ignored Range; restart instead of appending.
                else:
                    raise ValueError("下载服务未返回完整内容。")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ValueError("下载服务改变了文件编码。")
                with part.open("ab" if start else "wb") as stream:
                    count = start
                    for chunk in response.iter_bytes(64 * 1024):
                        _check_cancel(cancel)
                        count += len(chunk)
                        if count > artifact.size:
                            raise ValueError("下载大小超过清单。")
                        stream.write(chunk)
                        progress(count, artifact.size)
        _check_cancel(cancel)
        if not part.exists() or part.stat().st_size != artifact.size:
            raise ValueError("模型未下载完整，可重试续传。")
        if _digest(part, cancel) != artifact.sha256:
            part.unlink()
            raise ValueError("模型校验失败，已丢弃损坏数据，请重新下载。")
        part.replace(complete)
        return complete

    @staticmethod
    def _extract(blob, artifact, destination, cancel):
        total = 0
        seen = set()
        with tarfile.open(blob, "r:*") as archive:
            for member in archive:
                _check_cancel(cancel)
                name = member.name.rstrip("/")
                safe_relative(name)
                path = PurePosixPath(name)
                try:
                    relative = path.relative_to(artifact.archive_root)
                except ValueError as exc:
                    raise ValueError("模型包目录越界。") from exc
                if member.isdir():
                    continue
                if not member.isfile() or not relative.parts or str(relative) in seen:
                    raise ValueError("模型包含链接、特殊文件或重复文件。")
                seen.add(str(relative))
                total += member.size
                if total > artifact.unpacked_limit or len(seen) > 10000:
                    raise ValueError("模型包展开大小超过限制。")
                target = destination / str(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        _check_cancel(cancel)
                        output.write(chunk)

    def verify(self, package, *, cancel=None):
        with package_lock(self.root, package):
            if not self.installed(package):
                raise ValueError("模型未安装或文件不完整。")
            directory = self.model_path(package)
            marker = read_json(directory / ".installed.json")
            for name, meta in marker["files"].items():
                if _digest(directory / name, cancel) != meta["sha256"]:
                    raise ValueError("本地模型文件损坏，请卸载后重新下载。")
            return True

    def uninstall(self, package):
        with package_lock(self.root, package):
            path = self.model_path(package)
            if path.exists():
                if path.is_symlink():
                    raise ValueError("模型目录不能是链接。")
                shutil.rmtree(self._owned(path))
            # Content-addressed blobs are disposable; no user audio/history here.
            for artifact in package.files:
                for suffix in ("", ".part"):
                    (self.root / "downloads" / (artifact.sha256 + suffix)).unlink(missing_ok=True)


@contextmanager
def _borrow(client):
    yield client
