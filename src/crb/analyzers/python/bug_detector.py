"""Potential bug detector for Python code.

Detects common bug patterns via AST analysis:
1. Bare except clauses (except: without exception type)
2. Mutable default arguments (def foo(x=[]))
3. Comparison with None/True/False using == instead of is
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg


class _BugVisitor(ast.NodeVisitor):
    """AST visitor to detect potential bug patterns."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []

    # -- Bare except clauses --
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            title, msg, suggestion = _finding_msg(self.lang, "bare_except")
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

    # -- Mutable default arguments --
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for arg in node.args.defaults:
            if isinstance(arg, (ast.List, ast.Dict, ast.Set)):
                title, msg, suggestion = _finding_msg(
                    self.lang, "mutable_default_arg", name=node.name,
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
                break  # One finding per function is enough

        # Check keyword-only defaults too
        for arg in node.args.kw_defaults:
            if arg is not None and isinstance(arg, (ast.List, ast.Dict, ast.Set)):
                title, msg, suggestion = _finding_msg(
                    self.lang, "mutable_default_arg", name=node.name,
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
                break

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    # -- "is" comparison anti-patterns (== None instead of is None) --
    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                if isinstance(comparator, ast.Constant) and (comparator.value is None or comparator.value is True or comparator.value is False):
                    op_name = "==" if isinstance(op, ast.Eq) else "!="
                    const_name = repr(comparator.value)
                    title, msg, suggestion = _finding_msg(
                        self.lang, "is_comparison",
                        name=const_name, op=op_name,
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
                    break  # One per expression
        self.generic_visit(node)


def analyze_file(
    file_path: str,
    _config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for potential bugs.

    Args:
        file_path: Path to the .py file.
        _config: Unused, kept for API consistency.
        lang: Output language for messages.

    Returns:
        List of bug findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _BugVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)
    return visitor.findings
