"""LLM-powered Fix Agent — generates fix suggestions for review findings.

Reads findings from the review report and uses LLM to produce concrete,
context-aware fix suggestions including code diffs where appropriate.

Requirements: 2.5.2 代码修复智能体
"""

from __future__ import annotations

from crb.agents import BaseAgent
from crb.report.models import Finding, OutputLang

_FIX_SYSTEM_PROMPT = """\
你是一个代码修复专家。你的任务是基于代码审查发现的问题，生成具体、可操作的修复建议。

规则：
1. 每个修复建议必须针对一个具体的发现项
2. 修复建议应包括：
   - 问题定位（文件、行号）
   - 根本原因分析
   - 具体修复方案（包含代码示例）
   - 修复后的预期效果
3. 代码示例应尽量使用 diff 格式（+/- 行标记）
4. 对于安全问题和潜在的破坏性修改，必须在建议中标注风险等级
5. 不做擅自主张的逻辑修改，只在安全范围内（格式、命名、简单重构）给出确定修复
6. 对需要人工判断的修改，生成建议代码块附在报告中

输出格式（JSON 数组）：
[
  {
    "finding_index": 0,
    "fix_type": "safe|risky|needs_review",
    "root_cause": "根本原因",
    "description": "修复方案描述",
    "code_diff": "```diff\\n- old code\\n+ new code\\n```",
    "risk": "none|low|medium|high"
  }
]

如果无法生成修复建议，输出空数组 []。只输出 JSON。\
"""


class FixAgent(BaseAgent):
    """LLM-powered agent that generates fix suggestions for review findings."""

    def process_findings(
        self,
        findings: list[Finding],
        source_files: dict[str, str],  # file_path -> source code content
        lang: OutputLang = OutputLang.EN,
    ) -> list[dict]:
        """Generate fix suggestions for a batch of findings.

        Args:
            findings: List of findings to generate fixes for.
            source_files: Mapping of file paths to their source code content.
            lang: Output language.

        Returns:
            List of fix suggestion dicts with finding_index, fix_type, etc.
        """
        if not self.is_llm_available():
            return []

        if not findings:
            return []

        # Build context: group findings by file
        file_groups: dict[str, list[tuple[int, Finding]]] = {}
        for i, f in enumerate(findings):
            file_groups.setdefault(f.file, []).append((i, f))

        all_fixes: list[dict] = []

        for file_path, file_findings in file_groups.items():
            source = source_files.get(file_path, "")
            if not source:
                continue

            # Build prompt for this file's findings
            findings_json = []
            for idx, f in file_findings:
                findings_json.append({
                    "index": idx,
                    "line": f.line,
                    "severity": f.severity.value,
                    "category": f.category.value,
                    "title": f.title,
                    "message": f.message,
                    "suggestion": f.suggestion or "",
                })

            user_prompt = f"""\
文件: {file_path}

## 源码
```python
{source[:6000]}
```

## 发现的问题
{__import__('json').dumps(findings_json, ensure_ascii=False, indent=2)}

为每个问题生成具体的修复建议。"""

            try:
                response = self.ask(_FIX_SYSTEM_PROMPT, user_prompt, temperature=0.2)
                parsed = self._parse_fixes(response)
                all_fixes.extend(parsed)
            except Exception:
                continue

        return all_fixes

    def process_single(
        self,
        finding: Finding,
        file_path: str,
        source_code: str,
        lang: OutputLang = OutputLang.EN,
    ) -> str | None:
        """Generate a fix suggestion for a single finding.

        Args:
            finding: The finding to fix.
            file_path: Path to the source file.
            source_code: Content of the source file.
            lang: Output language.

        Returns:
            A fix suggestion string, or None if unavailable.
        """
        if not self.is_llm_available():
            return None

        user_prompt = f"""\
文件: {file_path}

## 源码
```python
{source_code[:4000]}
```

## 发现的问题
- 行号: {finding.line}
- 严重程度: {finding.severity.value}
- 标题: {finding.title}
- 描述: {finding.message}

生成具体的修复建议。"""

        try:
            response = self.ask(_FIX_SYSTEM_PROMPT, user_prompt, temperature=0.2)
            fixes = self._parse_fixes(response)
            if fixes:
                fix = fixes[0]
                parts = []
                if fix.get("root_cause"):
                    parts.append(f"**根本原因**: {fix['root_cause']}")
                if fix.get("description"):
                    parts.append(f"**修复方案**: {fix['description']}")
                if fix.get("code_diff"):
                    parts.append(fix["code_diff"])
                if fix.get("risk"):
                    parts.append(f"**风险**: {fix['risk']}")
                return "\n\n".join(parts) if parts else None
            return None
        except Exception:
            return None

    def _parse_fixes(self, response: str) -> list[dict]:
        """Parse JSON fix suggestions from LLM response."""
        import json
        import re

        json_match = re.search(r"\[.*?\]", response, re.DOTALL)
        if not json_match:
            return []

        try:
            items = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            return []

        return [item for item in items if isinstance(item, dict)]


def process_findings(
    findings: list[Finding],
    source_files: dict[str, str],
    config=None,
    lang: OutputLang = OutputLang.EN,
) -> list[dict]:
    """Entry point for LLM-powered fix suggestions."""
    from crb.config.settings import AppConfig
    cfg = config or AppConfig()
    agent = FixAgent(cfg)
    return agent.process_findings(findings, source_files, lang=lang)


def process_single(
    finding: Finding,
    file_path: str,
    source_code: str,
    config=None,
    lang: OutputLang = OutputLang.EN,
) -> str | None:
    """Entry point for single-finding fix suggestion."""
    from crb.config.settings import AppConfig
    cfg = config or AppConfig()
    agent = FixAgent(cfg)
    return agent.process_single(finding, file_path, source_code, lang=lang)
