"""Commit Organizer Agent — analyzes and reorganizes git commit history.

Analyzes git commit history for:
- Commit reasonableness and cleanliness
- Functional reorganization (not chronological)
- Meaningless commit messages (fix, update, wip)
- Enforcing branch protection rules

Requirements: 2.1 Git 记录管理, 2.5.3 提交记录整理智能体
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from crb.agents import BaseAgent
from crb.report.models import Finding, FindingCategory, OutputLang, Severity

_COMMIT_REVIEW_SYSTEM_PROMPT = """\
你是一个 Git 提交记录审查专家。分析 Git 提交历史并提出改进建议。

审查维度：
1. 提交信息质量 — 是否有无意义的信息（如 "fix"、"update"、"wip"）
2. 提交粒度 — 提交是否过大（大杂烩）或过小（细碎中间态）
3. 功能组织 — 相关变更是否应归并为功能完整的提交
4. 分支规范 — 是否在 main/master 上直接开发
5. 提交信息简洁性 — 拒绝冗余描述

对每个问题输出 JSON 格式：
[
  {
    "hash": "abc1234",
    "type": "message_quality|commit_size|functional_organization|branch_violation",
    "severity": "major|critical|blocker",
    "title": "简短标题",
    "message": "详细问题描述",
    "suggestion": "建议方案 (包括具体的 git rebase/squash 指令)"
  }
]

如果完全合规输出 []。只输出 JSON。\
"""


class CommitOrganizerAgent(BaseAgent):
    """Analyzes and suggests reorganization of git commit history."""

    def __init__(self, config=None):
        super().__init__(config)
        self._git_available = self._check_git()

    def _check_git(self) -> bool:
        """Check if git is available."""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True, timeout=5,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _run_git(
        self, args: list[str], cwd: str | None = None,
    ) -> subprocess.CompletedProcess | None:
        """Run a git command safely."""
        if not self._git_available:
            return None
        try:
            return subprocess.run(
                ["git"] + args,
                capture_output=True, text=True, timeout=30,
                cwd=cwd,
            )
        except subprocess.SubprocessError:
            return None

    def review_repo(
        self,
        repo_path: str,
        max_commits: int = 30,
        lang: OutputLang = OutputLang.EN,
    ) -> list[Finding]:
        """Review git commit history for a repository.

        Args:
            repo_path: Path to the git repository.
            max_commits: Maximum number of commits to analyze.
            lang: Output language.

        Returns:
            List of findings about commit quality.
        """
        if not self._git_available:
            return []

        # 1. Get recent commit log
        result = self._run_git(
            ["log", f"-{max_commits}", "--format=%H|%an|%ai|%s"],
            cwd=repo_path,
        )
        if not result or result.returncode != 0:
            return []

        commits = self._parse_log(result.stdout.strip())

        # 2. Get current branch
        branch_result = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
        )
        current_branch = branch_result.stdout.strip() if branch_result else "unknown"

        findings: list[Finding] = []

        # 3. Run static analysis on commits
        findings.extend(self._check_branch_protection(current_branch))
        findings.extend(self._check_commit_messages(commits))
        findings.extend(self._check_commit_size(commits, repo_path))

        # 4. Run LLM analysis if available
        if self.is_llm_available() and commits:
            llm_findings = self._llm_review(commits, repo_path, lang)
            findings.extend(llm_findings)

        return findings

    def _parse_log(self, log_output: str) -> list[dict[str, str]]:
        """Parse git log output into structured commit data."""
        commits: list[dict[str, str]] = []
        for line in log_output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0][:8],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })
        return commits

    def _check_branch_protection(
        self, branch: str,
    ) -> list[Finding]:
        """Check if on a protected branch."""
        if branch in ("main", "master"):
            return [
                Finding(
                    file="git",
                    line=0,
                    severity=Severity.CRITICAL,
                    category=FindingCategory.DESIGN,
                    title="禁止在受保护分支上开发",
                    message=f"当前在 {branch} 分支上。禁止在 main/master 分支上直接开发、提交、推送。",
                    suggestion="创建一个功能分支进行开发：git checkout -b feature/your-feature-name",
                )
            ]
        return []

    def _check_commit_messages(
        self, commits: list[dict[str, str]],
    ) -> list[Finding]:
        """Check for meaningless commit messages."""
        meaningless_patterns = [
            r"^(fix|update|wip|temp|tmp|cleanup|minor|tweak|oops|test|debug|work|commit)$",
            r"^\.$",
            r"^\s*$",
            r"^[0-9a-f]{7,}$",
        ]
        patterns = [re.compile(p, re.IGNORECASE) for p in meaningless_patterns]

        findings: list[Finding] = []
        for c in commits:
            msg = c["message"].strip()
            for pattern in patterns:
                if pattern.match(msg):
                    findings.append(
                        Finding(
                            file="git",
                            line=0,
                            severity=Severity.MAJOR,
                            category=FindingCategory.STYLE,
                            title="无意义的提交信息",
                            message=f"提交 {c['hash']} 的信息 \"{msg}\" 缺乏描述性。",
                            suggestion='使用有意义的提交信息，如 "feat: add user authentication" 或 "fix: handle null pointer in login"',
                        )
                    )
                    break

            # Check for overly verbose messages
            if len(msg) > 100:
                findings.append(
                    Finding(
                        file="git",
                        line=0,
                        severity=Severity.MAJOR,
                        category=FindingCategory.STYLE,
                        title="提交信息过于冗长",
                        message=f"提交 {c['hash']} 的信息过长 ({len(msg)} 字符)。提交信息应简洁。",
                        suggestion="将详细信息放在提交正文中，第一行保持在 72 字符以内。",
                    )
                )

        return findings

    def _check_commit_size(
        self, commits: list[dict[str, str]], repo_path: str,
    ) -> list[Finding]:
        """Check commit sizes — large commits may be 'kitchen sink' commits."""
        findings: list[Finding] = []

        for c in commits[:10]:  # Check first 10
            result = self._run_git(
                ["diff", "--stat", f"{c['hash']}~1", c["hash"]],
                cwd=repo_path,
            )
            if not result or result.returncode != 0:
                continue

            # Count changed files
            stats = result.stdout.strip()
            if not stats:
                continue

            # Try to get file count from diff stat
            file_count = len([l for l in stats.split("\n") if l.strip() and "changed" not in l])
            # The last line is the summary "X files changed, Y insertions(+)..."
            summary_match = re.search(r"(\d+) files? changed", stats)
            if summary_match:
                file_count = int(summary_match.group(1))

            if file_count > 15:
                findings.append(
                    Finding(
                        file="git",
                        line=0,
                        severity=Severity.MAJOR,
                        category=FindingCategory.DESIGN,
                        title="提交过大 — 大杂烩提交",
                        message=f"提交 {c['hash']} ({c['message'][:50]}) 修改了 {file_count} 个文件。",
                        suggestion="考虑拆分为多个功能性提交。使用 git rebase -i 进行拆分。",
                    )
                )

        return findings

    def _llm_review(
        self,
        commits: list[dict[str, str]],
        repo_path: str,
        lang: OutputLang,
    ) -> list[Finding]:
        """Use LLM to perform deep commit history analysis."""
        if not self.is_llm_available():
            return []

        # Get detailed commit info for LLM review
        commit_lines = []
        for c in commits:
            commit_lines.append(
                f"{c['hash']} | {c['date']} | {c['author']} | {c['message']}"
            )
        commit_text = "\n".join(commit_lines)

        user_prompt = f"""\
仓库路径: {repo_path}

## 最近的提交历史
{commit_text}

分析此提交历史的质量，包括：
1. 提交信息质量和意义
2. 提交粒度和功能组织
3. 是否适合用于 code review（PR 角度）
4. 提交历史重整建议

输出问题列表（JSON 格式）。"""

        try:
            response = self.ask(_COMMIT_REVIEW_SYSTEM_PROMPT, user_prompt, temperature=0.3)
        except Exception:
            return []

        return self._parse_findings(response)

    def _parse_findings(self, response: str) -> list[Finding]:
        """Parse LLM JSON response into Finding objects."""
        import json
        import re

        json_match = re.search(r"\[.*?\]", response, re.DOTALL)
        if not json_match:
            return []

        try:
            items = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            return []

        severity_map = {
            "blocker": Severity.BLOCKER,
            "critical": Severity.CRITICAL,
            "major": Severity.MAJOR,
        }

        findings: list[Finding] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            findings.append(
                Finding(
                    file="git",
                    line=0,
                    severity=severity_map.get(
                        (item.get("severity") or "").lower(), Severity.MAJOR
                    ),
                    category=FindingCategory.STYLE,
                    title=item.get("title", "Commit quality issue"),
                    message=item.get("message", ""),
                    suggestion=item.get("suggestion", ""),
                )
            )
        return findings

    def generate_reorganization_plan(
        self,
        repo_path: str,
        max_commits: int = 20,
    ) -> dict[str, Any] | None:
        """Generate a plan for reorganizing recent commits.

        Returns a structured plan with instructions for rebase/squash/reorder.
        """
        if not self._git_available:
            return None

        result = self._run_git(
            ["log", f"-{max_commits}", "--oneline"],
            cwd=repo_path,
        )
        if not result or result.returncode != 0:
            return None

        log_text = result.stdout.strip()

        user_prompt = f"""\
仓库路径: {repo_path}

## 最近的提交历史（单行模式）
{log_text}

请分析此提交历史，并制定一个重整方案。

输出 JSON 格式：
{{
  "needs_reorganization": true/false,
  "summary": "重整方案概述",
  "operations": [
    {{
      "type": "squash|reword|reorder|split",
      "commits": ["hash1", "hash2"],
      "reason": "操作原因",
      "new_message": "合并后的新提交信息（如果是 squash）",
      "git_commands": ["git rebase -i HEAD~N", ...]
    }}
  ],
  "requires_user_confirmation": true
}}"""

        if self.is_llm_available():
            try:
                response = self.ask(
                    "你是一个 Git 历史重整专家。分析提交历史并生成重整方案。只输出 JSON。",
                    user_prompt,
                    temperature=0.2,
                )
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    import json
                    return json.loads(json_match.group())
            except Exception:
                pass

        return None


def review_repo(
    repo_path: str,
    max_commits: int = 30,
    config=None,
    lang: str = "ch",
) -> list[Finding]:
    """Entry point for commit history review."""
    from crb.config.settings import AppConfig
    cfg = config or AppConfig()
    agent = CommitOrganizerAgent(cfg)
    return agent.review_repo(
        repo_path, max_commits=max_commits,
        lang=OutputLang(lang),
    )
