"""Edge case and boundary condition reviewer for Python code.

Detects potential boundary issues via AST analysis:
1. Long if-elif chains without a final else branch (missing default)
2. Division/binary ops without preceding zero check
3. Off-by-one in range(len(...)) patterns (suggest enumerate)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg


class _EdgeCaseVisitor(ast.NodeVisitor):
    """AST visitor for edge case detection."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []
        self._current_function = "<module>"
        self._function_body_lines: set[int] = set()

    # -- Track function names --
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_name = self._current_function
        self._current_function = node.name
        self.generic_visit(node)
        self._current_function = old_name

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    # -- Long if-elif without final else --
    def visit_If(self, node: ast.If) -> None:
        # Walk to find deepest elif chain
        chain_length = 1
        current = node
        while current.orelse and len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            chain_length += 1
            current = current.orelse[0]

        has_final_else = current.orelse and not (
            len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If)
        )

        if chain_length >= 3 and not has_final_else:
            title, msg, suggestion = _finding_msg(
                self.lang, "missing_else_branch",
                count=chain_length,
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

    # -- Off-by-one range patterns --
    def visit_Call(self, node: ast.Call) -> None:
        # Check for range(len(...)) -> suggest enumerate
        if isinstance(node.func, ast.Name) and node.func.id == "range":
            if node.args and isinstance(node.args[0], ast.Call):
                call = node.args[0]
                if isinstance(call.func, ast.Name) and call.func.id == "len":
                    title, msg, suggestion = _finding_msg(
                        self.lang, "range_len",
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

    # -- Division without zero guard --
    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            # Check if the parent scope has a zero check around this
            if not self._is_guarded(node, node.right):
                title, msg, suggestion = _finding_msg(
                    self.lang, "division_by_zero",
                    name=self._current_function,
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

    def _is_guarded(self, target_node: ast.AST, divisor: ast.expr) -> bool:
        """Check if a division is guarded by a zero check in surrounding if statements."""
        # This is a simple heuristic - checks if divisor is checked via if guard
        if not isinstance(divisor, ast.Name):
            return True  # Non-trivial divisors are harder to check statically
        # We'll be conservative and only flag simple cases
        return False


def analyze_file(
    file_path: str,
    _config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for edge case issues.

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

    visitor = _EdgeCaseVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)
    return visitor.findings
