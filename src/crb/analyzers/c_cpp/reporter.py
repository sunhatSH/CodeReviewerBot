"""C/C++ code review reporter.

Uses the generic line-based analyzer for initial estimates.
Full AST analysis requires tree-sitter-c or a native tool.
"""

from __future__ import annotations

from typing import Optional

from crb.config.settings import AppConfig
from crb.report.models import Finding, FindingCategory, OutputLang, ReviewReport, Severity

from ..generic import analyze_file


def analyze_files(
    file_paths: list[str],
    config: Optional[AppConfig] = None,
    sort_order: Optional[list[Severity]] = None,
    output_lang: str = "ch",
) -> ReviewReport:
    """Analyze C/C++ source files for code quality issues."""
    report = ReviewReport(
        target=", ".join(str(p) for p in file_paths),
        lang=OutputLang(output_lang),
    )
    if sort_order:
        report.set_sort_order(sort_order)

    for fpath in file_paths:
        findings = analyze_file(
            file_path=fpath,
            lang_key="c_family",
            complexity_threshold=10,
            func_lines_threshold=50,
            lang=OutputLang(output_lang),
        )
        for finding in findings:
            report.add_finding(finding)

    if not report.findings:
        report.add_finding(
            Finding(
                file=file_paths[0] if file_paths else "",
                line=0,
                severity=Severity.MAJOR,
                category=FindingCategory.COMPLEXITY,
                title="Basic Analysis Only",
                message=(
                    "C/C++ analysis is line-based estimation. "
                    "For accurate results, install tree-sitter or use clang-tidy."
                ),
                suggestion="Consider running clang-tidy separately for deep analysis.",
            )
        )

    return report
