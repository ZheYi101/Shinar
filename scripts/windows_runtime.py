"""Trim only a new Windows build payload, retaining Qt's native dependency closure.

The interpreter stays unfrozen: venv/ensurepip and the model subprocess mechanism
remain available. Nothing here touches a developer venv or an installed app.
"""

from __future__ import annotations

import ast
from collections import deque
import json
from pathlib import Path
import struct
import subprocess


def pe_dependencies(path: Path) -> set[str]:
    """Read normal and delayed imports from a PE32/PE32+ image without loading it."""
    data = path.read_bytes()
    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[:2] != b"MZ" or data[pe : pe + 4] != b"PE\0\0":
            raise ValueError
        sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
        optional = pe + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic not in {0x10B, 0x20B}:
            raise ValueError
        directories = optional + (112 if magic == 0x20B else 96)
        image_base = struct.unpack_from(
            "<Q" if magic == 0x20B else "<I", data, optional + (24 if magic == 0x20B else 28)
        )[0]
        table = optional + optional_size

        def offset(rva: int) -> int:
            for index in range(sections):
                size, address, raw_size, raw = struct.unpack_from(
                    "<IIII", data, table + 40 * index + 8
                )
                if address <= rva < address + max(size, raw_size):
                    result = raw + rva - address
                    if result >= len(data):
                        break
                    return result
            raise ValueError

        result = set()
        for directory, stride, name_index in ((1, 20, 12), (13, 32, 4)):
            rva, size = struct.unpack_from("<II", data, directories + directory * 8)
            if not rva:
                continue
            start = offset(rva)
            for row in range(start, min(start + size, len(data)), stride):
                if not any(data[row : row + stride]):
                    break
                name = struct.unpack_from("<I", data, row + name_index)[0]
                if directory == 13 and not struct.unpack_from("<I", data, row)[0] & 1:
                    name -= image_base
                begin = offset(name)
                end = data.index(b"\0", begin, min(begin + 512, len(data)))
                result.add(data[begin:end].decode("ascii").lower())
        return result
    except (ValueError, struct.error, IndexError, UnicodeError):
        raise ValueError(f"Invalid native dependency image: {path.name}") from None


def native_closure(qt: Path, seeds: set[Path]) -> set[Path]:
    available = {p.name.lower(): p for p in qt.iterdir() if p.suffix.lower() in {".dll", ".pyd"}}
    retained, pending = set(seeds), deque(seeds)
    while pending:
        for name in pe_dependencies(pending.popleft()):
            dependency = available.get(name)
            if dependency is None:
                if name.startswith("qt6"):
                    raise ValueError(f"Missing Qt runtime dependency: {name}")
                continue  # Windows/system or private-Python runtime dependency.
            if dependency not in retained:
                retained.add(dependency)
                pending.append(dependency)
    return retained


def python_qt_modules(source: Path) -> set[str]:
    modules = {"QtTest"}  # The packaged interaction check uses real Qt input events.
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                if node.module == "PySide6":
                    modules.update(a.name for a in node.names if a.name.startswith("Qt"))
                elif node.module and node.module.startswith("PySide6.Qt"):
                    modules.add(node.module.split(".")[1])
            elif isinstance(node, ast.Import):
                modules.update(
                    a.name.split(".")[1] for a in node.names if a.name.startswith("PySide6.Qt")
                )
    return modules


def qml_modules(qt: Path, source: Path) -> set[Path]:
    scan = subprocess.run(
        [
            str(qt / "qmlimportscanner.exe"),
            "-rootPath",
            str(source),
            "-importPath",
            str(qt / "qml"),
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    modules = set()
    for row in json.loads(scan.stdout):
        if row.get("type") != "module":
            continue
        if not row.get("path"):
            if row["name"] not in {"QML", "QtQuickControls2", "org.kde.kirigami"}:
                raise ValueError(f"Unresolved QML runtime module: {row['name']}")
            continue
        folder = Path(row["path"]).resolve()
        if not folder.is_relative_to((qt / "qml").resolve()):
            raise ValueError("QML dependency escaped the packaged runtime")
        modules.add(folder)
    if (qt / "qml/QtWebEngine").resolve() not in modules:
        raise ValueError("The EPUB WebEngine import must be retained")
    return modules


def trim_runtime(app: Path, *, build_root: Path) -> dict:
    """Plan then unlink expendable files inside an explicitly bounded build folder."""
    app = app.resolve()
    if (
        not app.is_relative_to(build_root.resolve())
        or app == build_root.resolve()
        or app.name != "LinguaLoop"
    ):
        raise ValueError("Runtime trimming is restricted to a new LinguaLoop build payload")
    runtime = app / "runtime"
    qt = runtime / "Lib/site-packages/PySide6"
    source = runtime / "Lib/site-packages/lingualoop"
    paths = list(runtime.rglob("*"))
    if any(p.is_symlink() or not p.resolve().is_relative_to(app) for p in paths):
        raise ValueError("Runtime payload must not contain links")
    modules = python_qt_modules(source)
    # Importing bindings also resolves PySide's generated Python-level dependencies.
    code = (
        "import importlib,json,sys; "
        f"[importlib.import_module('PySide6.'+m) for m in {sorted(modules)!r}]; "
        "print(json.dumps(sorted(n.split('.')[1] for n in sys.modules if n.startswith('PySide6.Qt'))))"
    )
    loaded = subprocess.run(
        [str(runtime / "python.exe"), "-I", "-c", code],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    modules.update(json.loads(loaded.stdout))
    imports = qml_modules(qt, source / "desktop/qml")
    plugins = {
        "platforms",
        "platforminputcontexts",
        "imageformats",
        "iconengines",
        "multimedia",
        "networkinformation",
        "styles",
        "tls",
    }
    seeds = {qt / (name + ".pyd") for name in modules} | {qt / "QtWebEngineProcess.exe"}
    seeds.update(
        p
        for p in qt.glob("*.dll")
        if p.name.lower().startswith(("opengl32sw", "d3dcompiler", "av", "sw"))
    )
    seeds.update(p for group in plugins for p in (qt / "plugins" / group).rglob("*.dll"))
    for folder in imports:
        seeds.update(folder.glob("*.dll"))
    retained_native = native_closure(qt, seeds)
    qml_root = qt / "qml"
    qml_owners = {p.parent.resolve() for p in qml_root.rglob("qmldir")}
    locale_files = {"en-US.pak", "zh-CN.pak", "zh-TW.pak", "ja.pak"}
    removed = []
    before = sum(p.stat().st_size for p in paths if p.is_file())
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(runtime)
        parts, name = relative.parts, path.name
        discard = "__pycache__" in parts or path.suffix.lower() in {".pyc", ".pyo", ".pyi", ".pdb"}
        discard |= parts[0] in {"include", "libs", "tcl"}
        discard |= relative.as_posix().startswith(("Lib/idlelib/", "Lib/tkinter/"))
        discard |= parts[0] == "DLLs" and (
            name.startswith("_test") or name in {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll"}
        )
        if path.is_relative_to(qt):
            qt_parts = path.relative_to(qt).parts
            discard |= ".debug." in name or path.suffix.lower() in {
                ".lib",
                ".obj",
                ".h",
                ".hpp",
                ".cpp",
            }
            discard |= any(part.startswith("objects-") for part in qt_parts)
            discard |= qt_parts[0] in {
                "metatypes",
                "include",
                "typesystems",
                "glue",
                "doc",
                "scripts",
            }
            if len(qt_parts) == 1 and path.suffix.lower() in {".pyd", ".dll", ".exe"}:
                discard |= path not in retained_native
            if qt_parts[0] == "plugins":
                discard |= qt_parts[1] not in plugins
            if qt_parts[0] == "qml":
                owner = next((p.resolve() for p in path.parents if p.resolve() in qml_owners), None)
                discard |= owner not in imports or path.suffix == ".qmltypes"
            if qt_parts[0] == "translations":
                discard |= name not in locale_files and not name.endswith(
                    ("_en.qm", "_en_US.qm", "_zh_CN.qm", "_zh_TW.qm", "_ja.qm")
                )
        if discard:
            removed.append({"path": relative.as_posix(), "bytes": path.stat().st_size})
    # No mutation occurs until imports, QML scanning and PE validation all succeed.
    for entry in removed:
        (runtime / entry["path"]).unlink()
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    reclaimed = sum(entry["bytes"] for entry in removed)
    return {
        "policy": "windows-slim-v1",
        "before_bytes": before,
        "after_bytes": before - reclaimed,
        "removed_bytes": reclaimed,
        "python_qt_modules": sorted(modules),
        "qml_modules": sorted(p.relative_to(qml_root).as_posix() for p in imports),
        "native_files": sorted(p.relative_to(qt).as_posix() for p in retained_native),
        "removed": removed,
    }
