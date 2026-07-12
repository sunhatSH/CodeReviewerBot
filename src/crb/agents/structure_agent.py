"""Structure Document Agent — LLM-powered enhancement of project structure docs.

Reads the programmatically generated structure docs and uses LLM to add
function descriptions per requirements section 2.7 (node name, path, function).
"""

from __future__ import annotations

import os
from pathlib import Path

from crb.agents import BaseAgent

_REQUIREMENTS_EXCERPT = """\
## 2.7 项目结构文档规范

**2.7.1 结构图（Mermaid 图）**
- 使用 Mermaid 绘制项目结构图，每个节点对应一个功能模块/文件/类/函数
- 通过 Mermaid 的 `click` 语法为每个节点添加可点击链接，指向对应的源代码文件、函数定义或子目录结构文档
- 同一层级的结构图只出现一次，禁止同一结构在不同文档中重复绘制

**2.7.2 结构详表（文件树）**
- 在每个结构图下方，附文件树形式的节点明细，包含：
  - 节点名称
  - 路径
  - 功能说明
- 精确到该结构图所覆盖的层级粒度

**2.7.4 分层组织**
- 根目录放置总结构图，描述顶层模块划分
- 每个子模块在其目录下放置自身的结构文档（Mermaid 图 + 文件树）
- 上层节点链接到下层结构文档，下层结构文档回指上层父节点，形成可导航的树状体系
"""

_SYSTEM_PROMPT = """\
你是一个代码审查项目结构文档专家。你的任务是增强"项目结构文档"使其符合规范的2.7节要求。

当前文档结构是程序自动生成的，缺少功能说明。你需要：
1. 分析项目的文件树和目录结构
2. 为每个节点（文件/目录）补充简洁的功能说明
3. 确保导航链接正确
4. 保持 Mermaid 图和文件树不变

输出格式：返回完整的增强后的文档内容，只增加功能说明，不改变已有结构。\
"""


class StructureDocAgent(BaseAgent):
    """Enhances project structure docs with LLM-generated function descriptions."""

    def enhance_all(self, project_root: str, requirement_doc: str | None = None) -> list[str]:
        """Find all structure.md files under project_root and enhance them.

        Args:
            project_root: Root directory of the project.
            requirement_doc: Optional path to the requirements document.

        Returns:
            List of enhanced file paths.
        """
        if not self.is_llm_available():
            return []

        root = Path(project_root).resolve()
        structure_files = sorted(root.rglob("structure.md"))

        # Read requirements for context
        req_text = _REQUIREMENTS_EXCERPT
        if requirement_doc:
            req_path = Path(requirement_doc)
            if req_path.exists():
                req_text = req_path.read_text(encoding="utf-8")

        enhanced: list[str] = []
        for sf in structure_files:
            try:
                result = self._enhance_one(sf, root, req_text)
                if result:
                    sf.write_text(result, encoding="utf-8")
                    enhanced.append(str(sf))
            except Exception as e:
                print(f"  [WARN] Failed to enhance {sf}: {e}")

        return enhanced

    def _enhance_one(self, doc_path: Path, root: Path, req_text: str) -> str | None:
        """Enhance a single structure.md document."""
        content = doc_path.read_text(encoding="utf-8")
        rel = doc_path.relative_to(root).as_posix()

        # Only enhance if it has a file tree section (programmatically generated)
        if "## File Tree" not in content:
            return None

        user_prompt = f"""\
项目根目录: {root}
当前文档路径: {rel}

## 需求规范
{req_text}

## 当前文档内容
```markdown
{content}
```

请增强此结构文档：
1. 在文件树节点后补充功能说明（格式：`节点名称 | 路径 | 功能说明`）
2. 确保导航链接正确
3. 不要删除或修改 Mermaid 图和文件树结构
4. 输出完整的增强后文档

以中文输出。\
"""

        response = self.ask(_SYSTEM_PROMPT, user_prompt, temperature=0.3)
        return response.strip()
