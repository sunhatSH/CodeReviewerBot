"""Python reporter - orchestrates all Python analysis and produces a report."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from crb.config.settings import AppConfig, PythonAnalyzerConfig
from crb.report.models import Finding, FindingCategory, OutputLang, ReviewReport, Severity, _finding_msg

from . import complexity, retry_detector, style_checker, third_party_suggester


def analyze_files(
    file_paths: list[str],
    config: Optional[AppConfig] = None,
    sort_order: Optional[list[Severity]] = None,
    output_lang: str = "ch",
) -> ReviewReport:
    """Analyze one or more Python files and produce a report.

    Args:
        file_paths: List of file or directory paths.
        config: Application configuration.
        sort_order: Severity sort order for the report (default: Blocker > Critical > Major).
        output_lang: Output language: "ch", "en", "ch_en".

    Returns:
        A ReviewReport with all findings.
    """
    if config is None:
        config = AppConfig()

    py_config: PythonAnalyzerConfig = config.python

    report = ReviewReport(
        target=", ".join(str(p) for p in file_paths),
        lang=OutputLang(output_lang),
    )

    # Apply custom sort order if provided
    if sort_order:
        report.set_sort_order(sort_order)

    # Collect all file paths
    all_files: list[str] = []
    for fp in file_paths:
        p = Path(fp)
        if p.is_dir():
            for root, _dirs, files in os.walk(str(p)):
                if "/archived" in root or "/." in root:
                    continue
                for fname in sorted(files):
                    if fname.endswith(".py"):
                        all_files.append(os.path.join(root, fname))
        elif p.suffix == ".py":
            all_files.append(str(p))

    if not all_files:
        title, msg, _ = _finding_msg(OutputLang(output_lang), "no_python_files")
        report.add_finding(
            Finding(
                file="",
                line=0,
                severity=Severity.MAJOR,
                category=FindingCategory.CONSISTENCY,
                title=title,
                message=msg,
            )
        )
        return report

    # 1. Complexity analysis
    for fpath in all_files:
        for finding in complexity.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 2. Retry detection
    for fpath in all_files:
        for finding in retry_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 3. Code style (always last in report for findings)
    if py_config.style_enabled:
        for fpath in all_files:
            for finding in style_checker.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
                report.add_finding(finding)

    # 4. Third-party library suggestions (lightweight hints)
    for fpath in all_files:
        for finding in third_party_suggester.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    return report
