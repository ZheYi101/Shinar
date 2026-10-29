"""Keep domain and orchestration independent of concrete UI and service adapters."""

import ast
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
    ("area", "allowed_layers", "allowed_external"),
    [
        ("core", {"core"}, {"pydantic"}),
        ("kernel", {"core", "kernel"}, {"pydantic"}),
        ("realtime/protocol.py", set(), set()),
    ],
)
def test_inner_layers_do_not_import_concrete_adapters(
    area: str, allowed_layers: set[str], allowed_external: set[str]
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
            parts = dependency.split(".")
            if parts[0] == "lingualoop":
                allowed = len(parts) == 1 or parts[1] in allowed_layers
            else:
                allowed = parts[0] in sys.stdlib_module_names | allowed_external | {"__future__"}
            if not allowed:
                violations.append(f"{relative}:{line}: {dependency}")
    assert not violations, "Inner layers depend on concrete adapters:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        ("import PySide6.QtCore", "lingualoop.core", "PySide6.QtCore"),
        ("from lingualoop import desktop", "lingualoop.core", "lingualoop.desktop"),
        ("from ..providers import mock", "lingualoop.core", "lingualoop.providers.mock"),
        ("from .domain import Message", "lingualoop.core", "lingualoop.core.domain.Message"),
    ],
)
def test_import_guard_resolves_aliases_and_relative_imports(
    source: str, package: str, expected: str
) -> None:
    assert expected in {module for _, module in imported_modules(ast.parse(source), package)}
