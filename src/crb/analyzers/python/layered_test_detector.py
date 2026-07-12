"""Layered test coverage analyzer.

Checks that each layer in a call chain (A → B → C) has its own tests,
preventing "penetration testing" where only the top-level function is tested
and lower-level functions are indirectly covered.

Requirements: 2.2 代码审查能力 — 分层测试覆盖审查
"""

from __future__ import annotations

import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

from crb.report.models import (
    Finding,
    FindingCategory,
    OutputLang,
    Severity,
    _finding_msg,
)


def _get_function_calls(tree: ast.AST, function_name: str) -> set[str]:
    """Get all function names called within a specific function body."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != function_name:
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)
    return calls


def _collect_all_functions(tree: ast.AST, filepath: str) -> dict[str, int]:
    """Collect all function definitions and their line numbers."""
    functions: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions[node.name] = node.lineno
        # Also collect class methods
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qual = f"{node.name}.{item.name}"
                    if not item.name.startswith("_"):
                        functions[qual] = item.lineno
    return functions


def _get_test_functions(tree: ast.AST) -> set[str]:
    """Get all test function names from a test file's AST."""
    test_funcs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                test_funcs.add(node.name)
    return test_funcs


def _find_imported_names(tree: ast.AST, module_name: str) -> set[str]:
    """Find names imported from a specific module (e.g., 'foo' from 'from foo import bar')."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and module_name in node.module:
                for alias in node.names:
                    names.add(alias.name)
        if isinstance(node, ast.Import):
            for alias in node.names:
                # import foo or import foo.bar
                if alias.name == module_name or alias.name.startswith(f"{module_name}."):
                    if alias.asname:
                        names.add(alias.asname)
                    else:
                        short = alias.name.split(".")[-1]
                        names.add(short)
    return names


def _map_source_to_test_files(all_files: list[str]) -> dict[str, list[str]]:
    """Map source module names to corresponding test file paths.

    test_foo.py -> tests for foo.py
    test/foo_test.py -> tests for foo.py
    """
    source_to_tests: dict[str, list[str]] = defaultdict(list)
    test_files = [f for f in all_files if "test" in Path(f).stem or "test_" in Path(f).parent.name]

    for tf in test_files:
        stem = Path(tf).stem
        # Extract source module name from test filename
        src_name = stem.replace("test_", "", 1) if stem.startswith("test_") else stem
        src_name = src_name.replace("_test", "", 1) if src_name.endswith("_test") else src_name
        for sf in all_files:
            if sf in test_files:
                continue
            sf_stem = Path(sf).stem
            if sf_stem == src_name:
                source_to_tests[sf].append(tf)

    return source_to_tests


def analyze_files(
    file_paths: list[str],
    config: Optional[object] = None,
    lang: OutputLang = OutputLang.CH,
) -> list[Finding]:
    """Analyze Python files for layered test coverage gaps.

    For each source file, traces call chains and checks whether each
    function in the chain has direct test coverage (not just indirect).

    Args:
        file_paths: All Python file paths (source + test).
        config: Analyzer configuration (unused, kept for API compatibility).
        lang: Output language.

    Returns:
        List of findings for untested functions in call chains.
    """
    findings: list[Finding] = []

    if not file_paths:
        return findings

    # Split source and test files
    test_files: list[str] = []
    source_files: list[str] = []
    for fp in file_paths:
        if not fp.endswith(".py"):
            continue
        path = Path(fp)
        if not path.exists():
            continue
        if "test" in path.stem or "test_" in path.parent.name:
            test_files.append(fp)
        else:
            source_files.append(fp)

    if not source_files or not test_files:
        return findings

    # Parse all files
    source_trees: dict[str, ast.AST] = {}
    test_trees: dict[str, ast.AST] = {}

    for fp in source_files:
        try:
            source_trees[fp] = ast.parse(Path(fp).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            pass

    for fp in test_files:
        try:
            test_trees[fp] = ast.parse(Path(fp).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            pass

    # Map source files to their test files
    source_to_tests = _map_source_to_test_files(file_paths)

    # For each source file, find functions that are called by other functions
    # but lack direct tests
    for src_fp, src_tree in source_trees.items():
        if src_fp in source_to_tests:
            src_tests = source_to_tests[src_fp]
        else:
            src_tests = []
            # Also check if test files import from this module
            src_module = Path(src_fp).stem
            for tf_fp, tf_tree in test_trees.items():
                imports = _find_imported_names(tf_tree, src_module)
                if imports:
                    src_tests.append(tf_fp)

        if not src_tests:
            continue

        # Collect all functions in the source file
        all_funcs = _collect_all_functions(src_tree, src_fp)

        if not all_funcs:
            continue

        # Collect all functions directly tested
        directly_tested: set[str] = set()
        for tf_fp in src_tests:
            tf_tree = test_trees.get(tf_fp)
            if tf_tree is None:
                continue
            test_funcs = _get_test_functions(tf_tree)
            # For each test function, check which source functions it calls
            for tf_name in test_funcs:
                called = _get_function_calls(tf_tree, tf_name)
                # Also check imports (from foo import bar -> bar is tested)
                imported = _find_imported_names(tf_tree, Path(src_fp).stem)
                directly_tested.update(called)
                directly_tested.update(imported)

        # Build call chain: for each function, which functions does it call?
        call_graph: dict[str, set[str]] = {}
        for func_name in all_funcs:
            # For qualified names (Class.method), try the simple name too
            simple_name = func_name.split(".")[-1]
            calls = _get_function_calls(src_tree, simple_name)
            call_graph[func_name] = calls

        # Find functions in call chains that lack direct tests
        # A function is in a call chain if it's called by at least one other function
        # in the same file
        callees: set[str] = set()
        callers: dict[str, set[str]] = defaultdict(set)
        for caller, callee_set in call_graph.items():
            for callee in callee_set:
                callees.add(callee)
                callers[callee].add(caller)

        # Flag functions that:
        # 1. Are called by other functions (not top-level entry points)
        # 2. Are NOT directly tested
        # 3. Are not private helpers (these are OK to be untested if called by tested functions)
        for func_name, lineno in all_funcs.items():
            simple_name = func_name.split(".")[-1]

            # Skip if directly tested
            if simple_name in directly_tested:
                continue

            # Skip if not in any call chain (isolated/entry points)
            if simple_name not in callees and func_name not in callees:
                continue

            # Skip private helpers
            if simple_name.startswith("_"):
                continue

            # Check if any caller is tested (indirect coverage exists)
            caller_names = callers.get(simple_name, set()) | callers.get(func_name, set())
            has_tested_caller = any(
                cname in directly_tested or cname.split(".")[-1] in directly_tested
                for cname in caller_names
            )

            if not has_tested_caller:
                # This function is called but none of its callers are tested either
                continue

            # This function is in a call chain but has no direct test
            caller_list = ", ".join(sorted(caller_names)[:5])
            title, msg, suggestion = _finding_msg(
                lang, "layered_test_gap",
                name=func_name,
                file=os.path.relpath(src_fp),
                callers=caller_list,
            )
            findings.append(
                Finding(
                    file=src_fp,
                    line=lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.TEST,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

    return findings
