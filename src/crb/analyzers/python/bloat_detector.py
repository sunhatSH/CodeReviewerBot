"""AI code bloat / function growth trend detector for Python.

Detects patterns common in AI-generated or excessively verbose code:
1. Functions with too many parameters (suggesting generated boilerplate)
2. Functions with excessive nesting depth (suggesting uncontrolled growth)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Thresholds
_MAX_PARAMS = 6
_MAX_NESTING = 5

# Node types that count toward nesting depth
_NESTING_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With)


class _BloatVisitor(ast.NodeVisitor):
    """AST visitor to detect code bloat patterns."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []
        self._current_func: str = ""
        self._depth = 0
        self._max_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev_func = self._current_func
        self._current_func = node.name

        # Check parameter count
        total_params = len(node.args.args) + len(node.args.kwonlyargs)
        if total_params > _MAX_PARAMS:
            title, msg, suggestion = _finding_msg(
                self.lang, "too_many_params",
                name=node.name, count=total_params, threshold=_MAX_PARAMS,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.COMPLEXITY,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        # Check nesting depth
        self._depth = 0
        self._max_depth = 0
        self.generic_visit(node)

        if self._max_depth > _MAX_NESTING:
            title, msg, suggestion = _finding_msg(
                self.lang, "excessive_nesting",
                name=node.name, depth=self._max_depth, threshold=_MAX_NESTING,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.COMPLEXITY,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        self._current_func = prev_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def _visit_nesting_node(self, node: ast.AST) -> None:
        if not self._current_func:
            self.generic_visit(node)
            return
        self._depth += 1
        self._max_depth = max(self._max_depth, self._depth)
        self.generic_visit(node)
        self._depth -= 1

    def visit_If(self, node: ast.If) -> None:
        self._visit_nesting_node(node)

    def visit_For(self, node: ast.For) -> None:
        self._visit_nesting_node(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_nesting_node(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_nesting_node(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_nesting_node(node)


def analyze_file(
    file_path: str,
    _config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for code bloat patterns.

    Args:
        file_path: Path to the .py file.
        _config: Unused, kept for API consistency.
        lang: Output language for messages.

    Returns:
        List of findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _BloatVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)
    return visitor.findings
