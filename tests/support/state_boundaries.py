"""Identify shared-state writes and cross-facade notifications for debt ratcheting."""

import ast
from tests.support.boundaries import PrivateAccess


def state_boundary_violations(source):
    tree = ast.parse(source)

    class SignalAccess(PrivateAccess):
        def __init__(self):
            super().__init__()
            self.signals = set()

        def visit_Call(self, node):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"
                and self.foreign(node.func.value)
            ):
                self.signals.add(node.lineno)
            super().visit_Call(node)

    access = SignalAccess()
    access.visit(tree)
    violations = set()
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for method in (
            n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for node in ast.walk(method):
                if cls.name.endswith("Mixin") and isinstance(
                    node, (ast.Assign, ast.AnnAssign, ast.AugAssign)
                ):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if ast.unparse(target).startswith("self."):
                            violations.add(f"{cls.name}.{method.name}:write:{ast.unparse(target)}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    name = ast.unparse(node.func)
                    if node.lineno in access.signals:
                        violations.add(f"{cls.name}.{method.name}:signal:{name}")
    return sorted(violations)


def collaborator_violations(source):
    """Plain state owners accept narrow ports/data instead of complete Qt facades."""
    tree = ast.parse(source)
    violations = set()
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
            if (node.module or "").startswith("PySide"):
                violations.add("qt-import")
        if isinstance(node, ast.Import) and any(a.name.startswith("PySide") for a in node.names):
            violations.add("qt-import")
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            annotation = ast.unparse(node.annotation) if node.annotation else ""
            annotation = aliases.get(annotation, annotation)
            if node.arg in {"vm", "viewmodel", "workspace", "library", "facade"} or any(
                name in annotation for name in ("ViewModel", "DesktopWorkspaceController")
            ):
                violations.add("facade-parameter")
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if node.attr.lstrip("_") in {"vm", "viewmodel", "workspace", "library", "facade"}:
                violations.add("facade-reference")
    return sorted(violations)
