"""LLM Review Agent — orchestrates all LLM-powered code review agents.

Runs after static analysis to add deep semantic findings that static
rules cannot detect, and generates fix suggestions, commit history
reviews, etc.

Requirements: 2.5.1 代码审查智能体, 2.5.2 代码修复智能体, 2.5.3 提交记录整理智能体
"""

from __future__ import annotations

import os
from pathlib import Path

from crb.agents import BaseAgent
from crb.agents.semantic_agent import SemanticReviewAgent
from crb.agents.doc_consistency_agent import DocConsistencyAgent
from crb.report.models import Finding, OutputLang, ReviewReport


class LLMReviewAgent(BaseAgent):
    """Orchestrates all LLM-powered code review agents.

    Runs:
    1. Semantic review on source files (SOLID, design, AI bloat, etc.)
    2. Doc consistency check (planning docs vs code)
    3. Fix suggestions for findings (when source available)
    4. Commit history review (if project is a git repo)
    """

    def __init__(self, config=None):
        super().__init__(config)
        self.semantic_agent = SemanticReviewAgent(self.config)
        self.doc_consistency_agent = DocConsistencyAgent(self.config)
        self.fix_agent = None  # lazily imported
        self.commit_agent = None  # lazily imported

    def _get_fix_agent(self):
        if self.fix_agent is None:
            from crb.agents.fix_agent import FixAgent
            self.fix_agent = FixAgent(self.config)
        return self.fix_agent

    def _get_commit_agent(self):
        if self.commit_agent is None:
            from crb.agents.commit_organizer_agent import CommitOrganizerAgent
            self.commit_agent = CommitOrganizerAgent(self.config)
        return self.commit_agent

    def analyze_files(
        self,
        file_paths: list[str],
        project_root: str | None = None,
        lang: OutputLang = OutputLang.EN,
        report: ReviewReport | None = None,
    ) -> list[Finding]:
        """Run all LLM-powered agents on the given files.

        Args:
            file_paths: List of source file paths to review.
            project_root: Project root directory.
            lang: Output language.
            report: Optional existing ReviewReport (for fix agent context).

        Returns:
            Combined list of findings from all agents.
        """
        all_findings: list[Finding] = []

        if not self.is_llm_available():
            return all_findings

        # 1. Semantic review on each source file
        source_files = [fp for fp in file_paths if Path(fp).suffix in (".py", ".go", ".rs", ".cpp", ".c", ".h", ".hpp")]
        n = len(source_files)
        for idx, fp in enumerate(source_files, 1):
            p = Path(fp)
            rel = os.path.relpath(fp)
            print(f"  🔍  LLM semantic [{idx}/{n}] {rel}", flush=True)
            findings = self.semantic_agent.review_file(fp, lang=lang)
            all_findings.extend(findings)

        # 2. Doc consistency check (requirements vs code)
        if project_root:
            doc_findings = self.doc_consistency_agent.review_project(
                project_root, lang=lang,
            )
            all_findings.extend(doc_findings)

        # 3. Fix suggestions for existing findings (if a report is provided)
        if report and report.findings:
            try:
                fix_agent = self._get_fix_agent()
                # Read source files mentioned in the report
                source_files: dict[str, str] = {}
                for f in report.findings:
                    fp = f.file
                    if fp and os.path.isfile(fp) and fp not in source_files:
                        try:
                            with open(fp) as fh:
                                source_files[fp] = fh.read()
                        except (OSError, UnicodeDecodeError):
                            continue

                if source_files:
                    fixes = fix_agent.process_findings(
                        report.findings, source_files, lang=lang,
                    )
                    if fixes:
                        # Attach fix suggestions to findings
                        for fix in fixes:
                            idx = fix.get("finding_index")
                            if idx is not None and 0 <= idx < len(report.findings):
                                existing = report.findings[idx].suggestion or ""
                                desc = fix.get("description", "")
                                if desc and desc not in existing:
                                    report.findings[idx].suggestion = (
                                        f"{existing}\n\n**LLM Fix**: {desc}"
                                    ).strip()
            except Exception:
                pass

        # 4. Commit history review (if project_root is a git repo)
        if project_root:
            git_dir = Path(project_root) / ".git"
            if git_dir.is_dir():
                try:
                    commit_agent = self._get_commit_agent()
                    commit_findings = commit_agent.review_repo(
                        project_root, lang=lang,
                    )
                    all_findings.extend(commit_findings)
                except Exception:
                    pass

        return all_findings


def analyze_files(
    file_paths: list[str],
    config=None,
    project_root: str | None = None,
    output_lang: str = "ch",
    report: ReviewReport | None = None,
) -> list[Finding]:
    """Entry point for LLM-powered review agents."""
    from crb.config.settings import AppConfig
    cfg = config or AppConfig()
    agent = LLMReviewAgent(cfg)
    return agent.analyze_files(
        file_paths,
        project_root=project_root,
        lang=OutputLang(output_lang),
        report=report,
    )
