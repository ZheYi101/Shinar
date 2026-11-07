"""Executable size and collaboration boundaries for first-party production code."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "lingualoop"


def source_files():
    return sorted(
        path
        for path in SOURCE.rglob("*")
        if path.is_file() and path.suffix in {".py", ".qml", ".js"} and "foliate" not in path.parts
    )


def test_production_files_and_functions_have_bounded_size():
    violations = []
    for path in source_files():
        text = path.read_text(encoding="utf-8-sig")
        label = path.relative_to(SOURCE)
        if len(text.splitlines()) > 800:
            violations.append(f"{label}: file exceeds 800 physical lines")
        if path.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = node.end_lineno - node.lineno + 1
                if size > 100:
                    violations.append(f"{label}:{node.lineno} {node.name}: {size} lines")
    assert not violations, "\n".join(violations)


def test_desktop_collaborators_use_public_interfaces():
    violations = []
    collaborators = {"self.vm", "self.voice", "vm", "viewmodel", "self.workbench"}
    for path in (SOURCE / "desktop").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and ast.unparse(node.value) in collaborators
            ):
                violations.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    assert not violations, "\n".join(violations)


def test_plain_source_and_process_boundaries_do_not_import_qt():
    for name in ("application/source_loading.py", "infrastructure/blocking_jobs.py"):
        path = SOURCE / name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("PySide") for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("PySide")
