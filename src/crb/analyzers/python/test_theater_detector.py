"""Test theater / AI echo chamber detector for Python test files.

Detects test anti-patterns:
1. Test functions with zero assertions (test theater — no actual validation)
2. Assertions that always pass (assert True, assert 1, assert None)
3. Tests with excessive mocking relative to assertion count
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Mock decorators/functions commonly used for mocking
_MOCK_NAMES = {"mock", "patch", "MagicMock", "Mock", "PropertyMock", "AsyncMock"}


def _is_test_function(name: str) -> bool:
    return name.startswith("test_") or name.startswith("test")


def _count_assertions(body: list[ast.stmt]) -> int:
    """Count assert statements in a list of AST statements."""
    count = 0
    for stmt in ast.walk(body[0]) if body else []:
        pass
    # Walk properly
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Assert):
            count += 1
        elif isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute):
                    if call.func.attr.startswith("assert"):
                        count += 1
    return count


def _count_mock_calls(body: list[ast.stmt]) -> int:
    """Count mock usages in a list of AST statements."""
    count = 0
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        # @patch decorators
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                    if dec.func.id == "patch":
                        count += 1
                elif isinstance(dec, ast.Name) and dec.id in _MOCK_NAMES:
                    count += 1
                elif isinstance(dec, ast.Attribute) and dec.attr == "patch":
                    count += 1
        # MagicMock / Mock / create_autospec calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _MOCK_NAMES:
                count += 1
            elif isinstance(node.func, ast.Attribute) and node.func.attr in ("create_autospec", "patch"):
                count += 1
    return count


def _has_always_true_assertion(body: list[ast.stmt]) -> bool:
    """Check if any assertion always passes (assert True, assert 1, etc.)."""
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Assert):
            if isinstance(node.test, ast.Constant) and node.test.value:
                return True
    return False


class _TestVisitor(ast.NodeVisitor):
    """AST visitor to detect test anti-patterns."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not _is_test_function(node.name):
            return

        assertions = _count_assertions(node.body)
        mock_calls = _count_mock_calls(node.body)

        # No assertions at all
        if assertions == 0:
            title, msg, suggestion = _finding_msg(
                self.lang, "test_no_assert",
                name=node.name,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.TEST,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        # Excessive mocking vs assertions
        if assertions > 0 and mock_calls > assertions * 3:
            title, msg, suggestion = _finding_msg(
                self.lang, "test_excessive_mock",
                name=node.name, mocks=mock_calls, asserts=assertions,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.TEST,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        # Always-true assertions
        if _has_always_true_assertion(node.body):
            title, msg, suggestion = _finding_msg(
                self.lang, "test_always_true",
                name=node.name,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.TEST,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)


def analyze_file(
    file_path: str,
    _config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single test file for test theater patterns.

    Args:
        file_path: Path to the .py file.
        _config: Unused, kept for API consistency.
        lang: Output language for messages.

    Returns:
        List of test findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    # Only analyze test files
    if not _is_test_function(path.stem) and "test" not in str(path):
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _TestVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)
    return visitor.findings
