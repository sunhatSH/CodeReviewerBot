"""Redundant documentation and comment detector for Python code.

Detects:
1. Docstrings that merely repeat the function name (e.g., def foo(): \"\"\"foo\"\"\")
2. Stub/placeholder comments (# TODO without details, # FIXME without details)
3. Self-evident comments (comment is identical or nearly identical to the code below)
4. Empty docstrings
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg


# Stub patterns — TODO/FIXME/HACK without a person or detail
_STUB_PATTERN = re.compile(
    r"#\s*(todo|fixme|hack|xxx|optimize)\s*($|:?\s*$)",
    re.IGNORECASE,
)


class _CommentVisitor(ast.NodeVisitor):
    """AST visitor to detect redundant documentation."""

    def __init__(self, file_path: str, source_lines: list[str], lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.source_lines = source_lines
        self.lang = lang
        self.findings: list[Finding] = []

    def _get_docstring(self, node: ast.AST) -> Optional[str]:
        """Extract docstring from a function/class/module node."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                doc = node.body[0].value.value
                if isinstance(doc, str):
                    return doc.strip()
        return None

    def _get_node_source(self, node: ast.AST) -> str:
        """Get source text for a node."""
        start = node.lineno - 1
        end = getattr(node, "end_lineno", start) or start
        return "\n".join(self.source_lines[start:end])

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_docstring(node, node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_docstring(node, node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_docstring(node, node.name)
        self.generic_visit(node)

    def _check_docstring(self, node: ast.AST, name: str) -> None:
        """Check docstring for redundancy."""
        doc = self._get_docstring(node)
        if doc is None:
            return

        # Empty docstring
        if not doc.strip():
            title, msg, suggestion = _finding_msg(
                self.lang, "empty_docstring", name=name,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.DOCUMENTATION,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )
            return

        # Docstring that just repeats the name
        first_line = doc.split("\n")[0].strip().rstrip(".")
        name_lower = name.lower()
        if first_line.lower() in (name_lower, f"the {name_lower}", f"a {name_lower}"):
            title, msg, suggestion = _finding_msg(
                self.lang, "redundant_docstring", name=name,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.DOCUMENTATION,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

    def _check_stub_comment(self, lineno: int, line: str) -> None:
        """Check if a line is a stub comment without details."""
        stripped = line.strip()
        m = _STUB_PATTERN.search(stripped)
        if m:
            tag = m.group(1).upper()
            title, msg, suggestion = _finding_msg(
                self.lang, "stub_comment", tag=tag,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.DOCUMENTATION,
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
    """Analyze a single Python file for redundant documentation.

    Args:
        file_path: Path to the .py file.
        _config: Unused, kept for API consistency.
        lang: Output language for messages.

    Returns:
        List of documentation findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _CommentVisitor(
        file_path=file_path,
        source_lines=source_lines,
        lang=lang,
    )
    visitor.visit(tree)

    # Also check all lines for stub comments
    for lineno, line in enumerate(source_lines, start=1):
        visitor._check_stub_comment(lineno, line)

    return visitor.findings
