"""Multi-agent architecture for code review.

Provides:
1. ReviewAgent — Wraps the existing analyzer pipeline
2. FixAgent — Generates concrete fix suggestions for each finding
3. OrganizerAgent — Categorizes, prioritizes, and generates executive summary

All agents produce structured output that feeds into the final ReviewReport.
"""

from __future__ import annotations

from typing import Optional

from crb.config.settings import AppConfig, PythonAnalyzerConfig
from crb.report.models import (
    Finding,
    FindingCategory,
    OutputLang,
    ReviewReport,
    Severity,
)

from . import bloat_detector, bug_detector, comment_detector, complexity
from . import dead_code_detector, dependency_detector, design_detector
from . import edge_case_detector, orphan_detector, retry_detector
from . import style_checker, test_theater_detector, third_party_suggester


# ---------------------------------------------------------------------------
# Fix Agent — generates concrete fix suggestions for common finding types
# ---------------------------------------------------------------------------

# Fix templates: finding_key -> (fix_description, code_example)
_FIX_SUGGESTIONS: dict[str, tuple[str, Optional[str]]] = {
    "bare_except": (
        "Specify the exception type instead of using a bare `except:`.",
        "except Exception:  # instead of bare except:",
    ),
    "mutable_default_arg": (
        "Use None as the default value and create the mutable inside the function.",
        "def foo(x=None):\n    if x is None:\n        x = []",
    ),
    "is_comparison": (
        "Use `is` instead of `==` for None/True/False comparisons.",
        "if x is None:  # instead of if x == None:",
    ),
    "hardcoded_secret": (
        "Move sensitive data to environment variables.",
        'API_KEY = os.environ["API_KEY"]  # instead of hardcoding',
    ),
    "wildcard_import": (
        "Import specific names instead of using *.",
        "from os import path, getcwd  # instead of from os import *",
    ),
    "global_statement": (
        "Pass values as parameters instead of using global variables.",
        "def foo(x): ...  # pass x as parameter instead of global",
    ),
    "orphan_code": (
        "Remove dead code or add an explicit reference if dynamically invoked.",
        "# Delete unused functions/classes, or add a __all__ reference",
    ),
    "excessive_isinstance": (
        "Replace isinstance checks with polymorphic method dispatch.",
        "class Base:\n    def handle(self): ...\nclass A(Base):\n    def handle(self): ...",
    ),
    "too_many_params": (
        "Group related parameters into a data class or config object.",
        "@dataclass\nclass Config:\n    host: str\n    port: int\n\ndef connect(cfg: Config): ...",
    ),
    "excessive_nesting": (
        "Extract nested blocks into separate functions.",
        "def inner_logic():\n    ...\n\ndef outer():\n    inner_logic()",
    ),
    "test_no_assert": (
        "Add assertions to validate expected behavior.",
        "def test_foo():\n    result = foo()\n    assert result == expected",
    ),
}


class FixAgent:
    """Generates concrete fix suggestions for findings."""

    def process(self, report: ReviewReport) -> ReviewReport:
        """Add enhanced fix suggestions to all findings."""
        for finding in report.findings:
            enhancement = self._generate_fix(finding)
            if enhancement:
                existing = finding.suggestion or ""
                if enhancement not in existing:
                    finding.suggestion = (
                        f"{existing}\n\n**Fix**: {enhancement}" if existing else enhancement
                    )
        return report

    def _generate_fix(self, finding: Finding) -> Optional[str]:
        """Generate a fix suggestion for a finding based on its title."""
        # Match by key patterns in the title
        title_lower = finding.title.lower()

        for key, (desc, _code) in _FIX_SUGGESTIONS.items():
            if key.replace("_", " ") in title_lower:
                return desc

        return finding.suggestion


# ---------------------------------------------------------------------------
# Organizer Agent — categorizes findings and generates summary
# ---------------------------------------------------------------------------

_CATEGORY_PRIORITY: list[tuple[str, list[FindingCategory]]] = [
    ("Security & Bugs", [FindingCategory.SECURITY, FindingCategory.BUG]),
    ("Design & Complexity", [FindingCategory.COMPLEXITY, FindingCategory.DESIGN]),
    ("Testing Issues", [FindingCategory.TEST]),
    ("Dependencies", [FindingCategory.DEPENDENCY]),
    ("Documentation & Style", [FindingCategory.DOCUMENTATION, FindingCategory.STYLE, FindingCategory.CONSISTENCY]),
    ("Orphan Code & Retry", [FindingCategory.ORPHAN, FindingCategory.RETRY]),
    ("Other", [FindingCategory.PERFORMANCE]),
]


class OrganizerAgent:
    """Categorizes, prioritizes findings and generates executive summaries."""

    def organize(self, report: ReviewReport) -> ReviewReport:
        """Organize findings into priority groups and add summary metadata."""
        report._organized_findings = self._group_findings(report.findings)
        report._executive_summary = self._generate_summary(report)
        return report

    def _group_findings(
        self, findings: list[Finding],
    ) -> list[tuple[str, list[Finding]]]:
        """Group findings by priority category."""
        groups: list[tuple[str, list[Finding]]] = []
        seen: set[int] = set()

        for group_name, categories in _CATEGORY_PRIORITY:
            group = [
                f for f in findings
                if f.category in categories and id(f) not in seen
            ]
            if group:
                for f in group:
                    seen.add(id(f))
                groups.append((group_name, group))

        # Any remaining uncategorized findings
        remaining = [f for f in findings if id(f) not in seen]
        if remaining:
            groups.append(("Other", remaining))

        return groups

    def _generate_summary(self, report: ReviewReport) -> str:
        """Generate an executive summary of findings."""
        total = len(report.findings)
        if total == 0:
            return "No issues found."

        blocker = report.blocker_count
        critical = report.critical_count
        major = report.major_count

        # Category breakdown
        cat_counts: dict[str, int] = {}
        for f in report.findings:
            cat_counts[f.category.value] = cat_counts.get(f.category.value, 0) + 1

        cat_summary = ", ".join(
            f"{count} {cat}" for cat, count in
            sorted(cat_counts.items(), key=lambda x: -x[1])
        )

        summary = (
            f"**Executive Summary**: {total} total issues "
            f"({blocker} Blocker, {critical} Critical, {major} Major).\n\n"
            f"Breakdown: {cat_summary}."
        )

        # Highlight most critical issues
        critical_findings = [
            f for f in report.findings
            if f.severity in (Severity.BLOCKER, Severity.CRITICAL)
        ]
        if critical_findings:
            summary += "\n\n**Top Priority**:\n"
            for f in critical_findings[:5]:
                summary += f"- {f.title} in `{f.file}:{f.line}`\n"

        return summary


# ---------------------------------------------------------------------------
# Review Agent — orchestrates the full pipeline
# ---------------------------------------------------------------------------

class ReviewAgent:
    """Orchestrates the complete multi-agent code review pipeline."""

    def __init__(self):
        self.fix_agent = FixAgent()
        self.organizer_agent = OrganizerAgent()

    def analyze(
        self,
        file_paths: list[str],
        config: Optional[AppConfig] = None,
        sort_order: Optional[list[Severity]] = None,
        output_lang: str = "ch",
    ) -> ReviewReport:
        """Run the full review pipeline and return an enriched report."""
        if config is None:
            config = AppConfig()

        py_config: PythonAnalyzerConfig = config.python
        lang = OutputLang(output_lang)

        # 1. Run all analyzers
        from .reporter import analyze_files as run_analyzers
        report = run_analyzers(file_paths, config=config, sort_order=sort_order, output_lang=output_lang)

        # 2. Apply fix suggestions (Fix Agent)
        report = self.fix_agent.process(report)

        # 3. Organize findings and generate summary (Organizer Agent)
        report = self.organizer_agent.organize(report)

        return report


def analyze_files(
    file_paths: list[str],
    config: Optional[AppConfig] = None,
    sort_order: Optional[list[Severity]] = None,
    output_lang: str = "ch",
) -> ReviewReport:
    """Multi-agent entry point. Delegates to ReviewAgent.

    Args:
        file_paths: List of file or directory paths.
        config: Application configuration.
        sort_order: Severity sort order.
        output_lang: Output language.

    Returns:
        An enriched ReviewReport.
    """
    agent = ReviewAgent()
    return agent.analyze(file_paths, config=config, sort_order=sort_order, output_lang=output_lang)
