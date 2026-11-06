"""Explicit, pinned speech provisioning. Inference never invokes this module to download."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack, contextmanager
from importlib.resources import files
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from .catalog import Artifact, ModelPackage, load_catalog
from .downloads import DownloadCancelled, ModelStore, package_lock
from .runtime import run_bounded
from .storage import atomic_json, read_json


class SpeechSetupError(ValueError):
    """Stable codes for desktop translation; never expose installer logs."""


@dataclass(frozen=True)
class RuntimeSpec:
    id: str
    device: str
    wheels: tuple[dict, ...]
    resources: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        value = {
            **self.__dict__,
            "resource_fingerprints": {
                name: resource_package(name).fingerprint for name in self.resources
            },
            "python_fingerprint": resource_package("python").fingerprint,
        }
        if self.id.startswith("melo-"):
            value["frontend"] = manifest()["support_sha256"]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class InstallationPlan:
    package_id: str
    runtime_id: str
    language: str
    device: str
    download_bytes: int
    disk_bytes: int


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(
        files(__package__).joinpath("runtime_resources/manifest.json").read_text("utf-8")
    )


def runtime_spec(runtime_id: str) -> RuntimeSpec:
    item = manifest()["runtimes"].get(runtime_id)
    if item is None:
        raise SpeechSetupError("speech_runtime_unknown")
    return RuntimeSpec(
        runtime_id, item["device"], tuple(item["wheels"]), tuple(item.get("resources", ()))
    )


def resource_package(resource_id: str) -> ModelPackage:
    return ModelPackage.model_validate(manifest()["resources"][resource_id])


def runtime_id_for(package: ModelPackage, device: str) -> str:
    if package.adapter == "voicevox":
        if device != "cpu":
            raise SpeechSetupError("speech_device_unsupported")
        return "voicevox-cpu"
    if package.adapter == "melo_english":
        return "melo-" + device
    return "ort-" + device


def managed_status(root: Path, runtime_id: str) -> dict:
    pointer = read_json(root / "runtimes" / (runtime_id + ".json"), {})
    try:
        folder = (root / "runtimes" / pointer["folder"]).resolve()
        if not folder.is_relative_to((root / "runtimes").resolve()):
            return {"prepared": False}
        ready = read_json(folder / "ready.json", {})
        python = folder / "Scripts/python.exe"
        valid = (
            pointer.get("fingerprint") == runtime_spec(runtime_id).fingerprint
            and ready.get("ok") is True
            and python.is_file()
            and ready.get("fingerprint") == pointer["fingerprint"]
            and all(
                ModelStore(root).installed(resource_package(name))
                for name in runtime_spec(runtime_id).resources
            )
        )
        return {**ready, "prepared": valid, "python": str(python)}
    except (KeyError, ValueError, OSError):
        return {"prepared": False}


def make_plan(root: Path, package: ModelPackage, language: str, device: str) -> InstallationPlan:
    spec = runtime_spec(runtime_id_for(package, device))
    size, disk = _asset_plan(root, spec, package.files)
    return InstallationPlan(package.id, spec.id, language, device, size, disk)


def runtime_plan(root: Path, runtime_id: str) -> InstallationPlan:
    spec = runtime_spec(runtime_id)
    size, disk = _asset_plan(root, spec, (), runtime_required=True)
    return InstallationPlan("", spec.id, "", spec.device, size, disk)


def _asset_plan(
    root: Path, spec: RuntimeSpec, model_assets, *, runtime_required=False
) -> tuple[int, int]:
    data = manifest()
    assets = [*model_assets]
    if runtime_required or not managed_status(root, spec.id)["prepared"]:
        assets.extend(Artifact.model_validate(w) for w in spec.wheels if "resource" not in w)
        assets.extend(resource_package("python").files)
        assets.append(Artifact.model_validate(data["uv"]))
        for name in spec.resources:
            assets.extend(resource_package(name).files)
    unique = {a.sha256: a for a in assets}
    pending = [a for a in unique.values() if not (root / "downloads" / a.sha256).is_file()]
    size = sum(a.size for a in pending)
    disk = (
        sum(a.size + a.unpacked_limit for a in unique.values())
        + sum(a.size for a in unique.values()) * 3
    )
    return size, disk + 256 * 1024**2


def _check_platform() -> None:
    import platform

    if (
        sys.platform != "win32"
        or platform.machine().lower() not in {"amd64", "x86_64"}
        or getattr(sys, "frozen", False)
    ):
        raise SpeechSetupError("speech_runtime_platform_unsupported")


def _check_cancel(cancel) -> None:
    if cancel and cancel.is_set():
        raise DownloadCancelled("speech_setup_cancelled")


def _uv(store: ModelStore, cancel, progress) -> Path:
    artifact = Artifact.model_validate(manifest()["uv"])
    blob = store.fetch_artifact(artifact, cancel=cancel, progress=progress)
    target = store.root / "bootstrap" / artifact.sha256 / "uv.exe"
    with zipfile.ZipFile(blob) as archive:
        candidates = [i for i in archive.infolist() if i.filename.endswith("/uv.exe")]
        if len(candidates) != 1 or candidates[0].file_size > 100 * 1024**2:
            raise SpeechSetupError("speech_bootstrap_invalid")
        expected = hashlib.sha256(archive.read(candidates[0])).hexdigest()
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix("." + uuid4().hex)
        with archive.open(candidates[0]) as source, tmp.open("xb") as output:
            shutil.copyfileobj(source, output)
        os.replace(tmp, target)
    return target


@contextmanager
def _model_leases(root: Path, runtime_id: str):
    """Inference holds these same locks, including in another app instance."""
    with ExitStack() as leases:
        for package in load_catalog():
            try:
                matches = runtime_id_for(package, runtime_spec(runtime_id).device) == runtime_id
            except SpeechSetupError:
                matches = False
            if package.files and matches:
                leases.enter_context(package_lock(root, package))
        yield


def prepare_managed_runtime(
    root: Path,
    runtime_id: str,
    *,
    cancel=None,
    progress=lambda done, total: None,
    stage=lambda value: None,
    gpu_index: int = 0,
    repair: bool = False,
) -> dict:
    _check_platform()
    root = root.resolve()
    store, spec = ModelStore(root), runtime_spec(runtime_id)
    old = managed_status(root, runtime_id)
    if old["prepared"] and not repair:
        return old
    with (
        package_lock(root, SimpleNamespace(id="runtime-" + runtime_id)),
        _model_leases(root, runtime_id),
    ):
        old = managed_status(root, runtime_id)
        if old["prepared"] and not repair:
            return old
        if shutil.disk_usage(root).free < runtime_plan(root, runtime_id).disk_bytes:
            raise SpeechSetupError("speech_setup_disk_insufficient")
        stage("speech_setup_bootstrap")
        uv = _uv(store, cancel, progress)
        python_package = resource_package("python")
        python_home = store.install(python_package, cancel=cancel, progress=progress)
        for name in spec.resources:
            stage("speech_setup_resources")
            store.install(resource_package(name), cancel=cancel, progress=progress)
        wheelhouse = root / "wheelhouses" / spec.fingerprint
        wheelhouse.mkdir(parents=True, exist_ok=True)
        stage("speech_setup_wheels")
        for item in spec.wheels:
            _check_cancel(cancel)
            target = wheelhouse / item["path"]
            if item.get("resource"):
                source = files(__package__).joinpath("runtime_resources", item["resource"])
                content = source.read_bytes()
                if (
                    len(content) != item["size"]
                    or hashlib.sha256(content).hexdigest() != item["sha256"]
                ):
                    raise SpeechSetupError("speech_runtime_resource_corrupt")
                target.write_bytes(content)
            else:
                blob = store.fetch_artifact(
                    Artifact.model_validate(item), cancel=cancel, progress=progress
                )
                # A corrupt hard link may have outlived replacement of its cache blob.
                # Reuse only the exact file whose bytes fetch_artifact just verified.
                if target.exists() and target.samefile(blob):
                    continue
                target.unlink(missing_ok=True)
                try:
                    os.link(blob, target)
                except OSError:
                    shutil.copyfile(blob, target)
        folder = root / "runtimes" / (runtime_id + "-" + uuid4().hex)
        folder.parent.mkdir(parents=True, exist_ok=True)
        try:
            stage("speech_setup_installing")
            run_bounded(
                [
                    str(uv),
                    "--no-config",
                    "--no-python-downloads",
                    "venv",
                    "--python",
                    str(python_home / "python.exe"),
                    str(folder),
                ],
                cancel=cancel,
                timeout=120,
            )
            python = folder / "Scripts/python.exe"
            run_bounded(
                [
                    str(uv),
                    "--no-config",
                    "--offline",
                    "--cache-dir",
                    str(root / "installer-cache"),
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--no-deps",
                    "--no-index",
                    *(str(wheelhouse / w["path"]) for w in spec.wheels),
                ],
                cancel=cancel,
                timeout=900,
            )
            if runtime_id.startswith("melo-"):
                support = folder / "support"
                import io

                content = (
                    files(__package__).joinpath("runtime_resources/melo_support.zip").read_bytes()
                )
                if (
                    hashlib.sha256(content).hexdigest()
                    != manifest()["support_sha256"]["melo_support.zip"]
                ):
                    raise SpeechSetupError("speech_runtime_resource_corrupt")
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    for name, expected in manifest()["support_files"].items():
                        content = archive.read(name)
                        if hashlib.sha256(content).hexdigest() != expected:
                            raise SpeechSetupError("speech_runtime_resource_corrupt")
                        target = support / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                nlp = store.model_path(resource_package("nltk"))
                from .catalog import safe_relative

                for blob in nlp.rglob("*.zip"):
                    parent = support / "nltk_data" / blob.parent.relative_to(nlp)
                    with zipfile.ZipFile(blob) as archive:
                        total = 0
                        for info in archive.infolist():
                            _check_cancel(cancel)
                            relative = safe_relative(info.filename.rstrip("/"))
                            if info.is_dir():
                                continue
                            total += info.file_size
                            if (
                                total > 64 * 1024**2
                                or ((info.external_attr >> 16) & 0o170000) == 0o120000
                            ):
                                raise SpeechSetupError("speech_runtime_resource_corrupt")
                            target = parent / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(info) as source, target.open("xb") as output:
                                shutil.copyfileobj(source, output)
            _check_cancel(cancel)
            stage("speech_setup_probing")
            result = probe_managed_runtime(
                root, runtime_id, str(python), gpu_index=gpu_index, cancel=cancel
            )
            _check_cancel(cancel)
            result.update(fingerprint=spec.fingerprint, runtime_id=runtime_id)
            atomic_json(folder / "ready.json", result)
            atomic_json(
                root / "runtimes" / (runtime_id + ".json"),
                {"folder": folder.name, "fingerprint": spec.fingerprint},
            )
            return managed_status(root, runtime_id)
        except BaseException:
            # The old pointer has not changed. Only this operation's candidate is removed.
            if folder.exists() and folder.resolve().is_relative_to((root / "runtimes").resolve()):
                shutil.rmtree(folder)
            raise


def probe_managed_runtime(
    root: Path, runtime_id: str, python: str, *, gpu_index=0, cancel=None
) -> dict:
    config = {
        "runtime_id": runtime_id,
        "gpu_index": gpu_index,
        "resources": {
            name: str(ModelStore(root).model_path(resource_package(name)))
            for name in runtime_spec(runtime_id).resources
        },
    }
    try:
        raw = run_bounded(
            [python, str(Path(__file__).with_name("managed_runtime_probe.py")), json.dumps(config)],
            cancel=cancel,
            timeout=120,
        )
    except RuntimeError:
        raise SpeechSetupError("speech_runtime_probe_failed") from None
    try:
        result = json.loads(raw.strip().splitlines()[-1])
        if result.get("ok") is not True or result.get("runtime_id") != runtime_id:
            raise ValueError
        return result
    except (ValueError, IndexError):
        raise SpeechSetupError("speech_runtime_probe_failed") from None
