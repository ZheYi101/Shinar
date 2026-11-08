"""Build a relocatable private CPython app, ZIP and optional per-user Inno installer.

Only allowlisted sources enter the wheel. All installs happen in a fresh build folder,
never in the developer venv or the user's application/data directories.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging/windows"


def run(arguments: list[str | Path], *, cwd: Path | None = None) -> None:
    subprocess.run([str(item) for item in arguments], cwd=cwd or ROOT, check=True)


def fetch_verified(spec: dict[str, str], cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / spec["sha256"]
    if target.is_file():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == spec["sha256"]:
                return target
    with (
        urlopen(spec["url"], timeout=120) as response,
        target.with_suffix(".part").open("wb") as output,
    ):
        shutil.copyfileobj(response, output)
    with target.with_suffix(".part").open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != spec["sha256"]:
        raise RuntimeError("Build tool download failed SHA256 verification")
    target.with_suffix(".part").replace(target)
    return target


def snapshot_sources(destination: Path) -> None:
    destination.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copy2(ROOT / name, destination / name)
    shutil.copytree(
        ROOT / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )


def inspect_payload(root: Path) -> dict:
    """Fail closed on accidental secrets, learning data, links or dev-only files."""
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected symlink: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        lower = path.name.lower()
        if (
            lower in {".env", "ai-services.json"}
            or lower.startswith(".env.")
            and lower != ".env.example"
            or lower.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".log"))
        ):
            raise RuntimeError(f"Private data is not distributable: {relative}")
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append({"path": relative, "bytes": path.stat().st_size, "sha256": checksum})
    return {"files": records, "total_bytes": sum(item["bytes"] for item in records)}


def compiler() -> Path:
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    path = windows / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not path.is_file():
        raise RuntimeError("Windows .NET Framework 4.x C# compiler was not found")
    return path


def build_launcher(destination: Path, work: Path, version: str) -> None:
    source = work / "Launcher.cs"
    source.write_text(
        (PACKAGING / "Launcher.cs")
        .read_text(encoding="utf-8")
        .replace("@@VERSION@@", version + ".0"),
        encoding="utf-8",
    )
    run(
        [
            compiler(),
            "/nologo",
            "/target:winexe",
            "/platform:x64",
            "/optimize+",
            "/codepage:65001",
            "/reference:System.Windows.Forms.dll",
            f"/win32icon:{destination / 'app-icon.ico'}",
            f"/win32manifest:{PACKAGING / 'launcher.manifest'}",
            f"/out:{destination / 'Shinar.exe'}",
            source,
        ]
    )


def main() -> None:
    from windows_runtime import trim_runtime

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/windows")
    parser.add_argument("--iscc", type=Path, help="Optional Inno Setup 6.7+ compiler")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Build the Windows distribution on Windows x64")
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv is required")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    build_root = ROOT / "build/windows"
    build_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="build-", dir=build_root))
    print(f"Isolated build: {work}", flush=True)
    snapshot = work / "source"
    snapshot_sources(snapshot)
    project = tomllib.loads((snapshot / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    tools = json.loads((PACKAGING / "toolchain.json").read_text(encoding="utf-8"))
    artifact_name = f"Shinar-{version}-windows-x64"
    app = work / "Shinar"
    app.mkdir()
    archive = fetch_verified(tools["python"], build_root / "downloads")
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(app, filter="data")
    (app / "python").rename(app / "runtime")
    python = app / "runtime/python.exe"
    requirements = work / "requirements.txt"
    run(
        [
            uv,
            "export",
            "--project",
            snapshot,
            "--locked",
            "--no-config",
            "--no-dev",
            "--no-default-groups",
            "--extra",
            "desktop",
            "--extra",
            "continuous-voice",
            "--no-emit-project",
            "--output-file",
            requirements,
            "--quiet",
        ]
    )
    run(
        [
            uv,
            "pip",
            "install",
            "--no-config",
            "--python",
            python,
            "--system",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--link-mode",
            "copy",
            "-r",
            requirements,
        ]
    )
    wheel_dir = work / "wheels"
    run([uv, "build", snapshot, "--wheel", "--out-dir", wheel_dir, "--no-config"])
    (wheel,) = wheel_dir.glob("*.whl")
    run(
        [
            uv,
            "pip",
            "install",
            "--no-config",
            "--python",
            python,
            "--system",
            "--no-deps",
            "--link-mode",
            "copy",
            wheel,
        ]
    )
    for name in ("app-icon.ico", "app-icon.png"):
        shutil.copy2(snapshot / "src/shinar/desktop/assets" / name, app / name)
    build_launcher(app, work, version)
    shutil.copy2(ROOT / ".env.example", app / ".env.example")
    shutil.copy2(ROOT / "docs/desktop/WINDOWS_DISTRIBUTION.md", app / "使用说明.md")
    shutil.copy2(requirements, app / "DEPENDENCIES.txt")
    trimming = trim_runtime(app, build_root=build_root)
    (work / "pruning.json").write_text(json.dumps(trimming, indent=2), encoding="utf-8")
    layout = {"policy": trimming["policy"],
              "retired": [entry["path"] for entry in trimming["removed"]],
              "retained": sorted(p.relative_to(app / "runtime").as_posix()
                                 for p in (app / "runtime").rglob("*") if p.is_file())}
    (app / "RUNTIME_LAYOUT.json").write_text(json.dumps(layout), encoding="utf-8")
    shutil.copy2(PACKAGING / "cleanup_runtime.py", app / "cleanup_runtime.py")
    metadata = {
        "version": version,
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "python": tools["python"],
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "lock_sha256": hashlib.sha256((snapshot / "uv.lock").read_bytes()).hexdigest(),
        "source_is_working_tree_snapshot": True,
        "runtime_layout": trimming["policy"],
        "runtime_removed_bytes": trimming["removed_bytes"],
    }
    # No credentials or environment values are written to this manifest.
    (app / "BUILD.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    payload = inspect_payload(app)
    (work / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    zip_path = output / f"{artifact_name}.zip"
    partial_zip = zip_path.with_suffix(".zip.part")
    with ZipFile(partial_zip, "w", compression=ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                zipped.write(path, "Shinar/" + path.relative_to(app).as_posix())
    partial_zip.replace(zip_path)
    if args.iscc:
        run(
            [
                args.iscc.resolve(),
                "/Qp",
                f"/DAppVersion={version}",
                f"/DSourceDir={app}",
                f"/DOutputDir={output}",
                PACKAGING / "Shinar.iss",
            ]
        )
    results = [zip_path]
    if args.iscc:
        results.append(output / f"{artifact_name}-setup.exe")
    sums = []
    for path in results:
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        sums.append(f"{checksum}  {path.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "app": str(app),
                "output": str(output),
                "files": len(payload["files"]),
                "bytes": payload["total_bytes"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
