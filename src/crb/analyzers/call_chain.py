"""Call chain analyzer — generates main logic call chain with file links.

Collects all source files, builds a static call graph, then uses LLM
(if available) to identify and simplify the main logic call chain.
Produces a markdown report with clickable file links.

Requirements: 报告 → 主逻辑调用逻辑链
"""

from __future__ import annotations

import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

from crb.config.settings import AppConfig


def _get_source_files(project_root: str) -> list[str]:
    """Collect all source files in a project."""
    files: list[str] = []
    root = Path(project_root)
    skip_dirs = {".git", "__pycache__", "node_modules", "build", "dist",
                 ".egg-info", ".venv", "venv", "report", "archived"}
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.suffix in (".py", ".go", ".rs", ".c", ".cpp", ".h", ".hpp"):
            if not any(part.startswith(".") or part in skip_dirs for part in f.parts):
                files.append(str(f))
    return files


def _parse_file(file_path: str) -> tuple[Optional[ast.AST], str]:
    """Parse a Python file and return (tree, source)."""
    try:
        source = Path(file_path).read_text(encoding="utf-8")
        return ast.parse(source), source
    except (SyntaxError, OSError):
        return None, ""


def _get_file_functions(file_path: str) -> dict[str, int]:
    """Get all function definitions with line numbers from a Python file."""
    functions: dict[str, int] = {}
    tree, _ = _parse_file(file_path)
    if tree is None:
        return functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions[node.name] = node.lineno
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qual = f"{node.name}.{item.name}"
                    functions[qual] = item.lineno
    return functions


def _get_function_calls(tree: ast.AST, func_name: str) -> set[str]:
    """Get top-level function calls within a specific function."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != func_name:
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)
    return calls


def _build_call_context(project_root: str) -> str:
    """Build a compact text representation of the project for LLM analysis."""
    files = _get_source_files(project_root)
    lines: list[str] = []
    for fp in files:
        rel = os.path.relpath(fp, project_root)
        functions = _get_file_functions(fp)
        if not functions:
            continue
        lines.append(f"## {rel}")
        tree, _ = _parse_file(fp)
        if tree is None:
            continue
        for func_name, lineno in sorted(functions.items(), key=lambda x: x[1]):
            simple = func_name.split(".")[-1]
            calls = _get_function_calls(tree, simple)
            calls_str = f" -> calls: {', '.join(sorted(calls))}" if calls else ""
            lines.append(f"  {func_name} (L{lineno}){calls_str}")
    return "\n".join(lines)


def _llm_generate_call_chain(
    app_config: AppConfig,
    project_root: str,
    project_name: str,
) -> str:
    """Use LLM to analyze call graph and produce simplified main logic chain."""
    from crb.llm.client import chat, LLMError

    context = _build_call_context(project_root)

    file_count = len(_get_source_files(project_root))
    if not context.strip():
        return "（无可用源代码数据）"

    system_prompt = (
        "You are a software architecture analyst. Given a project's call graph, "
        "identify the MAIN LOGIC call chain(s) — the most important execution path "
        "that represents the core functionality of the project. "
        "Ignore utility functions, setup code, tests, and trivial helpers. "
        "Simplify the chain to at most 8-12 key nodes. "
        "Output ONLY a markdown description with clickable file links."
    )

    user_prompt = f"""Project: {project_name}
Total source files: {file_count}

Below is the call graph with function definitions and their direct calls:

{context[:8000]}

Tasks:
1. Identify the 1-2 main logic call chains of this project
2. For each node, give its file path and line number
3. Use markdown link format: [function_name](relative/file/path#L123)
4. Briefly explain what each node does (1 short line)
5. If there are multiple chains (e.g., CLI entry + library API), show both

Format example:
```markdown
### Main Logic: [Feature Name]

1. **`[main()](src/cli/main.py#L300)`** — CLI entry point, parses arguments
   ↓ calls
2. **`[review()](src/cli/main.py#L322)`** — Orchestrates review process
   ↓ calls
3. **`[analyze_files()](src/analyzers/reporter.py#L15)`** — Runs all analyzers
   ...
```
"""

    try:
        result = chat(app_config.llm, system_prompt, user_prompt, temperature=0.3)
    except LLMError as e:
        return f"（LLM 分析失败: {e}）"

    return result


def _static_generate_call_chain(project_root: str, project_name: str) -> str:
    """Generate a basic call graph when LLM is not available."""
    files = _get_source_files(project_root)
    lines: list[str] = []

    for fp in files:
        rel = os.path.relpath(fp, project_root)
        functions = _get_file_functions(fp)
        if not functions:
            continue
        lines.append(f"## [{rel}]({rel})")
        tree, _ = _parse_file(fp)
        if tree is None:
            continue
        for func_name, lineno in sorted(functions.items(), key=lambda x: x[1]):
            simple = func_name.split(".")[-1]
            calls = _get_function_calls(tree, simple)
            calls_str = f" → {', '.join(sorted(calls)[:5])}" if calls else ""
            suffix = " ..." if calls and len(calls) > 5 else ""
            lines.append(f"- [{func_name}]({rel}#L{lineno}){calls_str}{suffix}")

    lines.append("")
    return "\n".join(lines)


def generate_call_chain_report(
    project_root: str,
    project_name: str,
    app_config: Optional[AppConfig] = None,
    report_dir: str = "report",
) -> str:
    """Generate a main logic call chain report for the project.

    Args:
        project_root: Project root directory.
        project_name: Display name for the project.
        app_config: App configuration (for LLM access).
        report_dir: Output directory for the report.

    Returns:
        Path to the generated report file.
    """
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build static call graph first
    call_graph_text = _build_call_context(project_root)

    if not call_graph_text.strip():
        md = f"# {project_name} — 调用链\n\n（无可用源代码，无法生成调用链）\n"
    elif app_config and app_config.llm.is_valid():
        md = f"# {project_name} — 主逻辑调用链\n\n"
        md += _llm_generate_call_chain(app_config, project_root, project_name)
        static_raw = _static_generate_call_chain(project_root, project_name)
        md += "\n\n---\n\n## 详细调用图\n\n"
        md += static_raw
    else:
        md = f"# {project_name} — 调用链概览\n\n"
        md += "> 配置 LLM 可生成精简主逻辑调用链。当前为原始调用图。\n\n"
        md += _static_generate_call_chain(project_root, project_name)

    out_path = out_dir / f"{project_name}_call_chain.md"
    out_path.write_text(md, encoding="utf-8")
    return str(out_path)


def _make_file_links_clickable(md: str, project_root: str) -> str:
    """Post-process markdown to ensure file references are clickable links."""
    import re
    # Convert bare path references like `path/to/file.py` to clickable links
    def _linkify(m: re.Match) -> str:
        path = m.group(1)
        return f"[{path}]({path})"
    md = re.sub(r'`([^\s`]+\.py)`', _linkify, md)
    return md
