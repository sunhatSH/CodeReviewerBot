"""Python reporter - orchestrates all Python analysis and produces a report."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from crb.config.settings import AppConfig, PythonAnalyzerConfig
from crb.report.models import Finding, FindingCategory, OutputLang, ReviewReport, Severity, _finding_msg

from . import bloat_detector, bug_detector, comment_detector, complexity, dead_code_detector, dependency_detector, design_detector, edge_case_detector, orphan_detector, retry_detector, style_checker, test_theater_detector, third_party_suggester, auth_detector, layered_test_detector


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

    # Summarize target: show directory or count instead of all file paths
    if len(file_paths) > 5:
        common = os.path.commonpath([str(p) for p in file_paths])
        target = f"{len(file_paths)} Python files in {common}"
    else:
        target = ", ".join(str(p) for p in file_paths)
    report = ReviewReport(
        target=target,
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

    # 2. Code bloat detection (AI growth patterns)
    for fpath in all_files:
        for finding in bloat_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 3. Bug detection
    for fpath in all_files:
        for finding in bug_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 4. Edge case detection
    for fpath in all_files:
        for finding in edge_case_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 5. Design/extensibility review
    for fpath in all_files:
        for finding in design_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 6. Dead code / stale documentation detection
    for fpath in all_files:
        for finding in dead_code_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 7. Documentation/comment redundancy detection
    for fpath in all_files:
        for finding in comment_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 8. Retry detection
    for fpath in all_files:
        for finding in retry_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 9. Code style (always last in report for findings)
    if py_config.style_enabled:
        for fpath in all_files:
            for finding in style_checker.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
                report.add_finding(finding)

    # 10. Third-party library suggestions (lightweight hints)
    for fpath in all_files:
        for finding in third_party_suggester.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 11. Orphan code detection (cross-file analysis)
    if py_config.orphan_enabled:
        for finding in orphan_detector.analyze_files(all_files, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 12. Dependency conflict detection (cross-file analysis)
    for finding in dependency_detector.analyze_files(all_files, lang=OutputLang(output_lang)):
        report.add_finding(finding)

    # 13. Test theater detection (test files only)
    test_files = [f for f in all_files if "test_" in Path(f).stem or "/test_" in f]
    if test_files:
        for fpath in test_files:
            for finding in test_theater_detector.analyze_file(fpath, py_config, lang=OutputLang(output_lang)):
                report.add_finding(finding)

    # 14. Auth missing detection
    for fpath in all_files:
        for finding in auth_detector.analyze_file(fpath, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    # 15. Layered test coverage (cross-file analysis)
    if test_files:
        for finding in layered_test_detector.analyze_files(all_files, lang=OutputLang(output_lang)):
            report.add_finding(finding)

    return report
