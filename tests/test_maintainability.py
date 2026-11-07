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


def test_conversation_display_updates_use_the_single_facade():
    violations = []
    legacy = {"_messages", "_streaming_text", "_pending_user_text", "_response_timing",
              "_recording_seconds", "_error"}
    for path in (SOURCE / "desktop").glob("*.py"):
        if path.name == "conversation_presentation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                target = ast.unparse(node)
                if ".presentation." in target or target.startswith("self._conversation.") or (
                    path.name in {"viewmodel.py", "learning_presentation.py"}
                    and ast.unparse(node.value) == "self" and node.attr in legacy
                ):
                    violations.append(f"{path.name}:{node.lineno}: display assignment {target}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = ast.unparse(node.func)
                if path.name != "conversation_view.py" and name == "self.messagesChanged.emit":
                    violations.append(f"{path.name}:{node.lineno}: message signal outside entry point")
                if name in {
                    f"self.vm.{signal}.emit" for signal in
                    ("messagesChanged", "historyChanged", "messageSent", "uiChanged", "busyChanged")
                }:
                    violations.append(f"{path.name}:{node.lineno}: controller emits facade signal")
                if name in {"self.vm.refresh_session_state", "self.vm.restore_last_reply"}:
                    violations.append(f"{path.name}:{node.lineno}: controller bypasses display event")
                if name == "self._conversation.apply" and path.name != "conversation_view.py":
                    violations.append(f"{path.name}:{node.lineno}: owner update outside entry point")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"setattr", "delattr"} and node.args
                and any(name in ast.unparse(node.args[0]) for name in ("presentation", "_conversation"))):
                violations.append(f"{path.name}:{node.lineno}: dynamic display assignment")
    assert not violations, "\n".join(violations)


def test_legacy_desktop_import_entrypoints_do_not_reappear():
    removed = {"loadMaterial", "importMaterial", "startPractice"}
    for path in (SOURCE / "desktop").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in removed, f"{path.name}:{node.lineno}: {node.name}"
