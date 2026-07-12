"""Dead code and stale documentation detector for Python.

Detects:
1. Large commented-out code blocks (>3 consecutive lines that look like code)
2. Stale TODO/FIXME markers with old dates (more than 6 months old)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Regexes for detecting dates in comments
_DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})"
)

# Patterns suggesting a comment line is commented-out code (not prose)
_CODE_LINE_PATTERNS = re.compile(
    r"^\s*#\s+"
    r"(?:"
    r"import\s|from\s|def\s|class\s|return\s|if\s|elif\s|else\s|for\s|while\s|"
    r"try:|except:|finally:|with\s|raise\s|pass\s*$|break|continue|"
    r"print\(|assert\s|yield\s|del\s|global\s|nonlocal\s|"
    r"self\.|cls\.|super\(\)|"
    r"@\w+"  # decorators
    r")",
    re.IGNORECASE,
)

_COMMENTED_CODE_MIN_LINES = 4


def _check_stale_dates(source: str, file_path: str, findings: list[Finding], lang: OutputLang) -> None:
    """Check TODO/FIXME comments for stale dates."""
    now = datetime.now(timezone.utc)
    six_months_ago = now - timedelta(days=180)

    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue

        if not any(tag in stripped.upper() for tag in ("TODO", "FIXME", "HACK", "XXX")):
            continue

        m = _DATE_PATTERN.search(stripped)
        if m:
            try:
                dt = datetime(
                    int(m.group("year")),
                    int(m.group("month")),
                    int(m.group("day")),
                    tzinfo=timezone.utc,
                )
                if dt < six_months_ago:
                    title, msg, suggestion = _finding_msg(
                        lang, "stale_todo", date=m.group(),
                    )
                    findings.append(
                        Finding(
                            file=file_path,
                            line=lineno,
                            severity=Severity.MAJOR,
                            category=FindingCategory.DOCUMENTATION,
                            title=title,
                            message=msg,
                            suggestion=suggestion,
                        )
                    )
            except (ValueError, OverflowError):
                pass


def _check_commented_out_code(source: str, file_path: str, findings: list[Finding], lang: OutputLang) -> None:
    """Check for large blocks of commented-out code."""
    lines = source.splitlines()
    code_block_lines: list[int] = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if _CODE_LINE_PATTERNS.match(stripped):
            code_block_lines.append(lineno)
        else:
            # Check for consecutive runs
            if len(code_block_lines) >= _COMMENTED_CODE_MIN_LINES:
                title, msg, suggestion = _finding_msg(
                    lang, "commented_out_code",
                    lines=len(code_block_lines), start=code_block_lines[0],
                )
                findings.append(
                    Finding(
                        file=file_path,
                        line=code_block_lines[0],
                        severity=Severity.MAJOR,
                        category=FindingCategory.DOCUMENTATION,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )
            code_block_lines = []

    # Check trailing block
    if len(code_block_lines) >= _COMMENTED_CODE_MIN_LINES:
        title, msg, suggestion = _finding_msg(
            lang, "commented_out_code",
            lines=len(code_block_lines), start=code_block_lines[0],
        )
        findings.append(
            Finding(
                file=file_path,
                line=code_block_lines[0],
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
    """Analyze a single Python file for dead code and stale docs.

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

    source = path.read_text(encoding="utf-8", errors="replace")
    findings: list[Finding] = []

    _check_stale_dates(source, file_path, findings, lang)
    _check_commented_out_code(source, file_path, findings, lang)

    return findings
