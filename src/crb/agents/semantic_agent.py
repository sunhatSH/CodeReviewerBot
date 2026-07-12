"""Semantic Review Agent — LLM-powered deep code analysis.

Reviews code for design patterns, SOLID principles, surface patching vs
root cause fixes, AI code bloat, extensibility, and performance issues
that static analysis alone cannot detect.
"""

from __future__ import annotations

import os
from pathlib import Path

from crb.agents import BaseAgent
from crb.report.models import (
    Finding,
    FindingCategory,
    OutputLang,
    ReviewReport,
    Severity,
)

_REVIEW_SYSTEM_PROMPT = """\
你是一个资深代码审查专家，擅长软件工程理论审查。分析以下源代码并找出：
1. AI 代码膨胀趋势 — 代码是否存在层层叠加、过度封装、不必要的抽象
2. 根本修复 vs 表面修补 — 问题是否从根源解决，还是仅靠加判空/try-catch 修补
3. SOLID 原则违反 — 单一职责、开闭原则、依赖反转等
4. 可扩展性问题 — 硬编码配置、缺乏扩展点
5. 性能问题 — 不必要的重复计算、N+1 查询等
6. 设计模式适用性 — 是否滥用设计模式，或应该用但没用的场景
7. 耦合与内聚 — 模块间过度耦合、低内聚
8. 抽象层次 — 抽象是否合理，关注点分离是否恰当

对每个问题输出：
- 行号
- 问题类型（分类）
- 严重程度（Blocker/Critical/Major）
- 问题描述
- 建议修复方案

输出格式（JSON 数组）：
[
  {
    "line": 42,
    "category": "design",
    "severity": "major",
    "title": "简短标题",
    "message": "详细问题描述",
    "suggestion": "修复建议"
  }
]

如果没有任何问题，输出空数组 []。不要输出其他内容。\
"""


class SemanticReviewAgent(BaseAgent):
    """LLM-powered deep semantic code review for a single file."""

    def review_file(self, file_path: str, lang: OutputLang = OutputLang.EN) -> list[Finding]:
        """Review a single file for semantic issues."""
        if not self.is_llm_available():
            return []

        try:
            with open(file_path) as f:
                code = f.read()
        except (OSError, UnicodeDecodeError):
            return []

        if len(code) > 8000:
            # Truncate very long files
            code = code[:4000] + "\n# ... (truncated) ...\n" + code[-3500:]

        rel_path = os.path.relpath(file_path)

        user_prompt = f"""\
文件: {rel_path}

```python
{code}
```

分析此代码，输出 JSON 格式的审查结果。"""

        try:
            response = self.ask(_REVIEW_SYSTEM_PROMPT, user_prompt, temperature=0.2)
        except Exception:
            return []

        return self._parse_findings(response, file_path, lang)

    def _parse_findings(
        self, response: str, file_path: str, lang: OutputLang,
    ) -> list[Finding]:
        """Parse LLM JSON response into Finding objects."""
        import json
        import re

        # Extract JSON array from response
        json_match = re.search(r"\[.*?\]", response, re.DOTALL)
        if not json_match:
            return []

        try:
            items = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            return []

        findings: list[Finding] = []
        category_map = {
            "design": FindingCategory.DESIGN,
            "complexity": FindingCategory.COMPLEXITY,
            "performance": FindingCategory.PERFORMANCE,
            "security": FindingCategory.SECURITY,
            "bug": FindingCategory.BUG,
            "style": FindingCategory.STYLE,
            "test": FindingCategory.TEST,
        }
        severity_map = {
            "blocker": Severity.BLOCKER,
            "critical": Severity.CRITICAL,
            "major": Severity.MAJOR,
        }

        for item in items:
            if not isinstance(item, dict):
                continue
            findings.append(
                Finding(
                    file=file_path,
                    line=item.get("line", 0),
                    severity=severity_map.get(
                        (item.get("severity") or "").lower(), Severity.MAJOR
                    ),
                    category=category_map.get(
                        (item.get("category") or "").lower(), FindingCategory.DESIGN
                    ),
                    title=item.get("title", "Code quality issue"),
                    message=item.get("message", ""),
                    suggestion=item.get("suggestion", ""),
                )
            )

        return findings


def review_file(
    file_path: str,
    config=None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Entry point for semantic review."""
    from crb.config.settings import AppConfig
    cfg = config or AppConfig()
    agent = SemanticReviewAgent(cfg)
    return agent.review_file(file_path, lang=lang)
