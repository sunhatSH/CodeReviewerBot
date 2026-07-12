"""Code style checker for Python files.

Delegate to pycodestyle/flake8 rules via AST analysis.
Generates Major-severity findings placed at the end of the report.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Optional

from crb.config.settings import PythonAnalyzerConfig
from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg


class _StyleVisitor(ast.NodeVisitor):
    """AST-based style checks (non-exhaustive, complementary to linters)."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []
        self._import_count = 0

    def _check_wildcard(self, names: list[ast.alias], lineno: int) -> None:
        for alias in names:
            if alias.name == "*":
                title, msg, suggestion = _finding_msg(self.lang, "wildcard_import")
                self.findings.append(
                    Finding(
                        file=self.file_path,
                        line=lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.STYLE,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

    def visit_Import(self, node: ast.Import) -> None:
        self._import_count += len(node.names)
        self._check_wildcard(node.names, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._import_count += len(node.names)
        self._check_wildcard(node.names, node.lineno)
        if node.module == "__future__":
            pass  # future imports are fine
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        title, msg, suggestion = _finding_msg(
            self.lang, "global_statement", names=", ".join(node.names),
        )
        self.findings.append(
            Finding(
                file=self.file_path,
                line=node.lineno,
                severity=Severity.MAJOR,
                category=FindingCategory.STYLE,
                title=title,
                message=msg,
                suggestion=suggestion,
            )
        )

    def visit_Name(self, node: ast.Name) -> None:
        # Check for single-character names (excluding common loop vars)
        if (
            len(node.id) == 1
            and isinstance(node.ctx, ast.Store)
            and node.id not in ("i", "j", "k")
        ):
            title, msg, suggestion = _finding_msg(self.lang, "short_variable_name", name=node.id)
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.STYLE,
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
    """Run style checks on a single Python file.

    Args:
        file_path: Path to the .py file.
        _config: Unused, kept for API consistency.
        lang: Output language for messages.

    Returns:
        List of style findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _StyleVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)

    # Check file line count
    lines = source.splitlines()
    if len(lines) > 1000:
        title, msg, suggestion = _finding_msg(lang, "overly_long_file", lines=len(lines))
        visitor.findings.append(
            Finding(
                file=file_path,
                line=1,
                severity=Severity.MAJOR,
                category=FindingCategory.STYLE,
                title=title,
                message=msg,
                suggestion=suggestion,
            )
        )

    return visitor.findings

