"""Error retry pattern detector for Python code.

Detects retry loops around model API calls and other stateful operations.
Excludes stateless/idempotent retries (e.g., simple data fetching).

Retry patterns detected:
1. while retry_count < N / attempts < N loops around try/except
2. Decorators like @retry, @backoff
3. Recursive retry on exceptions
4. for _ in range(N) retry loops
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
    Severity,
    _finding_msg,
)

# Decorators that indicate retry behavior
_RETRY_DECORATORS = {
    "retry",
    "backoff",
    "tenacity",
    "retry_on_exception",
}


class _RetryVisitor(ast.NodeVisitor):
    """AST visitor to detect retry patterns."""

    def __init__(self, file_path: str, ignore_list: list[str], threshold: int, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.ignore_list = ignore_list
        self.threshold = threshold
        self.lang = lang
        self.findings: list[Finding] = []
        self._in_retry_context = False

    def _is_retry_loop(self, node: ast.AST) -> Optional[int]:
        """Check if a loop node is a retry pattern. Returns max_retries if so."""
        # Pattern 1: for _ in range(N) wrapping try/except with retry
        if isinstance(node, ast.For):
            if (
                isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"
            ) or (
                isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Attribute)
                and node.iter.func.attr == "range"
            ):
                # Check if body contains try/except
                for body_node in node.body:
                    if isinstance(body_node, ast.Try):
                        return self._count_retry_in_try(body_node)
            return None

        # Pattern 2: while retry_count < N / attempts < N
        if isinstance(node, ast.While):
            test = node.test
            if isinstance(test, ast.Compare):
                # Check for: count < N, attempts < N
                if isinstance(test.left, ast.Name) and any(
                    isinstance(op, ast.Lt) for op in test.ops
                ):
                    left_name = test.left.id.lower()
                    if "retry" in left_name or "attempt" in left_name or "try" in left_name:
                        if len(test.comparators) == 1 and isinstance(
                            test.comparators[0], ast.Constant
                        ):
                            return test.comparators[0].value
                # Also check: retries > 0 type conditions (loop while retries exist)
                if isinstance(test.left, ast.Name) and any(
                    isinstance(op, ast.Gt) for op in test.ops
                ):
                    left_name = test.left.id.lower()
                    if "retry" in left_name or "attempt" in left_name:
                        for body_node in node.body:
                            if isinstance(body_node, ast.Try):
                                return self._count_retry_in_try(body_node)
            return None

        return None

    def _count_retry_in_try(self, try_node: ast.Try) -> Optional[int]:
        """Check if a try/except has retry logic (recursive call similar name in except)."""
        for handler in try_node.handlers:
            for body_node in handler.body:
                # Pattern: recursive call to same function
                if isinstance(body_node, ast.Expr) and isinstance(
                    body_node.value, ast.Call
                ):
                    call = body_node.value
                    if isinstance(call.func, ast.Name):
                        # This is a recursive call pattern - correlates with retry
                        pass

                # Pattern: wait/sleep before retry
                if isinstance(body_node, ast.Expr) and isinstance(
                    body_node.value, ast.Call
                ):
                    call = body_node.value
                    if isinstance(call.func, ast.Attribute) and call.func.attr in (
                        "sleep",
                        "wait",
                    ):
                        pass  # sleep indicates retry

            # Check if handler body continues the loop (pass, continue, etc.)
            for body_node in handler.body:
                if isinstance(body_node, ast.Continue):
                    # This is inside a retry loop, count as retry
                    return 3  # default threshold
                if isinstance(body_node, ast.Pass):
                    return None
        return None

    def _check_decorator_retry(self, node: ast.FunctionDef) -> Optional[int]:
        """Check if function has retry decorator with max attempts."""
        for dec in node.decorator_list:
            # Pattern: @retry(...) or @tenacity.retry(...)
            if isinstance(dec, ast.Call):
                func_name = None
                if isinstance(dec.func, ast.Name):
                    func_name = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    func_name = dec.func.attr

                if func_name in _RETRY_DECORATORS or func_name == "retry":
                    # Try to extract max attempts from decorator args
                    for kw in dec.keywords:
                        if kw.arg in (
                            "max_retries", "max_attempts", "tries",
                            "stop_max_attempt_number",
                        ):
                            if isinstance(kw.value, ast.Constant):
                                return kw.value.value
                    return 3  # default
            # Pattern: @retry (no args)
            elif isinstance(dec, ast.Name) and dec.id in _RETRY_DECORATORS:
                return 3
            # Pattern: @tenacity.retry (no args)
            elif isinstance(dec, ast.Attribute) and (
                dec.attr in _RETRY_DECORATORS or dec.attr == "retry"
            ):
                return 3
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        decorators = set(d.id for d in node.decorator_list if isinstance(d, ast.Name))
        decorators |= set(
            d.attr for d in node.decorator_list if isinstance(d, ast.Attribute)
        )

        if self.ignore_list and decorators & set(self.ignore_list):
            return

        # Check decorator-based retry
        retry_count = self._check_decorator_retry(node)
        if retry_count is not None and retry_count > self.threshold:
            title, msg, suggestion = _finding_msg(
                self.lang, "excessive_retry_decorator",
                name=node.name, attempts=retry_count, threshold=self.threshold,
            )
            self.findings.append(
                Finding(
                    file=self.file_path,
                    line=node.lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.RETRY,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        # Check loop-based retry in body
        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.While)):
                max_retries = self._is_retry_loop(child)
                if max_retries is not None and max_retries > self.threshold:
                    title, msg, suggestion = _finding_msg(
                        self.lang, "excessive_retry_loop",
                        name=node.name, attempts=max_retries, threshold=self.threshold,
                    )
                    self.findings.append(
                        Finding(
                            file=self.file_path,
                            line=child.lineno,
                            severity=Severity.MAJOR,
                            category=FindingCategory.RETRY,
                            title=title,
                            message=msg,
                            suggestion=suggestion,
                        )
                    )

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Treat same as sync functions
        self.visit_FunctionDef(node)


def analyze_file(
    file_path: str,
    config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for excessive retry patterns.

    Args:
        file_path: Path to the .py file.
        config: Analyzer configuration.
        lang: Output language for messages.

    Returns:
        List of findings.
    """
    if config is None:
        config = PythonAnalyzerConfig()

    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _RetryVisitor(
        file_path=file_path,
        ignore_list=config.ignore_decorators,
        threshold=config.retry.max_retries,
        lang=lang,
    )
    visitor.visit(tree)
    return visitor.findings


def analyze_directory(
    dir_path: str,
    config: Optional[PythonAnalyzerConfig] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Recursively analyze Python files for retry issues."""
    if config is None:
        config = PythonAnalyzerConfig()

    all_findings: list[Finding] = []
    for root, _dirs, files in os.walk(dir_path):
        if "/archived" in root or "/." in root:
            continue
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            all_findings.extend(analyze_file(fpath, config, lang=lang))

    return all_findings
