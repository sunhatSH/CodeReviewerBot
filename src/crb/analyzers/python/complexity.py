"""Cyclomatic complexity and function line count analyzer for Python.

Uses Python's built-in `ast` module for static analysis.
Supports @complex_func decorator to suppress warnings.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Optional

from crb.config.settings import PythonAnalyzerConfig
from crb.report.models import (
    Finding,
    FindingCategory,
    OutputLang,
    ReviewReport,
    Severity,
    _finding_msg,
)

# Node types that increase cyclomatic complexity
_DECISION_NODES = (
    ast.If,
    ast.While,
    ast.For,
    ast.AsyncFor,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
    ast.Try,
)

_BOOLEAN_OPS = (ast.And, ast.Or)


def _get_decorator_names(decorator_list: list[ast.expr]) -> list[str]:
    """Extract decorator names from an AST decorator list."""
    names = []
    for d in decorator_list:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            names.append(d.attr)
        elif isinstance(d, ast.Call):
            if isinstance(d.func, ast.Name):
                names.append(d.func.id)
            elif isinstance(d.func, ast.Attribute):
                names.append(d.func.attr)
    return names


def _is_ignored(decorator_names: list[str], ignore_list: list[str]) -> bool:
    """Check if any decorator matches the ignore list."""
    return any(name in ignore_list for name in decorator_names)


class _ComplexityVisitor(ast.NodeVisitor):
    """AST visitor that computes cyclomatic complexity."""

    def __init__(self):
        self.complexity = 1  # base complexity

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:  # bare except doesn't add complexity
            self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if isinstance(node.op, _BOOLEAN_OPS):
            # each bool operator adds N-1 to complexity
            self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.complexity += 1
        self.generic_visit(node)


def _count_lines(node: ast.AST) -> int:
    """Count physical lines of an AST node (end_lineno - lineno)."""
    if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
        return node.end_lineno - node.lineno + 1
    return 0


def _find_nested_classes(node: ast.AST) -> list[ast.ClassDef]:
    """Find all ClassDef nodes directly inside a node."""
    classes = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            classes.append(child)
    return classes


def analyze_file(
    file_path: str,
    config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for complexity issues.

    Args:
        file_path: Path to the .py file.
        config: Analyzer configuration, uses defaults if None.
        lang: Output language for messages.

    Returns:
        List of findings.
    """
    if config is None:
        config = PythonAnalyzerConfig()

    findings: list[Finding] = []
    path = Path(file_path)

    if not path.exists():
        return findings

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        title, msg, suggestion = _finding_msg(lang, "syntax_error", msg=e.msg)
        findings.append(
            Finding(
                file=file_path,
                line=e.lineno or 0,
                severity=Severity.CRITICAL,
                category=FindingCategory.COMPLEXITY,
                title=title,
                message=msg,
                suggestion=suggestion,
            )
        )
        return findings

    # --- Function-level analysis ---
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = _get_decorator_names(node.decorator_list)
            if _is_ignored(decorators, config.ignore_decorators):
                continue

            visitor = _ComplexityVisitor()
            visitor.visit(node)
            cc = visitor.complexity
            func_lines = _count_lines(node)

            # Cyclomatic complexity check
            if cc > config.complexity.cyclomatic:
                title, msg, suggestion = _finding_msg(
                    lang, "high_complexity",
                    name=node.name, cc=cc, threshold=config.complexity.cyclomatic,
                )
                findings.append(
                    Finding(
                        file=file_path,
                        line=node.lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.COMPLEXITY,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

            # Function line count check
            if func_lines > config.complexity.function_lines:
                title, msg, suggestion = _finding_msg(
                    lang, "overly_long_function",
                    name=node.name, lines=func_lines, threshold=config.complexity.function_lines,
                )
                findings.append(
                    Finding(
                        file=file_path,
                        line=node.lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.COMPLEXITY,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

        # --- Class-level analysis ---
        if isinstance(node, ast.ClassDef):
            decorators = _get_decorator_names(node.decorator_list)
            if _is_ignored(decorators, config.ignore_decorators):
                continue

            class_lines = _count_lines(node)
            if class_lines > config.complexity.class_lines:
                title, msg, suggestion = _finding_msg(
                    lang, "overly_large_class",
                    name=node.name, lines=class_lines, threshold=config.complexity.class_lines,
                )
                findings.append(
                    Finding(
                        file=file_path,
                        line=node.lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.COMPLEXITY,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

    return findings


def analyze_directory(
    dir_path: str,
    config: Optional[PythonAnalyzerConfig] = None,
) -> ReviewReport:
    """Recursively analyze all Python files in a directory.

    Args:
        dir_path: Path to the directory.
        config: Analyzer configuration.

    Returns:
        A ReviewReport containing all findings.
    """
    if config is None:
        config = PythonAnalyzerConfig()

    report = ReviewReport(target=dir_path)

    for root, _dirs, files in os.walk(dir_path):
        # Skip archived and hidden directories
        if "/archived" in root or "/." in root:
            continue
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            findings = analyze_file(fpath, config)
            for finding in findings:
                report.add_finding(finding)

    return report
