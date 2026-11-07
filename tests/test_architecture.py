"""Keep domain and orchestration independent of concrete UI and service adapters."""

import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SOURCE / "lingualoop"


def imported_modules(tree: ast.AST, package: str) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parents = package.split(".")
                base = ".".join(parents[: len(parents) - node.level + 1])
                module = ".".join(part for part in (base, node.module) if part)
            else:
                module = node.module or ""
            yield node.lineno, module
            for alias in node.names:
                if alias.name != "*":
                    yield node.lineno, f"{module}.{alias.name}"


@pytest.mark.parametrize(
    ("area", "allowed_internal", "allowed_external"),
    [
        ("core", {"lingualoop.core"}, {"pydantic"}),
        ("kernel", {"lingualoop.core", "lingualoop.kernel"}, {"pydantic"}),
        ("realtime/protocol.py", set(), set()),
        ("application/source_document.py", {"lingualoop.core"}, set()),
        (
            "infrastructure/epub_reader.py",
            {"lingualoop.core.knowledge", "lingualoop.infrastructure.material_import"},
            set(),
        ),
    ],
)
def test_inner_layers_do_not_import_concrete_adapters(
    area: str, allowed_internal: set[str], allowed_external: set[str]
) -> None:
    target = PACKAGE / area
    paths = [target] if target.is_file() else sorted(target.rglob("*.py"))
    assert paths, f"No modules checked for {area}"
    violations = []
    for path in paths:
        relative = path.relative_to(SOURCE)
        package = ".".join(relative.parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for line, dependency in imported_modules(tree, package):
            if not dependency_allowed(dependency, allowed_internal, allowed_external):
                violations.append(f"{relative}:{line}: {dependency}")
    assert not violations, "Inner layers depend on concrete adapters:\n" + "\n".join(violations)


def dependency_allowed(
    dependency: str, allowed_internal: set[str], allowed_external: set[str]
) -> bool:
    root = dependency.split(".")[0]
    if root == "lingualoop":
        return dependency == root or any(
            dependency == module or dependency.startswith(module + ".")
            for module in allowed_internal
        )
    return root in sys.stdlib_module_names | allowed_external | {"__future__"}


def test_webengine_dependencies_stay_in_desktop_reader_adapters() -> None:
    allowed_python = {"desktop/app.py", "desktop/reader_runtime.py"}
    violations = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        package = ".".join(path.relative_to(SOURCE).parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for line, dependency in imported_modules(tree, package):
            if dependency.startswith(("PySide6.QtWebEngine", "PySide6.QtWebChannel")):
                if relative not in allowed_python:
                    violations.append(f"{relative}:{line}: {dependency}")
    for path in sorted((PACKAGE / "desktop/qml").rglob("*.qml")):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative == "desktop/qml/components/FoliateSurface.qml":
            continue
        if re.search(
            r"^\s*import\s+Qt(?:WebEngine|WebChannel)\b", path.read_text(encoding="utf-8"), re.M
        ):
            violations.append(f"{relative}: direct WebEngine/WebChannel import")
    assert not violations, "Reader runtime dependencies escaped their adapters:\n" + "\n".join(
        violations
    )


def test_reader_vendor_files_and_licenses_match_the_pinned_manifest() -> None:
    root = PACKAGE / "desktop/reader/foliate"
    manifest = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["commit"])
    expected = dict(manifest["files"])
    expected.update(
        {name: license["sha256"] for name, license in manifest["vendor_licenses"].items()}
    )
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    assert actual == set(expected) | {"UPSTREAM.json"}, "Untracked or missing reader vendor files"
    assert "LICENSE" in expected and "vendor/ZIP-LICENSE" in expected
    for name, checksum in expected.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == checksum, name


@pytest.mark.parametrize(
    ("dependency", "allowed"),
    [
        ("lingualoop.core.knowledge.SourceSection", True),
        ("lingualoop.corex", False),
        ("lingualoop.desktop.workspace", False),
        ("lingualoop.infrastructure.sqlite_store", False),
        ("PySide6.QtCore", False),
        ("httpx", False),
        ("hashlib.sha256", True),
    ],
)
def test_dependency_guard_rejects_cross_layer_and_external_imports(
    dependency: str, allowed: bool
) -> None:
    assert dependency_allowed(dependency, {"lingualoop.core"}, set()) is allowed


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        ("import PySide6.QtCore", "lingualoop.core", "PySide6.QtCore"),
        ("from lingualoop import desktop", "lingualoop.core", "lingualoop.desktop"),
        ("from ..providers import mock", "lingualoop.core", "lingualoop.providers.mock"),
        ("from .domain import Message", "lingualoop.core", "lingualoop.core.domain.Message"),
        ("from PySide6 import QtWebEngineCore", "lingualoop.desktop", "PySide6.QtWebEngineCore"),
    ],
)
def test_import_guard_resolves_aliases_and_relative_imports(
    source: str, package: str, expected: str
) -> None:
    assert expected in {module for _, module in imported_modules(ast.parse(source), package)}
