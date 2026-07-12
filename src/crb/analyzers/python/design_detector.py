"""Design and extensibility reviewer for Python code.

Detects patterns that violate good design principles:
1. Excessive isinstance type checks (suggesting missing polymorphism)
2. Broad try-except swallowing bare Exception/BaseException
3. Silent except handlers (except: pass)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

_MAX_INSTANCEOF_CHECKS = 3


class _DesignVisitor(ast.NodeVisitor):
    """AST visitor for design pattern analysis."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []
        self._current_func = "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_func = self._current_func
        self._current_func = node.name

        # Count isinstance checks
        isinstance_count = 0
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name) and child.func.id == "isinstance":
                    isinstance_count += 1

        if isinstance_count > _MAX_INSTANCEOF_CHECKS:
            title, msg, suggestion = _finding_msg(
                self.lang, "excessive_isinstance",
                name=node.name, count=isinstance_count,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.DESIGN,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        self.generic_visit(node)
        self._current_func = old_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # Silent except handler: except: pass or except Exception: pass
        if node.type is None:
            # Bare except covered by bug_detector, skip here
            pass
        elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
            # Check if body is just pass
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                title, msg, suggestion = _finding_msg(
                    self.lang, "silent_except",
                    name=node.type.id,
                )
                self.findings.append(
                    Finding(
                        file=self.file_path,
                        line=node.lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.BUG,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

            # Check for broad except with print-only body
            if (len(node.body) == 1 and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Call)
                    and isinstance(node.body[0].value.func, ast.Name)
                    and node.body[0].value.func.id == "print"):
                title, msg, suggestion = _finding_msg(
                    self.lang, "surface_patching",
                    name=node.type.id,
                )
                self.findings.append(
                    Finding(
                        file=self.file_path,
                        line=node.lineno,
                        severity=Severity.MAJOR,
                        category=FindingCategory.BUG,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )

        self.generic_visit(node)


def analyze_file(
    file_path: str,
    _config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for design issues.

    Args:
        file_path: Path to the .py file.
        _config: Unused, kept for API consistency.
        lang: Output language for messages.

    Returns:
        List of design findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _DesignVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)
    return visitor.findings
