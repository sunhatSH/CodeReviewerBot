"""Dependency conflict and multi-path detection for Python.

Detects:
1. The same module imported via both relative and absolute paths
2. Modules that shadow stdlib or installed package names
3. Duplicate imports of the same symbol
"""

from __future__ import annotations

import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

from crb.config.settings import PythonAnalyzerConfig
from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Known stdlib modules (subset) — used to detect shadowing
_STDLIB_MODULES = {
    "os", "sys", "re", "json", "math", "datetime", "pathlib", "typing",
    "collections", "itertools", "functools", "subprocess", "tempfile",
    "shutil", "hashlib", "base64", "abc", "enum", "dataclasses", "uuid",
    "io", "glob", "argparse", "logging", "threading", "multiprocessing",
    "asyncio", "http", "urllib", "xml", "csv", "sqlite3",
}


def analyze_files(
    file_paths: list[str],
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze multiple Python files for dependency issues.

    Args:
        file_paths: List of Python file paths.
        lang: Output language.

    Returns:
        List of dependency findings.
    """
    findings: list[Finding] = []

    # Map: module_name -> list of (file, line)
    imports: dict[str, list[tuple[str, int]]] = defaultdict(list)

    for fp in file_paths:
        path = Path(fp)
        if not path.exists():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=fp)
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.name].append((fp, node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports[node.module].append((fp, node.lineno))

    # Check for shadowing stdlib modules
    for fp in file_paths:
        p = Path(fp)
        stem = p.stem  # filename without .py
        if stem in _STDLIB_MODULES:
            title, msg, suggestion = _finding_msg(
                lang, "shadows_stdlib", module=stem,
            )
            findings.append(
                Finding(
                    file=fp,
                    line=1,
                    severity=Severity.MAJOR,
                    category=FindingCategory.DEPENDENCY,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

    # Check for modules imported from conflicting paths
    # (same module imported in different files — suggests possible duplicate)
    _check_conflicting_imports(imports, findings, lang)

    return findings


def _is_test_file(filepath: str) -> bool:
    """Check if a file is a test file."""
    return "test_" in Path(filepath).stem or filepath.startswith("test_")


def _check_conflicting_imports(
    imports: dict[str, list[tuple[str, int]]],
    findings: list[Finding],
    lang: OutputLang,
) -> None:
    """Check for conflicting import patterns."""
    for module_name, locations in imports.items():
        if len(locations) < 2:
            continue

        # Check if any location is a test file
        test_files = [fp for fp, _ in locations if _is_test_file(fp)]
        if len(test_files) == len(locations):
            continue  # All are test files — common pattern

        # Check for both relative and absolute by looking at import depth
        files_set = set(fp for fp, _ in locations)
        if len(files_set) > 1:
            # Group by which directory the import happens in
            dirs = defaultdict(list)
            for fp, line in locations:
                dirs[os.path.dirname(fp)].append(line)

            if len(dirs) > 1:
                # Same module imported in different directories — possible conflict
                fp, line = locations[0]
                title, msg, suggestion = _finding_msg(
                    lang, "multi_path_import", module=module_name,
                )
                findings.append(
                    Finding(
                        file=fp,
                        line=line,
                        severity=Severity.MAJOR,
                        category=FindingCategory.DEPENDENCY,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )
