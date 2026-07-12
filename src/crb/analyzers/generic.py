"""Generic line-based code analyzer for non-Python languages.

Uses regex patterns to estimate complexity and detect issues.
Scales: 1 base + 1 per keyword match (if, for, while, else if, case, catch, &&, ||).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Complexity keywords per language family
_COMPLEXITY_PATTERNS = {
    "c_family": re.compile(
        r"\b(if|else if|for|while|case |catch |\?\s*|&&|\|\|)\s*", re.MULTILINE
    ),
    "go": re.compile(
        r"\b(if|for|switch|select|case |catch |&&|\|\|)\s*", re.MULTILINE
    ),
    "rust": re.compile(
        r"\b(if|for|while|loop|match |catch |&&|\|\|)\s*", re.MULTILINE
    ),
}

# Comment patterns per language
_COMMENT_PATTERNS = {
    "c_family": re.compile(r"//|/\*|\*|#"),
    "go": re.compile(r"//|/\*|\*"),
    "rust": re.compile(r"//|/\*|\*"),
}


def _count_lines_in_function(
    lines: list[str], start: int, lang_key: str
) -> int:
    """Count lines from start until a function boundary or end."""
    count = 0
    brace_depth = 0
    in_function = False
    comment_re = _COMMENT_PATTERNS.get(lang_key, re.compile(r"//"))

    for i in range(start, len(lines)):
        line = lines[i]
        stripped = line.strip()

        # Skip blank/comment-only lines
        if not stripped or comment_re.match(stripped):
            continue

        # Track braces
        brace_depth += stripped.count("{") - stripped.count("}")
        if not in_function:
            if "{" in stripped:
                in_function = True
                brace_depth = 1
            continue

        count += 1
        if brace_depth <= 0:
            break

    return count


def _estimate_function_lines(
    lines: list[str], lang_key: str
) -> list[tuple[int, str, int]]:
    """Find likely function definitions and estimate their line count.

    Returns list of (lineno, name, line_count).
    """
    functions: list[tuple[int, str, int]] = []
    comment_re = _COMMENT_PATTERNS.get(lang_key, re.compile(r"//"))

    func_patterns = {
        "c_family": re.compile(
            r"^\s*(?:static\s+|inline\s+|virtual\s+)?"
            r"(?:int|void|char|float|double|long|short|unsigned|signed|"
            r"size_t|bool|string|auto|const|volatile|struct|class|"
            r"\w+_t|FILE|char\*|void\*)\s*"
            r"(\w+)\s*\(.*\)\s*(?:const\s*)?(?:override\s*)?(?:final\s*)?(?:\{|;)",
            re.MULTILINE,
        ),
        "go": re.compile(
            r"^\s*(?:func\s+)(?:\([^)]*\)\s+)?(\w+)\s*\([^)]*\)",
            re.MULTILINE,
        ),
        "rust": re.compile(
            r"^\s*(?:pub\s+)?(?:fn\s+)(\w+)\s*[\(<]",
            re.MULTILINE,
        ),
    }

    pattern = func_patterns.get(lang_key)
    if not pattern:
        return functions

    for match in pattern.finditer("\n".join(lines)):
        lineno = 1 + "\n".join(lines[: match.start()]).count("\n")
        # Handle multi-line definitions by searching forward for {
        func_start = match.start()
        brace_pos = -1
        for j in range(func_start, len("\n".join(lines))):
            if "\n".join(lines)[j] == "{":
                brace_pos = j
                break

        if brace_pos >= 0:
            brace_lineno = 1 + "\n".join(lines[:brace_pos]).count("\n")
            func_lines = _count_lines_in_function(
                lines, brace_lineno, lang_key
            )
        else:
            func_lines = 1

        functions.append((lineno, match.group(1), max(func_lines, 1)))

    return functions


def analyze_file(
    file_path: str,
    lang_key: str,
    complexity_threshold: int = 10,
    func_lines_threshold: int = 50,
    ignore_patterns: Optional[list[str]] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single source file for basic code quality issues.

    Args:
        file_path: Path to source file.
        lang_key: Language key ("c_family", "go", "rust").
        complexity_threshold: Max cyclomatic complexity before warning.
        func_lines_threshold: Max function lines before warning.
        ignore_patterns: Regex patterns for function names to skip.
        lang: Output language for messages.

    Returns:
        List of findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    findings: list[Finding] = []
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()

    if not lines:
        return findings

    # Check file length
    if len(lines) > 1000:
        title, msg, suggestion = _finding_msg(lang, "overly_long_file", lines=len(lines))
        findings.append(
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

    # Estimate function complexity
    complexity_pattern = _COMPLEXITY_PATTERNS.get(lang_key)
    functions = _estimate_function_lines(lines, lang_key)
    ignore_re = (
        re.compile("|".join(ignore_patterns)) if ignore_patterns else None
    )

    for lineno, name, func_lines in functions:
        if ignore_re and ignore_re.search(name):
            continue

        # Estimate complexity: count decision keywords in the function
        func_text = "\n".join(lines[lineno - 1 : lineno + func_lines])
        if complexity_pattern:
            matches = complexity_pattern.findall(func_text)
            cc = 1 + len(matches)
        else:
            cc = 1

        if cc > complexity_threshold:
            title, msg, suggestion = _finding_msg(
                lang, "high_complexity_estimated",
                name=name, cc=cc, threshold=complexity_threshold,
            )
            findings.append(
                Finding(
                    file=file_path,
                    line=lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.COMPLEXITY,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

        if func_lines > func_lines_threshold:
            title, msg, suggestion = _finding_msg(
                lang, "overly_long_function_estimated",
                name=name, lines=func_lines, threshold=func_lines_threshold,
            )
            findings.append(
                Finding(
                    file=file_path,
                    line=lineno,
                    severity=Severity.MAJOR,
                    category=FindingCategory.COMPLEXITY,
                    title=title,
                    message=msg,
                    suggestion=suggestion,
                )
            )

    return findings
