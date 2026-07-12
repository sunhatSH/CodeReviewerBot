"""Orphan code detector — finds unreferenced functions, classes, and methods.

Uses AST to parse all Python files in a project, builds a cross-reference
graph, and reports defined symbols that are never referenced from any entry
point or other reachable code.
"""

from __future__ import annotations

import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Symbols that are implicitly called / used by Python runtime
_IMPLICIT_CALLABLES = frozenset({
    "__init__", "__new__", "__enter__", "__exit__", "__aenter__", "__aexit__",
    "__call__", "__str__", "__repr__", "__len__", "__getitem__", "__setitem__",
    "__delitem__", "__iter__", "__next__", "__contains__", "__bool__",
    "__hash__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__add__", "__sub__", "__mul__", "__truediv__", "__floordiv__",
    "__mod__", "__pow__", "__and__", "__or__", "__xor__", "__lshift__",
    "__rshift__", "__iadd__", "__isub__", "__imul__", "__getattr__",
    "__setattr__", "__delattr__", "__format__", "__reduce__", "__copy__",
    "__deepcopy__", "__del__", "__index__", "__int__", "__float__",
    "__neg__", "__pos__", "__abs__", "__invert__",
    # async context managers
    "__aiter__", "__anext__",
})

# Top-level entry-point-like names that are likely called externally
_ENTRY_POINT_PREFIXES = frozenset({
    "main", "run", "start", "app", "application",
    "handler", "lambda_handler", "serve",
})


class _Symbol:
    """A symbol defined in a source file."""

    def __init__(self, name: str, kind: str, filepath: str, lineno: int):
        self.name = name
        self.kind = kind  # "function", "class", "method", "variable"
        self.filepath = filepath
        self.lineno = lineno
        self.parent_class: Optional[str] = None

    @property
    def qualified_name(self) -> str:
        if self.parent_class:
            return f"{self.parent_class}.{self.name}"
        return self.name

    @property
    def is_dunder(self) -> bool:
        return self.name in _IMPLICIT_CALLABLES

    @property
    def is_entry_point(self) -> bool:
        return self.name in _ENTRY_POINT_PREFIXES


def _resolve_import(node: ast.AST) -> list[tuple[str, Optional[str]]]:
    """Resolve an import statement to (module, alias) pairs."""
    results: list[tuple[str, Optional[str]]] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            results.append((alias.name, alias.asname))
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            full = f"{module}.{alias.name}" if module else alias.name
            results.append((full, alias.asname))
    return results


def _collect_definitions(tree: ast.AST, filepath: str) -> list[_Symbol]:
    """Collect all symbol definitions from an AST."""
    symbols: list[_Symbol] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            sym = _Symbol(node.name, "function", filepath, node.lineno)
            # Check if this is a method inside a class
            for parent in ast.walk(tree):
                if isinstance(parent, ast.ClassDef):
                    for child in parent.body:
                        if child is node:
                            sym.kind = "method"
                            sym.parent_class = parent.name
                            break
            symbols.append(sym)

        elif isinstance(node, ast.AsyncFunctionDef):
            sym = _Symbol(node.name, "function", filepath, node.lineno)
            for parent in ast.walk(tree):
                if isinstance(parent, ast.ClassDef):
                    for child in parent.body:
                        if child is node:
                            sym.kind = "method"
                            sym.parent_class = parent.name
                            break
            symbols.append(sym)

        elif isinstance(node, ast.ClassDef):
            symbols.append(_Symbol(node.name, "class", filepath, node.lineno))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(
                        _Symbol(target.id, "variable", filepath, target.lineno)
                    )

    return symbols


def _collect_references(tree: ast.AST) -> set[str]:
    """Collect all name references from an AST.

    Returns a set of referenced name strings (fully qualified when possible).
    """
    refs: set[str] = set()
    imported_names: dict[str, str] = {}  # alias -> original_name

    for node in ast.walk(tree):
        # Track imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for full_name, alias in _resolve_import(node):
                if alias:
                    imported_names[alias] = full_name
                else:
                    short = full_name.split(".")[-1]
                    imported_names[short] = full_name
            continue

        # Name nodes: variable references
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Load, ast.Del)):
                refs.add(node.id)

        # Attribute access: obj.attr -> adds both "obj" and fully resolved
        if isinstance(node, ast.Attribute):
            if isinstance(node.ctx, ast.Load):
                refs.add(node.attr)

        # Decorators
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            refs.add(node.func.id)

        # Class base specifications
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name):
                    refs.add(base.id)

    return refs


def _is_potential_entry_point(sym: _Symbol, tree: ast.AST) -> bool:
    """Check if a symbol is a potential entry point (called from outside)."""
    if sym.is_entry_point:
        return True
    # Check if it's decorated with a CLI/route decorator
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != sym.name:
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name):
                    if decorator.id in ("cli", "app", "router", "blueprint"):
                        return True
                    if decorator.id in ("click", "fastapi", "flask"):
                        return True
                elif isinstance(decorator, ast.Attribute):
                    if decorator.attr in ("command", "route", "get", "post",
                                          "put", "delete", "patch", "on"):
                        return True
    return False


def _is_entry_file(filepath: str) -> bool:
    """Check if a file is likely an entry point."""
    name = os.path.basename(filepath)
    return name in ("__main__.py", "main.py", "cli.py", "app.py", "run.py")


def analyze_files(
    file_paths: list[str],
    ignore_patterns: Optional[list[str]] = None,
    lang: OutputLang = OutputLang.CH,
) -> list[Finding]:
    """Analyze Python files for orphan (unreferenced) symbols.

    Args:
        file_paths: List of Python file paths to analyze.
        ignore_patterns: Regex patterns for symbol names to skip.
        lang: Output language.

    Returns:
        List of findings for unreferenced symbols.
    """
    findings: list[Finding] = []

    if not file_paths:
        return findings

    # Phase 1: Collect all definitions per file
    file_defs: dict[str, list[_Symbol]] = {}
    # Phase 2: Collect all references per file (cross-file)
    file_refs: dict[str, set[str]] = {}
    all_trees: dict[str, ast.AST] = {}

    for fp in file_paths:
        path = Path(fp)
        if not path.exists() or not fp.endswith(".py"):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=fp)
        except (SyntaxError, OSError):
            continue

        all_trees[fp] = tree
        file_defs[fp] = _collect_definitions(tree, fp)
        file_refs[fp] = _collect_references(tree)

    # Phase 3: Build cross-reference — which symbols are referenced where
    # Track counts: symbol_name -> number of files that reference it (excluding own file)
    ref_counts: dict[str, int] = defaultdict(int)
    # Track which specific symbols are used in each file
    used_symbols: set[str] = set()

    for fp, refs in file_refs.items():
        for ref in refs:
            used_symbols.add(ref)

    # Also track references within the same file (self-references)
    own_refs: dict[tuple[str, str], bool] = defaultdict(bool)  # (file, name) -> referenced_in_own_file

    for fp, tree in all_trees.items():
        defs_in_file = {s.name for s in file_defs.get(fp, [])}
        refs_in_file = file_refs.get(fp, set())
        for name in defs_in_file:
            if name in refs_in_file:
                own_refs[(fp, name)] = True

    # Phase 4: Find orphans
    for fp, defs in file_defs.items():
        tree = all_trees.get(fp)
        if tree is None:
            continue

        is_entry_file = _is_entry_file(fp)

        for sym in defs:
            # Skip entry points
            if sym.is_dunder:
                continue
            if is_entry_file and sym.is_entry_point:
                continue
            if tree is not None and _is_potential_entry_point(sym, tree):
                continue

            # Count how many files reference this symbol
            external_refs = 0
            for other_fp, refs in file_refs.items():
                if other_fp == fp:
                    continue
                if sym.name in refs:
                    external_refs += 1

            # Also check if self-referenced within file
            is_self_ref = own_refs.get((fp, sym.name), False)

            # Skip names that are common base classes or well-known names
            # that are likely referenced indirectly
            common_names = {
                "self", "cls", "args", "kwargs", "value", "item", "key",
                "result", "data", "config", "logger", "log", "db", "session",
                "request", "response", "ctx", "context", "event", "exception",
                "error", "message", "status", "type", "name", "path", "url",
                "file", "files", "dir", "directory", "tmp", "temp", "output",
                "input", "text", "lines", "line", "content", "body", "header",
                "headers", "params", "param", "query", "form", "json", "xml",
                "html", "css", "js", "ts", "md", "rst", "txt",
            }

            # Skip AST visitor methods (called dynamically by ast.NodeVisitor)
            if sym.kind == "method" and sym.name.startswith("visit_"):
                continue

            # Skip methods of private classes (implicit dispatch patterns)
            if sym.parent_class and sym.parent_class.startswith("_"):
                continue

            if (
                external_refs == 0
                and not is_self_ref
                and sym.name not in common_names
                and not sym.name.startswith("_")
                and not sym.name.startswith("test_")
            ):
                title, msg, suggestion = _finding_msg(
                    lang, "orphan_code",
                    name=sym.qualified_name,
                    kind=sym.kind,
                    file=os.path.relpath(fp),
                )
                findings.append(
                    Finding(
                        file=fp,
                        line=sym.lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.ORPHAN,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

    return findings
