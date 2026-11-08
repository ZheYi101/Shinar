"""Identify shared-state writes and cross-facade notifications for debt ratcheting."""

import ast


def state_boundary_violations(source):
    tree = ast.parse(source)
    violations = set()
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for method in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(method):
                if cls.name.endswith("Mixin") and isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if ast.unparse(target).startswith("self."):
                            violations.add(f"{cls.name}.{method.name}:write:{ast.unparse(target)}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    name = ast.unparse(node.func)
                    if name.endswith(".emit") and name.startswith(("self.vm.", "self._vm.", "self.viewmodel.")):
                        violations.add(f"{cls.name}.{method.name}:signal:{name}")
    return sorted(violations)
