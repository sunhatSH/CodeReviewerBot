"""Documentation Consistency Agent — compares planning docs against code.

Checks whether project documentation matches actual code implementation,
identifying inconsistencies per requirements section on planning doc review.
"""

from __future__ import annotations

import os
from pathlib import Path

from crb.agents import BaseAgent
from crb.report.models import (
    Finding,
    FindingCategory,
    OutputLang,
    Severity,
)

_DOC_REVIEW_SYSTEM_PROMPT = """\
你是一个代码审查专家，专门对比"规划文档"与"实际代码"的一致性。

规则：
1. 仅报告已实现部分的冲突 — 文档描述的功能已经实现但代码行为不符
2. 文档未描述但代码已实现的功能（超额完成）只需标注，不视为冲突
3. 未完成但文档中规划说明的内容不视为冲突

对每个不一致输出 JSON 格式：
[
  {
    "line": 0,
    "severity": "major",
    "title": "文档与代码不一致",
    "message": "文档说 X，但代码 Y",
    "suggestion": "修复建议"
  }
]

如果完全一致输出 []。只输出 JSON。\
"""


class DocConsistencyAgent(BaseAgent):
    """Checks planning documents against code implementation."""

    def review_project(
        self,
        project_root: str,
        lang: OutputLang = OutputLang.EN,
    ) -> list[Finding]:
        """Find planning docs and compare against code."""
        if not self.is_llm_available():
            return []

        root = Path(project_root).resolve()

        # Find planning docs
        planning_docs: list[Path] = []
        for pattern in ("docs/需求文档.md", "docs/requirements.md", "docs/设计文档.md", "docs/ARCH.md", "README.md", "需求文档.md"):
            matches = list(root.glob(pattern))
            planning_docs.extend(matches)

        if not planning_docs:
            return []

        findings: list[Finding] = []
        for doc_path in planning_docs:
            try:
                docs_result = self._check_doc(doc_path, root)
                findings.extend(docs_result)
            except Exception:
                continue

        return findings

    def _check_doc(self, doc_path: Path, root: Path) -> list[Finding]:
        """Check a single planning doc against code."""
        doc_text = doc_path.read_text(encoding="utf-8")
        if len(doc_text) > 6000:
            doc_text = doc_text[:6000]

        # Collect representative source files
        source_files: list[str] = []
        for ext in ("*.py", "*.go", "*.rs", "*.cpp", "*.c", "*.h"):
            for f in sorted(root.rglob(ext)):
                if not any(p.startswith(".") for p in f.parts):
                    try:
                        rel = f.relative_to(root)
                        source_files.append(str(rel))
                    except ValueError:
                        continue
                    if len(source_files) >= 30:
                        break
            if len(source_files) >= 30:
                break

        src_summary = "\n".join(source_files[:30])
        rel_doc = doc_path.relative_to(root)

        user_prompt = f"""\
规划文档: {rel_doc}
项目根目录: {root}

文档内容:
{doc_text}

项目源码文件列表:
{src_summary}

对比文档描述的功能与实际代码是否一致，输出不一致项。"""

        try:
            response = self.ask(_DOC_REVIEW_SYSTEM_PROMPT, user_prompt, temperature=0.2)
        except Exception:
            return []

        return self._parse_findings(response, str(rel_doc))

    def _parse_findings(self, response: str, doc_path: str) -> list[Finding]:
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

        findings: list[Finding] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            findings.append(
                Finding(
                    file=doc_path,
                    line=item.get("line", 0),
                    severity=Severity.MAJOR,
                    category=FindingCategory.CONSISTENCY,
                    title=item.get("title", "Document inconsistency"),
                    message=item.get("message", ""),
                    suggestion=item.get("suggestion", ""),
                )
            )
        return findings


def review_project(
    project_root: str,
    config=None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Entry point for doc consistency review."""
    from crb.config.settings import AppConfig
    cfg = config or AppConfig()
    agent = DocConsistencyAgent(cfg)
    return agent.review_project(project_root, lang=lang)
