"""Secret detection — finds hardcoded credentials, API keys, tokens, passwords.

Uses regex patterns to detect potential secrets hardcoded in source files.
Supports Python, C/C++, Go, and Rust.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from crb.report.models import Finding, FindingCategory, OutputLang, Severity, _finding_msg

# Regex patterns for hardcoded secrets
_SECRET_PATTERNS: list[tuple[str, str]] = [
    # API keys and tokens
    ("api_key", r"""(?i)\b(?:api[-_]key|api[-_]secret|access[-_]key|app[-_]token|bearer[-_]token|auth[-_]token|session[-_]key|refresh[-_]token)\s*[:=]\s*["'][^"']+["']"""),
    # Private keys
    ("private_key", r"(?i)(?:-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY-----)"),
    # Password assignments
    ("password", r"""(?i)\b(?:password|passwd|pwd|secret)\s*[:=]\s*["'][^"']+["']"""),
    # JWT tokens (long base64 strings)
    ("jwt_token", r"""(?i)["'](?:eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})["']"""),
    # Connection strings with credentials
    ("connection_string", r"""(?i)(?:jdbc|postgresql|mysql|mongodb|redis|amqp|rabbitmq)://[^:@\s]+:[^@\s]+@"""),
    # Slack/webhook URLs
    ("webhook_url", r"""(?i)https?://hooks\.slack\.com/services/[A-Za-z0-9_/]+"""),
    # GitHub tokens
    ("github_token", r"""(?i)(?:ghp_|gho_|ghu_|ghs_|ghr_)[a-zA-Z0-9]{36}"""),
]

# Patterns that are likely false positives (test fixtures, example code, etc.)
_FALSE_POSITIVE_PATTERNS = [
    r"example|test_|mock_|placeholder|your_|change_me",
    r"xxxxx|password_example",
    # Standalone placeholder numbers (avoid matching substrings like "12345" in "1234567890abcdef")
    r"\b12345\b|\bpassword\b.*\bplaceholder\b",
]


def _is_likely_false_positive(line: str) -> bool:
    """Check if a line is likely a test/example rather than a real secret."""
    return any(re.search(p, line, re.IGNORECASE) for p in _FALSE_POSITIVE_PATTERNS)


def analyze_file(
    file_path: str,
    lang: OutputLang = OutputLang.CH,
    ignore_patterns: Optional[list[str]] = None,
) -> list[Finding]:
    """Analyze a single file for hardcoded secrets.

    Args:
        file_path: Path to source file.
        lang: Output language.
        ignore_patterns: Optional regex patterns for lines to skip.

    Returns:
        List of findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    findings: list[Finding] = []
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()

    ignore_re = re.compile("|".join(ignore_patterns)) if ignore_patterns else None

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith(("#", "//", "/*", "*")):
            continue

        # Skip test/example patterns
        if _is_likely_false_positive(stripped):
            continue

        # Skip lines matching custom ignore patterns
        if ignore_re and ignore_re.search(stripped):
            continue

        for pattern_name, pattern in _SECRET_PATTERNS:
            if re.search(pattern, stripped):
                title, msg, suggestion = _finding_msg(
                    lang, "hardcoded_secret",
                    pattern=pattern_name,
                )
                findings.append(
                    Finding(
                        file=file_path,
                        line=lineno,
                        severity=Severity.CRITICAL,
                        category=FindingCategory.SECURITY,
                        title=title,
                        message=msg,
                        suggestion=suggestion,
                    )
                )
                break  # One finding per line is enough

    return findings
