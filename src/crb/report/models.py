"""Report data models for code review results."""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Severity(str, Enum):
    BLOCKER = "Blocker"
    CRITICAL = "Critical"
    MAJOR = "Major"

    @property
    def sort_key(self) -> int:
        return {"Blocker": 0, "Critical": 1, "Major": 2}[self.value]


class OutputLang(str, Enum):
    CH = "ch"
    EN = "en"
    CH_EN = "ch_en"


# Localized strings
_LABELS: dict[str, dict[str, str]] = {
    "code_review_report": {
        "ch": "代码审查报告",
        "en": "Code Review Report",
        "ch_en": "Code Review Report / 代码审查报告",
    },
    "target": {
        "ch": "审查目标",
        "en": "Target",
        "ch_en": "Target / 审查目标",
    },
    "summary": {
        "ch": "概要",
        "en": "Summary",
        "ch_en": "Summary / 概要",
    },
    "no_issues": {
        "ch": "未发现问题。",
        "en": "No issues found.",
        "ch_en": "No issues found. / 未发现问题。",
    },
    "issues": {
        "ch": "问题列表",
        "en": "Issues",
        "ch_en": "Issues / 问题列表",
    },
    "style_issues": {
        "ch": "风格问题",
        "en": "Style Issues",
        "ch_en": "Style Issues / 风格问题",
    },
    "file": {
        "ch": "文件",
        "en": "File",
        "ch_en": "File / 文件",
    },
    "line": {
        "ch": "行号",
        "en": "Line",
        "ch_en": "Line / 行号",
    },
    "category": {
        "ch": "类别",
        "en": "Category",
        "ch_en": "Category / 类别",
    },
    "message": {
        "ch": "信息",
        "en": "Message",
        "ch_en": "Message / 信息",
    },
    "suggestion": {
        "ch": "建议",
        "en": "Suggestion",
        "ch_en": "Suggestion / 建议",
    },
}


def _lbl(key: str, lang: OutputLang) -> str:
    return _LABELS.get(key, {}).get(lang.value, _LABELS.get(key, {}).get("en", key))


# Finding message templates (title, message, suggestion) with format placeholders
_MSG_TEMPLATES: dict[str, dict[str, tuple[str, str, str]]] = {
    "high_complexity": {
        "ch": (
            "圈复杂度过高",
            "函数 `{name}` 的圈复杂度为 {cc}，超过阈值 {threshold}。",
            "考虑将 `{name}` 拆分为更小的函数，或添加 @complex_func 装饰器显式忽略。",
        ),
        "en": (
            "High Cyclomatic Complexity",
            "Function `{name}` has cyclomatic complexity {cc}, exceeding threshold {threshold}.",
            "Consider breaking `{name}` into smaller functions. Add @complex_func decorator to explicitly suppress this warning.",
        ),
    },
    "high_complexity_estimated": {
        "ch": (
            "圈复杂度过高（估算）",
            "函数 `{name}` 的估算复杂度为 {cc}，超过阈值 {threshold}。",
            "考虑将 `{name}` 拆分为更小的函数。",
        ),
        "en": (
            "High Cyclomatic Complexity (estimated)",
            "Function `{name}` has estimated complexity {cc}, exceeding threshold {threshold}.",
            "Consider refactoring `{name}` into smaller functions.",
        ),
    },
    "overly_long_function": {
        "ch": (
            "函数过长",
            "函数 `{name}` 有 {lines} 行，超过阈值 {threshold} 行。",
            "将 `{name}` 重构为更小的子函数，或使用 @complex_func 装饰器忽略。",
        ),
        "en": (
            "Overly Long Function",
            "Function `{name}` is {lines} lines, exceeding threshold {threshold}.",
            "Refactor `{name}` into smaller sub-functions or use @complex_func to suppress.",
        ),
    },
    "overly_long_function_estimated": {
        "ch": (
            "函数过长",
            "函数 `{name}` 约有 {lines} 行，超过阈值 {threshold} 行。",
            "将 `{name}` 重构为更小的子函数。",
        ),
        "en": (
            "Overly Long Function",
            "Function `{name}` is ~{lines} lines, exceeding threshold {threshold}.",
            "Refactor `{name}` into smaller sub-functions.",
        ),
    },
    "overly_large_class": {
        "ch": (
            "类过大",
            "类 `{name}` 有 {lines} 行，超过阈值 {threshold} 行。",
            "考虑拆分 `{name}` 或添加 @complex_func 装饰器忽略。",
        ),
        "en": (
            "Overly Large Class",
            "Class `{name}` is {lines} lines, exceeding threshold {threshold}.",
            "Consider splitting `{name}` or applying @complex_func to suppress.",
        ),
    },
    "syntax_error": {
        "ch": (
            "语法错误",
            "解析文件失败：{msg}",
            None,
        ),
        "en": (
            "Syntax Error",
            "Failed to parse file: {msg}",
            None,
        ),
    },
    "overly_long_file": {
        "ch": (
            "文件过长",
            "文件共 {lines} 行（建议不超过 1000 行）。",
            "拆分为多个模块。",
        ),
        "en": (
            "Overly Long File",
            "File is {lines} lines (recommended < 1000).",
            "Split into multiple modules.",
        ),
    },
    "excessive_retry_decorator": {
        "ch": (
            "重试装饰器次数过多",
            "函数 `{name}` 使用了 @retry 装饰器，最大重试次数为 {attempts}（建议不超过 {threshold}）。",
            "检查是否为必要的重试，或使用 `@retry(stop=stop_after_attempt({threshold}))` 限制。",
        ),
        "en": (
            "Excessive Retry Decorator Attempts",
            "Function `{name}` uses @retry with max {attempts} attempts (recommended <= {threshold}).",
            "Verify the retry is necessary or limit with `@retry(stop=stop_after_attempt({threshold}))`.",
        ),
    },
    "excessive_retry_loop": {
        "ch": (
            "循环重试次数过多",
            "在 `{name}` 中检测到错误重试循环，最大重试次数为 {attempts}（建议不超过 {threshold}）。",
            "考虑实现指数退避，或将重试逻辑封装到装饰器中。",
        ),
        "en": (
            "Excessive Error Retry in Loop",
            "Error retry loop detected in `{name}`, max {attempts} attempts (recommended <= {threshold}).",
            "Consider exponential backoff or wrapping retry logic in a decorator.",
        ),
    },
    "wildcard_import": {
        "ch": (
            "通配符导入",
            "通配符导入 `*` 污染了命名空间。",
            "导入具体的名称。",
        ),
        "en": (
            "Wildcard Import",
            "Wildcard import `*` pollutes namespace.",
            "Import specific names instead.",
        ),
    },
    "global_statement": {
        "ch": (
            "使用了 global 语句",
            "全局变量 `{names}` 降低了可预测性。",
            "将值作为参数传递或使用类来管理状态。",
        ),
        "en": (
            "Use of `global` Statement",
            "Global variables `{names}` reduce predictability.",
            "Pass values as parameters or use a class instead.",
        ),
    },
    "short_variable_name": {
        "ch": (
            "变量名无描述性",
            "单字符变量 `{name}` 降低可读性。",
            "使用有描述性的名称。",
        ),
        "en": (
            "Non-Descriptive Variable Name",
            "Single-character variable `{name}` reduces readability.",
            "Use a descriptive name instead.",
        ),
    },
    "no_python_files": {
        "ch": (
            "未找到 Python 文件",
            "在给定路径中未找到 .py 文件。",
            None,
        ),
        "en": (
            "No Python Files Found",
            "No .py files matched the given paths.",
            None,
        ),
    },
    "cli_argparse": {
        "ch": (
            "建议使用 CLI 框架",
            "函数 `{name}` 中使用了 `sys.argv` 手动解析命令行参数。",
            "考虑使用 `click` 或 `typer` 等 CLI 框架，减少样板代码。",
        ),
        "en": (
            "Consider Using a CLI Framework",
            "Function `{name}` parses CLI arguments via `sys.argv` manually.",
            "Consider using `click` or `typer` to reduce boilerplate.",
        ),
    },
    "manual_retry": {
        "ch": (
            "建议使用重试库",
            "函数 `{name}` 使用了 `time.sleep()` 实现手动重试。",
            "考虑使用 `tenacity` 或 `backoff` 库实现更稳健的重试逻辑。",
        ),
        "en": (
            "Consider Using a Retry Library",
            "Function `{name}` implements manual retry with `time.sleep()`.",
            "Consider using `tenacity` or `backoff` for robust retry logic.",
        ),
    },
}


def _finding_msg(
    lang: OutputLang, key: str, **kwargs: object
) -> tuple[str, str, Optional[str]]:
    """Get localized (title, message, suggestion) for a finding type."""
    templates = _MSG_TEMPLATES.get(key, {})
    t = templates.get(lang.value) or templates.get("en", ("", "", None))
    title = str(t[0]).format(**kwargs)
    msg = str(t[1]).format(**kwargs)
    suggestion = str(t[2]).format(**kwargs) if t[2] else None
    return title, msg, suggestion


class FindingCategory(str, Enum):
    COMPLEXITY = "complexity"
    RETRY = "retry"
    STYLE = "style"
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DESIGN = "design"
    DOCUMENTATION = "documentation"
    ORPHAN = "orphan"
    TEST = "test"
    DEPENDENCY = "dependency"
    CONSISTENCY = "consistency"


@dataclass
class Finding:
    file: str
    line: int
    severity: Severity
    category: FindingCategory
    title: str
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "severity": self.severity.value,
            "category": self.category.value,
            "title": self.title,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class ReviewReport:
    target: str  # file or directory path
    findings: list[Finding] = field(default_factory=list)
    lang: OutputLang = OutputLang.EN
    all_files: list[str] = field(default_factory=list)
    _sort_order: list[Severity] = field(
        default_factory=lambda: [Severity.BLOCKER, Severity.CRITICAL, Severity.MAJOR]
    )

    def set_sort_order(self, order: list[Severity]) -> None:
        self._sort_order = order

    def sort_findings(self) -> None:
        severity_rank = {s.value: i for i, s in enumerate(self._sort_order)}

        self.findings.sort(
            key=lambda f: (
                severity_rank.get(f.severity.value, 99),
                f.file,
                f.line,
            )
        )

    def add_finding(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def blocker_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.BLOCKER)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def major_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.MAJOR)

    @staticmethod
    def _extract_symbols(file_path: str) -> list[str]:
        """Extract class and function names from a source file."""
        symbols: list[str] = []
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".py":
                with open(file_path) as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        symbols.append(f"class {node.name}")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(f"def {node.name}()")
            elif ext in (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx"):
                with open(file_path) as f:
                    content = f.read()
                for m in re.finditer(
                    r"^\s*(?:static\s+|inline\s+|virtual\s+)?"
                    r"(?:int|void|char|float|double|long|short|unsigned|signed|"
                    r"size_t|bool|string|auto|const|volatile|struct|class|"
                    r"\w+_t|FILE|char\*|void\*)\s*(\w+)\s*\(",
                    content, re.MULTILINE,
                ):
                    symbols.append(f"def {m.group(1)}()")
            elif ext == ".go":
                with open(file_path) as f:
                    content = f.read()
                for m in re.finditer(
                    r"^\s*(?:func\s+)(?:\([^)]*\)\s+)?(\w+)\s*\(",
                    content, re.MULTILINE,
                ):
                    symbols.append(f"func {m.group(1)}()")
            elif ext == ".rs":
                with open(file_path) as f:
                    content = f.read()
                for m in re.finditer(
                    r"^\s*(?:pub\s+)?(?:fn\s+)(\w+)\s*[\(<]",
                    content, re.MULTILINE,
                ):
                    symbols.append(f"fn {m.group(1)}()")
        except (SyntaxError, OSError, UnicodeDecodeError):
            pass
        return symbols

    def _build_file_tree(self) -> str:
        """Generate a full project file tree with class/function symbols."""
        # Determine root directory
        root_dir: str | None = None
        if self.all_files:
            normalized = [fp.replace(os.sep, "/").rstrip("/") for fp in self.all_files]
            common = os.path.commonprefix(normalized)
            if "/" in common:
                common = common[: common.rfind("/") + 1]
            if common.strip("/"):
                root_dir = common
        if not root_dir and self.target:
            root_dir = self.target
        if not root_dir or not os.path.isdir(root_dir):
            return "(no project root)"

        # Build nested dict of the directory tree with symbols
        tree: dict = {}
        ignore_patterns = (".git", ".DS_Store", "__pycache__", "build", "node_modules", ".egg-info")
        ignore_suffixes = (".egg-info", ".pyc")
        root_path = Path(root_dir)

        for entry in sorted(root_path.rglob("*")):
            rel = entry.relative_to(root_path).as_posix()
            if any(
                part.startswith(".") or part in ignore_patterns
                or any(part.endswith(suf) for suf in ignore_suffixes)
                for part in entry.parts
            ):
                continue

            parts = rel.split("/")
            node = tree
            for i, part in enumerate(parts):
                if i == len(parts) - 1 and entry.is_file():
                    # File node — add symbols as children
                    symbols = self._extract_symbols(str(entry))
                    node = node.setdefault(part, {"__symbols__": symbols} if symbols else {})
                else:
                    node = node.setdefault(part, {})

        # Render
        root_name = root_path.name
        lines = ["```"]
        lines.append(root_name)
        self._render_tree(tree, lines, prefix="")
        lines.append("```")
        return "\n".join(lines)

    def _render_tree(
        self, node: dict, lines: list[str], prefix: str
    ) -> None:
        items = sorted((k, v) for k, v in node.items() if not k.startswith("__"))
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}")
            extension = "    " if is_last else "│   "

            # Render symbols nested under this file
            symbols: list[str] = subtree.get("__symbols__", []) if isinstance(subtree, dict) else []
            children_exist = subtree and any(not k.startswith("__") for k in subtree)
            for si, sym in enumerate(symbols):
                sym_last = si == len(symbols) - 1 and not children_exist
                sym_conn = "└── " if sym_last else "├── "
                lines.append(f"{prefix}{extension}{sym_conn}{sym}")

            # Render children (subdirectories, other files)
            if children_exist:
                self._render_tree(subtree, lines, prefix + extension)

    def to_markdown(self) -> str:
        self.sort_findings()
        L = lambda k: _lbl(k, self.lang)  # noqa: E731
        lines = []

        lines.append(f"# {L('code_review_report')}\n")
        lines.append(f"**{L('target')}**: {self.target}\n")

        # File tree overview
        lines.append("---\n")
        lines.append("### Project Structure\n")
        lines.append(self._build_file_tree())
        lines.append("")
        lines.append("---\n")
        lines.append(
            f"**{L('summary')}**: "
            f"{self.blocker_count} Blocker, "
            f"{self.critical_count} Critical, "
            f"{self.major_count} Major\n"
        )

        if not self.findings:
            lines.append(f"_{L('no_issues')}_\n")
            return "\n".join(lines)

        lines.append("---\n")

        style_items = [f for f in self.findings if f.category == FindingCategory.STYLE]
        non_style_items = [
            f for f in self.findings if f.category != FindingCategory.STYLE
        ]

        for items, header_key in [
            (non_style_items, "issues"),
            (style_items, "style_issues"),
        ]:
            if not items:
                continue
            lines.append(f"## {L(header_key)}\n")
            for f in items:
                badge = {
                    Severity.BLOCKER: "🔴 **Blocker**",
                    Severity.CRITICAL: "🟠 **Critical**",
                    Severity.MAJOR: "🟡 **Major**",
                }[f.severity]

                lines.append(f"### {badge}: {f.title}\n")
                lines.append(f"- **{L('file')}**: `{f.file}`")
                lines.append(f"- **{L('line')}**: `{f.line}`")
                lines.append(f"- **{L('category')}**: `{f.category.value}`")
                lines.append(f"- **{L('message')}**: {f.message}")
                if f.suggestion:
                    lines.append(f"- **{L('suggestion')}**: {f.suggestion}")
                lines.append("")

        return "\n".join(lines)
