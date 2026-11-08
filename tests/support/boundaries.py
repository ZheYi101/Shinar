"""Small AST checks for desktop ownership, aliases and runtime import direction."""

import ast
from pathlib import Path


ROLES = {"vm", "viewmodel", "voice", "workbench", "call", "workspace", "controller", "library"}


def collaborator_type(annotation: ast.AST | None) -> bool:
    value = ast.unparse(annotation) if annotation else ""
    return any(word in value for word in ("ViewModel", "Controller", "Workbench", "Coordinator"))


class PrivateAccess(ast.NodeVisitor):
    def __init__(self):
        self.aliases = set()
        self.violations = set()
        self.types = {}
        self.modules = set()
        self.accessors = {"getattr", "setattr", "delattr"}

    def typed(self, annotation):
        if annotation is None:
            return False
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            return collaborator_type(ast.Name(id=self.types.get(annotation.value, annotation.value)))
        return collaborator_type(annotation) or any(
            collaborator_type(ast.Name(id=self.types.get(node.id, "")))
            for node in ast.walk(annotation)
            if isinstance(node, ast.Name)
        )

    def foreign(self, value):
        key = ast.unparse(value)
        if key in self.aliases:
            return True
        if isinstance(value, ast.Name):
            return value.id in ROLES | self.modules or self.typed(value)
        if isinstance(value, ast.Attribute):
            return (
                isinstance(value.value, ast.Name)
                and value.value.id == "self"
                and value.attr.lstrip("_") in ROLES
            ) or self.foreign(value.value)
        if isinstance(value, ast.Call):
            return self.typed(value.func)
        return False

    def bind(self, target, value, annotation=None):
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            for left, right in zip(target.elts, value.elts):
                self.bind(left, right)
        elif self.foreign(value) or self.typed(annotation):
            self.aliases.add(ast.unparse(target))
        else:
            self.aliases.discard(ast.unparse(target))

    def visit_Assign(self, node):
        for target in node.targets:
            self.bind(target, node.value)
            if isinstance(node.value, ast.Name) and node.value.id in self.accessors:
                self.accessors.add(ast.unparse(target))
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value:
            self.bind(node.target, node.value, node.annotation)
        elif self.typed(node.annotation):
            self.aliases.add(ast.unparse(node.target))
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        before = set(self.aliases)
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if self.typed(argument.annotation):
                self.aliases.add(argument.arg)
        self.generic_visit(node)
        # Attribute aliases initialized by a constructor belong to the class.
        self.aliases = before | {key for key in self.aliases if key.startswith("self.")}

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        before = self.aliases
        self.aliases = set()
        self.generic_visit(node)
        self.aliases = before

    def visit_Attribute(self, node):
        if (
            node.attr.startswith("_")
            and not node.attr.startswith("__")
            and self.foreign(node.value)
        ):
            self.violations.add((node.lineno, ast.unparse(node)))
        self.generic_visit(node)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in self.accessors
            and len(node.args) >= 2
            and self.foreign(node.args[0])
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value.startswith("_")
        ):
            self.violations.add((node.lineno, ast.unparse(node)))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.types[alias.asname or alias.name] = alias.name
            if node.module == "builtins" and alias.name in {"getattr", "setattr", "delattr"}:
                self.accessors.add(alias.asname or alias.name)
        if node.level or (node.module or "").startswith(("shinar.desktop", "shinar.application")):
            for alias in node.names:
                if alias.name.startswith("_"):
                    self.violations.add((node.lineno, ast.unparse(node)))

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name.startswith(("shinar.desktop", "shinar.application")):
                self.modules.add(alias.asname or alias.name.split(".")[0])


def private_accesses(source: str) -> list[tuple[int, str]]:
    visitor = PrivateAccess()
    visitor.visit(ast.parse(source))
    return sorted(visitor.violations)


def desktop_violations(root: Path) -> list[str]:
    return [
        f"{path.relative_to(root)}:{line}: {expression}"
        for path in sorted(root.rglob("*.py"))
        for line, expression in private_accesses(path.read_text(encoding="utf-8-sig"))
    ]


class RuntimeImports(ast.NodeVisitor):
    def __init__(self, package):
        self.package = package
        self.imports = set()
        self.type_guards = {"TYPE_CHECKING", "typing.TYPE_CHECKING"}

    def visit_If(self, node):
        if ast.unparse(node.test) in self.type_guards:
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def visit_Import(self, node):
        self.imports.update(alias.name for alias in node.names)
        for alias in node.names:
            if alias.name == "typing":
                self.type_guards.add((alias.asname or alias.name) + ".TYPE_CHECKING")

    def visit_ImportFrom(self, node):
        if node.module == "typing":
            self.type_guards.update(
                alias.asname or alias.name for alias in node.names if alias.name == "TYPE_CHECKING"
            )
        base = self.package
        if node.level:
            base = ".".join(base.split(".")[: len(base.split(".")) - node.level + 1])
            module = ".".join(filter(None, (base, node.module)))
        else:
            module = node.module or ""
        self.imports.add(module)
        self.imports.update(module + "." + alias.name for alias in node.names)


def import_cycles(root: Path, package: str) -> list[list[str]]:
    modules = {}
    for path in root.rglob("*.py"):
        suffix = ".".join(path.relative_to(root).with_suffix("").parts)
        name = (package + "." + suffix).removesuffix(".__init__")
        parent = name if path.name == "__init__.py" else name.rpartition(".")[0]
        visitor = RuntimeImports(parent)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig")))
        modules[name] = visitor.imports
    cycles, visiting, done = [], [], set()

    def visit(name):
        if name in visiting:
            cycles.append(visiting[visiting.index(name) :] + [name])
            return
        if name in done:
            return
        visiting.append(name)
        for target in sorted(modules[name] & modules.keys() - {name}):
            visit(target)
        visiting.pop()
        done.add(name)

    for name in sorted(modules):
        visit(name)
    return cycles
