#!/usr/bin/env python3
"""CodeReviewerBot 文档生成 Agent

Reads source code, extracts module structure, and uses the configured LLM
to generate Mermaid + markdown structure documentation.

Usage:
    # Generate missing docs (only those that don't exist yet)
    python scripts/docs_gen_agent.py

    # Regenerate ALL docs (existing + missing) to a custom output directory
    python scripts/docs_gen_agent.py --all --output-dir /tmp/test_docs

    # Generate docs for specific modules only
    python scripts/docs_gen_agent.py --modules config,report,llm
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Ensure src is on the path
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC = _PROJECT_ROOT / "src"
sys.path.insert(0, str(_SRC))

from crb.config.settings import LLMConfig
from crb.llm.client import LLMError, chat


# ──────────────────────────────────────────────
# Module definitions: which source files produce which docs
# ──────────────────────────────────────────────

DocSpec = dict[str, str]  # {output_relpath: description}

DOC_SPECS: list[DocSpec] = [
    # Top-level overview
    {
        "docs/structure.md": "",
    },
    # Config module
    {
        "docs/config/structure.md": "",
    },
    # Report models
    {
        "docs/report/structure.md": "",
    },
    # LLM client
    {
        "docs/llm/structure.md": "",
    },
    # CLI module
    {
        "docs/cli/structure.md": "",
    },
    # Generic analyzer
    {
        "docs/analyzers/generic/structure.md": "",
    },
    # C/C++ analyzer
    {
        "docs/analyzers/c_cpp/structure.md": "",
    },
    # Go analyzer
    {
        "docs/analyzers/go/structure.md": "",
    },
    # Rust analyzer
    {
        "docs/analyzers/rust/structure.md": "",
    },
    # Python analyzer (most complex)
    {
        "docs/analyzers/python/structure.md": "",
    },
]

# Existing docs that serve as format examples
_EXISTING_DOCS: dict[str, str] = {}


def _load_existing_docs() -> None:
    """Load existing docs to use as format examples."""
    existing_paths = [
        "docs/structure.md",
        "docs/cli/structure.md",
        "docs/analyzers/python/structure.md",
    ]
    for rel in existing_paths:
        fp = _PROJECT_ROOT / rel
        if fp.exists():
            _EXISTING_DOCS[rel] = fp.read_text(encoding="utf-8")


# ──────────────────────────────────────────────
# Source code introspection
# ──────────────────────────────────────────────


def _extract_symbols(file_path: str) -> dict:
    """Extract classes, functions, imports from a Python source file."""
    result: dict = {
        "path": file_path,
        "classes": [],
        "functions": [],
        "imports": [],
        "lines": 0,
    }
    try:
        with open(file_path) as f:
            source = f.read()
        result["lines"] = len(source.splitlines())

        import ast as _ast
        tree = _ast.parse(source)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                ]
                result["classes"].append({"name": node.name, "methods": methods, "line": node.lineno})
            elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                result["functions"].append({"name": node.name, "line": node.lineno})
            elif isinstance(node, (_ast.Import, _ast.ImportFrom)):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        result["imports"].append(alias.name)
                else:
                    result["imports"].append(f"from {node.module} import ...")
    except (SyntaxError, OSError, UnicodeDecodeError):
        pass
    return result


def _get_module_info(base_dir: str) -> list[dict]:
    """Get structured info about all .py files in a module directory."""
    info = []
    base = Path(base_dir)
    if not base.exists():
        return info
    for f in sorted(base.rglob("*.py")):
        if f.name == "__init__.py":
            continue
        rel = str(f.relative_to(_PROJECT_ROOT))
        syms = _extract_symbols(str(f))
        syms["relpath"] = rel
        info.append(syms)
    return info


def _build_context() -> str:
    """Build a comprehensive context string about the project for the LLM."""
    sections = []

    # ── Project overview ──
    sections.append("## Project Overview\n")
    sections.append("CodeReviewerBot is an AI-powered code review CLI tool. It supports Python, C/C++, Go, and Rust.")
    sections.append("The tool has four layers:")
    sections.append("1. CLI entry (click commands)")
    sections.append("2. Language analyzers (Python AST, generic line-based for others)")
    sections.append("3. LLM integration (OpenAI-compatible)")
    sections.append("4. Report models (Finding, ReviewReport, Severity, localization)\n")

    # ── CLI module ──
    cli_info = _get_module_info(str(_SRC / "crb" / "cli"))
    sections.append("## CLI Module (src/crb/cli/)\n")
    sections.append("Commands: review, list-langs, list-sort-presets, doctor")
    sections.append("Key options: --lang, --sort, --output (markdown/json), --report-dir, --output-lang\n")
    for f in cli_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        if f["functions"]:
            sections.append("Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── Config module ──
    cfg_info = _get_module_info(str(_SRC / "crb" / "config"))
    sections.append("## Config Module (src/crb/config/)\n")
    sections.append("Dataclasses: AppConfig, LLMConfig, PythonAnalyzerConfig, ComplexityThresholds, RetryThresholds")
    sections.append("LLM config reads from env vars: CRB_LLM_API_URL, CRB_LLM_API_KEY, CRB_LLM_MODEL\n")
    for f in cfg_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        if f["classes"]:
            for cls in f["classes"]:
                sections.append(f"- class {cls['name']} (line {cls['line']})")
        sections.append("")

    # ── Report models ──
    rpt_info = _get_module_info(str(_SRC / "crb" / "report"))
    sections.append("## Report Module (src/crb/report/)\n")
    sections.append("Key types: Severity (Blocker/Critical/Major), OutputLang (ch/en/ch_en), Finding, ReviewReport, FindingCategory")
    sections.append("Localization: _MSG_TEMPLATES dict with bilingual templates for ~14 finding types")
    sections.append("File tree: _build_file_tree() walks filesystem, _extract_symbols() reads source symbols\n")
    for f in rpt_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        if f["classes"]:
            for cls in f["classes"]:
                sections.append(f"- class {cls['name']} (line {cls['line']})")
        if f["functions"]:
            sections.append("Top-level functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── LLM client ──
    llm_info = _get_module_info(str(_SRC / "crb" / "llm"))
    sections.append("## LLM Module (src/crb/llm/)\n")
    sections.append("OpenAI-compatible HTTP client using stdlib urllib")
    sections.append("Functions: chat(), _build_headers(), _build_payload()")
    sections.append("Error: LLMError exception\n")
    for f in llm_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        if f["functions"]:
            sections.append("Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── Python analyzer ──
    py_info = _get_module_info(str(_SRC / "crb" / "analyzers" / "python"))
    sections.append("## Python Analyzer (src/crb/analyzers/python/)\n")
    sections.append("Sub-modules: complexity (AST cyclomatic complexity), retry_detector, style_checker, third_party_suggester, reporter (orchestrator)\n")
    for f in py_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        sections.append(f"Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        if f["classes"]:
            for cls in f["classes"]:
                section_line = f"- class {cls['name']}"
                if cls["methods"]:
                    section_line += ": " + ", ".join(cls["methods"])
                sections.append(section_line)
        sections.append("")

    # ── C/C++ analyzer ──
    c_info = _get_module_info(str(_SRC / "crb" / "analyzers" / "c_cpp"))
    sections.append("## C/C++ Analyzer (src/crb/analyzers/c_cpp/)\n")
    sections.append("Single reporter.py that wraps the generic line-based analyzer for C/C++ files.\n")
    for f in c_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        sections.append(f"Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── Go analyzer ──
    go_info = _get_module_info(str(_SRC / "crb" / "analyzers" / "go"))
    sections.append("## Go Analyzer (src/crb/analyzers/go/)\n")
    sections.append("Single reporter.py that wraps the generic line-based analyzer for Go files.\n")
    for f in go_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        sections.append(f"Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── Rust analyzer ──
    rs_info = _get_module_info(str(_SRC / "crb" / "analyzers" / "rust"))
    sections.append("## Rust Analyzer (src/crb/analyzers/rust/)\n")
    sections.append("Single reporter.py that wraps the generic line-based analyzer for Rust files.\n")
    for f in rs_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        sections.append(f"Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── Generic analyzer ──
    gen_info = _get_module_info(str(_SRC / "crb" / "analyzers"))
    generic_py = [f for f in gen_info if f["relpath"].endswith("generic.py")]
    sections.append("## Generic Analyzer (src/crb/analyzers/generic.py)\n")
    sections.append("Line-based analysis for non-Python languages. Uses regex for complexity estimation.")
    sections.append("Supported: c_family, go, rust")
    sections.append("Functions: analyze_file(), _estimate_function_lines(), _count_lines_in_function()\n")
    for f in generic_py:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        sections.append(f"Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    # ── Detector ──
    det_info = [f for f in gen_info if f["relpath"].endswith("detector.py")]
    sections.append("## Language Detector (src/crb/analyzers/detector.py)\n")
    sections.append("Lang enum: PYTHON, C_CPP, GO, RUST, UNKNOWN")
    sections.append("Functions: detect() -> DetectionResult")
    sections.append("DetectionResult: files dict, lang_counts, primary_lang, detected_langs, label()\n")
    for f in det_info:
        sections.append(f"### {f['relpath']} ({f['lines']} lines)")
        if f["classes"]:
            for cls in f["classes"]:
                methods_str = ", ".join(cls["methods"]) if cls["methods"] else ""
                sections.append(f"- class {cls['name']}: {methods_str}")
        if f["functions"]:
            sections.append(f"Functions: " + ", ".join(fn["name"] for fn in f["functions"]))
        sections.append("")

    return "\n".join(sections)


# ──────────────────────────────────────────────
# Prompt templates for each doc type
# ──────────────────────────────────────────────

_OVERVIEW_PROMPT = """You are a documentation generator for CodeReviewerBot, an AI-powered code review CLI tool.

Generate a project structure overview document at `<proj_root>/docs/structure.md`.

## Format Requirements

Use this EXACT format:

```markdown
# CodeReviewerBot 项目结构

## 总体结构图

```mermaid
graph TD
    NODE_ID["Label<br/>subtitle"] -->|edge label| OTHER["Other"]
    click NODE_ID "relative/path.md" "Description"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| Name | `src/crb/path.py` | Description |

---

> 下层结构文档：
> - [Module Name](module/path.md)
```

## Mermaid Rules

1. Use `graph TD` (top-down)
2. Node IDs: UPPERCASE short names (e.g., CLI, PY, CFG, RPT, LLM_CLIENT, DETECTOR, GENERIC, C_REPORTER, GO_REPORTER, RS_REPORTER)
3. Labels use `"Display Name<br/>subtitle"` format
4. Edge labels use `|label|` syntax
5. ALL nodes must have `click` links:
   - Links to other `.md` docs: relative path from `docs/`: e.g., `cli/structure.md`
   - Links to source files: `../src/crb/path/to/file.py`
6. Group related nodes with subgraphs if helpful

## Required Content

The overview MUST show ALL these modules and their relationships:
1. **CLI** (`src/crb/cli/main.py`) - Entry point, click commands (review, list-langs, list-sort-presets, doctor)
2. **Config** (`src/crb/config/settings.py`) - AppConfig, LLMConfig, thresholds
3. **Report** (`src/crb/report/models.py`) - Finding, ReviewReport, Severity, localization
4. **LLM Client** (`src/crb/llm/client.py`) - OpenAI-compatible chat
5. **Detector** (`src/crb/analyzers/detector.py`) - Language auto-detection
6. **Generic** (`src/crb/analyzers/generic.py`) - Line-based analysis for non-Python
7. **Python Analyzer** (`src/crb/analyzers/python/`) - Reporter, complexity, retry, style, third-party suggester
8. **C/C++ Reporter** (`src/crb/analyzers/c_cpp/reporter.py`)
9. **Go Reporter** (`src/crb/analyzers/go/reporter.py`)
10. **Rust Reporter** (`src/crb/analyzers/rust/reporter.py`)

## File Tree Table

List EVERY module as a row. Format:
| Module | Path | Description |

## Cross-references

At the bottom, list links to ALL sub-structure docs:
- [CLI 模块](cli/structure.md)
- [配置模块](config/structure.md)
- [报告模型](report/structure.md)
- [LLM 客户端](llm/structure.md)
- [通用分析器](analyzers/generic/structure.md)
- [Python 分析器](analyzers/python/structure.md)
- [C/C++ 分析器](analyzers/c_cpp/structure.md)
- [Go 分析器](analyzers/go/structure.md)
- [Rust 分析器](analyzers/rust/structure.md)

## Project Context

{context}

Now output ONLY the markdown content for docs/structure.md."""


_MODULE_PROMPT = """You are a documentation generator for CodeReviewerBot.

Generate a module structure document at `{output_path}`.

## Format

Use this EXACT format with Mermaid graph + file tree table + key functions table:

```markdown
# Module Name

## 结构图

```mermaid
graph TD
    NODE["Label<br/>subtitle"] -->|edge label| OTHER["Other"]
    click NODE "relative/path" "Description"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| Name | `path` | Description |

### 关键函数

| 函数 | 所在文件 | 功能 |
|------|---------|------|
| `func_name()` | `file.py` | Description |
```

## Mermaid Rules
1. `graph TD` layout
2. Node IDs: UPPERCASE
3. Labels: `"Display Name<br/>subtitle"`
4. Edge labels: `|label|`
5. ALL nodes have `click` links:
   - Links to other `.md` docs: relative path from the doc's location (e.g., `../../structure.md` to go up)
   - Links to source files: relative path from the doc's location to `../../src/crb/...` (adjust number of `../` based on depth)
6. Always include navigation links:
   - Upper hierarchy link at bottom: `> 上层结构：[项目总图](../structure.md)` (adjust depth)

## Module Info

{context}

Now output ONLY the markdown content for {output_path}."""


# ──────────────────────────────────────────────
# Doc generation
# ──────────────────────────────────────────────


def _get_parent_depth(output_path: str) -> int:
    """Get how many levels deep this doc is from docs/ root."""
    # docs/a/b/c/structure.md -> depth 2 from docs/
    rel = output_path.replace("docs/", "", 1)
    parts = rel.split("/")
    return len(parts) - 1  # exclude the filename


def _build_prompt(output_path: str, gen_all: bool, context: str) -> str:
    """Build the appropriate prompt for a given doc output path."""
    depth = _get_parent_depth(output_path)

    if output_path == "docs/structure.md":
        return _OVERVIEW_PROMPT.format(context=context)

    # Build context including existing doc examples
    extra_context = context

    # Add existing doc example for reference if available
    if output_path == "docs/cli/structure.md" and "docs/cli/structure.md" in _EXISTING_DOCS:
        extra_context += "\n\n## Existing Doc (reference format)\n\n" + _EXISTING_DOCS["docs/cli/structure.md"]

    if output_path == "docs/analyzers/python/structure.md" and "docs/analyzers/python/structure.md" in _EXISTING_DOCS:
        extra_context += "\n\n## Existing Doc (reference format)\n\n" + _EXISTING_DOCS["docs/analyzers/python/structure.md"]

    return _MODULE_PROMPT.format(output_path=output_path, context=extra_context)


def generate_docs(
    llm_config: LLMConfig,
    output_base: Path,
    gen_all: bool = False,
    verbose: bool = True,
) -> int:
    """Generate documentation for all modules.

    Args:
        llm_config: LLM configuration.
        output_base: Base output directory (usually PROJECT_ROOT).
        gen_all: If True, regenerate ALL docs (including existing).
        verbose: Print progress.

    Returns:
        Number of docs generated.
    """
    _load_existing_docs()
    context = _build_context()

    doc_defs = [
        ("docs/structure.md", "overview"),
        ("docs/config/structure.md", "config"),
        ("docs/report/structure.md", "report"),
        ("docs/llm/structure.md", "llm"),
        ("docs/cli/structure.md", "cli"),
        ("docs/analyzers/generic/structure.md", "generic"),
        ("docs/analyzers/c_cpp/structure.md", "c_cpp"),
        ("docs/analyzers/go/structure.md", "go"),
        ("docs/analyzers/rust/structure.md", "rust"),
        ("docs/analyzers/python/structure.md", "python"),
    ]

    count = 0
    for output_rel, doc_label in doc_defs:
        output_path = output_base / output_rel

        # Skip if exists and not force-generating
        if output_path.exists() and not gen_all:
            if verbose:
                print(f"  [SKIP] {output_rel} (exists, use --all to regenerate)")
            continue

        # Build prompt
        prompt = _build_prompt(output_rel, gen_all, context)

        if verbose:
            print(f"  [GEN]  {output_rel} ({doc_label})...", end=" ", flush=True)

        try:
            system_prompt = (
                "You are a documentation generator for a code review tool. "
                "Generate clean, well-structured markdown with valid Mermaid diagrams. "
                "Output ONLY the markdown content, no explanations or JSON wrappers."
            )
            content = chat(config=llm_config, system_prompt=system_prompt, user_prompt=prompt, temperature=0.1)

            # Clean up the response - remove markdown code fences if the LLM wraps it
            content = content.strip()
            if content.startswith("```markdown"):
                content = content[len("```markdown"):].strip()
            if content.startswith("```"):
                # Find the end of the first line and remove everything up to it
                first_newline = content.find("\n")
                if first_newline >= 0:
                    content = content[first_newline:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()

            # Ensure the output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content + "\n", encoding="utf-8")

            if verbose:
                print(f"OK ({len(content)} bytes)")
            count += 1

        except LLMError as e:
            if verbose:
                print(f"FAILED: {e}")
            continue

    return count


# ──────────────────────────────────────────────
# CLI entry
# ──────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="CodeReviewerBot Doc Generation Agent")
    parser.add_argument("--all", action="store_true", help="Regenerate ALL docs (not just missing)")
    parser.add_argument("--output-dir", default=None, help="Custom output directory (default: project root)")
    parser.add_argument("--verbose", action="store_true", default=True, help="Print progress")
    parser.add_argument("--modules", default=None, help="Comma-separated module names to generate")

    args = parser.parse_args()

    llm_config = LLMConfig.from_env()
    if not llm_config.is_valid():
        print("Error: LLM not configured. Set CRB_LLM_API_URL and CRB_LLM_API_KEY.")
        sys.exit(1)

    output_base = Path(args.output_dir) if args.output_dir else _PROJECT_ROOT
    output_base = output_base.resolve()

    print(f"CodeReviewerBot Doc Generation Agent")
    print(f"Output base: {output_base}")
    print(f"LLM: {llm_config.model or 'default'} @ {llm_config.api_url}")
    print()

    count = generate_docs(llm_config, output_base, gen_all=args.all, verbose=args.verbose)
    print(f"\nDone. Generated {count} document(s).")


if __name__ == "__main__":
    main()
