"""Suggest well-known third-party libraries when DIY patterns are detected.

Checks for common "not-invented-here" patterns where a popular library
would be more appropriate than a custom implementation.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Optional

from crb.config.settings import PythonAnalyzerConfig
from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg


class _LibrarySuggester(ast.NodeVisitor):
    """Detect custom implementations of functionality provided by well-known libraries."""

    def __init__(self, file_path: str, source: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.source = source
        self.lang = lang
        self.findings: list[Finding] = []
        self._imported_modules: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._imported_modules.add(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self._imported_modules.add(node.module.split(".")[0])
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Pattern: custom CLI using sys.argv (AST-based to avoid self-detection)
        has_sys_argv = any(
            isinstance(n, ast.Attribute) and n.attr == "argv"
            and isinstance(n.value, ast.Name) and n.value.id == "sys"
            for n in ast.walk(node)
        )
        if has_sys_argv and "click" not in self._imported_modules:
            self._maybe_add("cli_argparse", node.lineno, name=node.name)

        # Pattern: manual retry via time.sleep (AST-based)
        has_time_sleep = any(
            isinstance(n, ast.Attribute) and n.attr == "sleep"
            and isinstance(n.value, ast.Name) and n.value.id == "time"
            for n in ast.walk(node)
        )
        if has_time_sleep and "tenacity" not in self._imported_modules and "backoff" not in self._imported_modules:
            self._maybe_add("manual_retry", node.lineno, name=node.name)

    def _maybe_add(self, key: str, line: int, **kwargs: object) -> None:
        title, msg, suggestion = _finding_msg(self.lang, key, **kwargs)
        self.findings.append(
            Finding(
                file=self.file_path,
                line=line,
                severity=Severity.MAJOR,
                category=FindingCategory.DEPENDENCY,
                title=title,
                message=msg,
                suggestion=suggestion,
            )
        )


def analyze_file(
    file_path: str,
    _config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Suggest third-party libraries when DIY patterns are detected.

    Args:
        file_path: Path to the .py file.
        _config: Analyzer configuration.
        lang: Output language for messages.

    Returns:
        List of suggestions.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _LibrarySuggester(file_path=file_path, source=source, lang=lang)
    visitor.visit(tree)
    return visitor.findings
