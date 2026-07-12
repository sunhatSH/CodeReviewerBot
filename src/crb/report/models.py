"""Report data models for code review results."""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from crb.report import structure_builder as sb


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
    "hardcoded_secret": {
        "ch": (
            "疑似硬编码密钥",
            "发现疑似硬编码的 {pattern}，存在安全风险。",
            "将敏感信息移至环境变量或密钥管理服务（如 .env 文件 + .gitignore）。",
        ),
        "en": (
            "Potential Hardcoded Secret",
            "Potential hardcoded {pattern} detected — security risk.",
            "Move sensitive data to environment variables or a secret manager (e.g. .env + .gitignore).",
        ),
    },
    "bare_except": {
        "ch": (
            "裸 except 子句",
            "使用了裸 `except:`，会捕获 KeyboardInterrupt 等系统异常。",
            "指定具体的异常类型，或使用 `except Exception:`。",
        ),
        "en": (
            "Bare Except Clause",
            "Bare `except:` catches system exceptions like KeyboardInterrupt.",
            "Specify an exception type, or use `except Exception:`.",
        ),
    },
    "mutable_default_arg": {
        "ch": (
            "可变默认参数",
            "函数 `{name}` 的默认参数是可变对象，所有调用共享同一实例。",
            "使用 `None` 作为默认值，并在函数体内创建新实例。",
        ),
        "en": (
            "Mutable Default Argument",
            "Function `{name}` has a mutable default argument shared across all calls.",
            "Use `None` as default and create a new instance inside the function body.",
        ),
    },
    "is_comparison": {
        "ch": (
            "应使用 `is` 而非 `{op}`",
            "使用 `{op}` 而不是 `is` 来比较 `{name}`。",
            "使用 `is {name}` 或 `is not {name}` 替代 `{op} {name}`。",
        ),
        "en": (
            "Use `is` Instead of `{op}`",
            "Comparing with `{name}` using `{op}` instead of `is`.",
            "Use `is {name}` or `is not {name}` instead of `{op} {name}`.",
        ),
    },
    "missing_else_branch": {
        "ch": (
            "缺少 else 分支",
            "包含 {count} 个条件的 if-elif 链缺少默认的 else 分支。",
            "添加 else 分支处理所有未覆盖的情况，或显式注释说明为何不需要。",
        ),
        "en": (
            "Missing else Branch",
            "If-elif chain with {count} conditions has no final else branch.",
            "Add an else branch to handle unanticipated cases, or add a comment explaining why it is unnecessary.",
        ),
    },
    "range_len": {
        "ch": (
            "建议使用 enumerate",
            "使用 `range(len(...))` 迭代索引，应改用 `enumerate`。",
            "使用 `for i, item in enumerate(seq):` 替代 `for i in range(len(seq)):`。",
        ),
        "en": (
            "Prefer enumerate",
            "Using `range(len(...))` to iterate by index should use `enumerate` instead.",
            "Use `for i, item in enumerate(seq):` instead of `for i in range(len(seq)):`.",
        ),
    },
    "division_by_zero": {
        "ch": (
            "可能的除零错误",
            "在 `{name}` 中执行除法操作，但除数没有零值检查。",
            "确保除数不为零，或在除法前添加零值检查。",
        ),
        "en": (
            "Potential Division by Zero",
            "Division operation in `{name}` without a preceding zero check on the divisor.",
            "Ensure the divisor is non-zero or add a guard check before division.",
        ),
    },
    "redundant_docstring": {
        "ch": (
            "冗余的文档字符串",
            "函数/类 `{name}` 的文档字符串仅重复了名称。",
            "提供有意义的文档说明其用途、参数和返回值。",
        ),
        "en": (
            "Redundant Docstring",
            "Docstring for `{name}` merely repeats its name.",
            "Provide a meaningful docstring describing purpose, parameters, and return value.",
        ),
    },
    "empty_docstring": {
        "ch": (
            "空的文档字符串",
            "函数/类 `{name}` 有空的文档字符串。",
            "移除空文档字符串或添加有意义的描述。",
        ),
        "en": (
            "Empty Docstring",
            "Function/class `{name}` has an empty docstring.",
            "Remove the empty docstring or add a meaningful description.",
        ),
    },
    "stub_comment": {
        "ch": (
            "缺少详细信息的 {tag} 注释",
            "发现 `{tag}` 注释，但缺少详细描述。",
            "在 `{tag}` 后添加具体的描述，包括负责人和预期修复日期。",
        ),
        "en": (
            "Stub {tag} Comment",
            "`{tag}` comment found without detailed description.",
            "Add a specific description after `{tag}`, including owner and expected fix date.",
        ),
    },
    "too_many_params": {
        "ch": (
            "参数过多",
            "函数 `{name}` 有 {count} 个参数，超过阈值 {threshold}。",
            "考虑将相关参数封装为数据类或配置对象。",
        ),
        "en": (
            "Too Many Parameters",
            "Function `{name}` has {count} parameters, exceeding threshold {threshold}.",
            "Consider grouping related parameters into a data class or config object.",
        ),
    },
    "excessive_nesting": {
        "ch": (
            "嵌套过深",
            "函数 `{name}` 的控制流嵌套深度为 {depth}，超过阈值 {threshold}。",
            "提取内层逻辑为独立函数以降低嵌套深度。",
        ),
        "en": (
            "Excessive Nesting",
            "Function `{name}` has control flow nesting depth {depth}, exceeding threshold {threshold}.",
            "Extract inner logic into separate functions to reduce nesting depth.",
        ),
    },
    "stale_todo": {
        "ch": (
            "过期的 TODO 注释",
            "TODO/FIXME 注释中的日期 {date} 已距今超过 6 个月。",
            "检查该任务是否已处理，如已完成则移除注释，否则更新日期。",
        ),
        "en": (
            "Stale TODO Comment",
            "TODO/FIXME comment dated {date} is over 6 months old.",
            "Check if the task has been addressed: remove if done, or update the date.",
        ),
    },
    "commented_out_code": {
        "ch": (
            "被注释的代码块",
            "发现 {lines} 行被注释的代码（起始行 {start}），可能是废弃代码。",
            "如不再需要则删除注释代码；如需要则取消注释。",
        ),
        "en": (
            "Commented-Out Code Block",
            "Found {lines} lines of commented-out code (starting at line {start}), likely dead code.",
            "Delete if no longer needed, or uncomment if still relevant.",
        ),
    },
    "excessive_isinstance": {
        "ch": (
            "过多的 isinstance 检查",
            "函数 `{name}` 包含 {count} 次 `isinstance` 类型检查，可能缺少多态设计。",
            "考虑使用多态（子类重写方法）替代 isinstance 检查。",
        ),
        "en": (
            "Excessive isinstance Checks",
            "Function `{name}` has {count} isinstance type checks, suggesting missing polymorphism.",
            "Consider using polymorphism (subclass method overrides) instead of isinstance checks.",
        ),
    },
    "silent_except": {
        "ch": (
            "静默的异常捕获",
            "使用 `except {name}: pass` 静默忽略了异常。",
            "至少记录异常日志，或处理具体的异常类型。",
        ),
        "en": (
            "Silent Exception Handling",
            "Using `except {name}: pass` silently ignores exceptions.",
            "At minimum log the exception, or handle specific exception types.",
        ),
    },
    "surface_patching": {
        "ch": (
            "表面修补",
            "在 `{name}` 中使用了 `except {name}: print(...)` 模式——仅打印而非修复。",
            "实现真正的错误处理（重试、回退、或向上传递），而非仅打印。",
        ),
        "en": (
            "Surface-Level Patching",
            "Pattern `except {name}: print(...)` — logs but does not fix.",
            "Implement real error handling (retry, fallback, or propagate) instead of just printing.",
        ),
    },
    "shadows_stdlib": {
        "ch": (
            "模块名覆盖标准库",
            "模块 `{module}` 的名称与 Python 标准库模块冲突。",
            "为重命名的模块换个名称，以避免导入歧义。",
        ),
        "en": (
            "Module Shadows Stdlib",
            "Module `{module}` shadows a Python standard library module.",
            "Rename the module to avoid import ambiguity.",
        ),
    },
    "multi_path_import": {
        "ch": (
            "多路径导入",
            "模块 `{module}` 从多个不同路径导入，可能导致依赖冲突。",
            "检查是否存在同名模块在不同目录中，确保导入路径唯一。",
        ),
        "en": (
            "Multi-Path Import",
            "Module `{module}` is imported from multiple different paths, which may cause dependency conflicts.",
            "Check for duplicate module names across directories and ensure unique import paths.",
        ),
    },
    "test_no_assert": {
        "ch": (
            "测试无断言",
            "测试函数 `{name}` 没有包含任何断言语句。",
            "添加断言验证预期行为，否则该测试无效。",
        ),
        "en": (
            "Test Has No Assertions",
            "Test function `{name}` contains no assertions.",
            "Add assertions to validate expected behavior, otherwise the test is ineffective.",
        ),
    },
    "test_excessive_mock": {
        "ch": (
            "过度 Mock",
            "测试 `{name}` 使用了 {mocks} 个 mock，但只有 {asserts} 个断言。",
            "减少 mock 数量，优先使用真实对象进行集成测试。",
        ),
        "en": (
            "Excessive Mocking",
            "Test `{name}` uses {mocks} mocks but only has {asserts} assertions.",
            "Reduce mocking; prefer real objects for integration testing.",
        ),
    },
    "test_always_true": {
        "ch": (
            "总是通过的断言",
            "测试 `{name}` 包含总是通过的断言（如 `assert True`）。",
            "使用有意义的断言验证实际行为。",
        ),
        "en": (
            "Always-True Assertion",
            "Test `{name}` contains an assertion that always passes (e.g. `assert True`).",
            "Use meaningful assertions to verify actual behavior.",
        ),
    },
    "orphan_code": {
        "ch": (
            "疑似孤儿代码",
            "{kind} `{name}` 在文件 `{file}` 中定义，但未被项目中任何其他代码引用。",
            "检查该 {kind} 是否仍被需要：如已废弃，删除或移入 archived/ 目录；如通过动态方式调用，考虑添加显式引用或 suppression 机制。",
        ),
        "en": (
            "Potentially Orphaned Code",
            "{kind} `{name}` is defined in `{file}` but not referenced by any other code in the project.",
            "Check if this {kind} is still needed: delete if obsolete, or add an explicit reference if dynamically invoked.",
        ),
    },
    "auth_missing_critical": {
        "ch": (
            "鉴权缺失 — 高危",
            "端点 `{name}` ({path}) 缺少身份认证或授权装饰器，可导致未授权数据修改。",
            "添加 @login_required 装饰器；如需更细粒度控制，添加 @permission_required 或角色校验装饰器。",
        ),
        "en": (
            "Missing Auth — Critical",
            "Endpoint `{name}` ({path}) lacks authentication/authorization decorator, allowing unauthorized data mutation.",
            "Add @login_required decorator; for finer control, add @permission_required or role-checking decorators.",
        ),
    },
    "auth_missing_major": {
        "ch": (
            "鉴权缺失 — 中危",
            "端点 `{name}` ({path}) 缺少身份认证装饰器，可能暴露资源标识符。",
            "考虑添加 @login_required 装饰器，并验证用户是否有权访问该资源。",
        ),
        "en": (
            "Missing Auth — Moderate",
            "Endpoint `{name}` ({path}) lacks authentication decorator, potentially exposing resource identifiers.",
            "Consider adding @login_required and verifying user ownership of the resource.",
        ),
    },
    "auth_missing_minor": {
        "ch": (
            "鉴权缺失 — 注意",
            "路由端点 `{name}` ({path}) 缺少显式身份认证装饰器。",
            "确认该端点是否应公开访问；如需要认证，添加 @login_required 装饰器。",
        ),
        "en": (
            "Missing Auth — Advisory",
            "Route endpoint `{name}` ({path}) lacks explicit authentication decorator.",
            "Verify this endpoint is intended for public access; add @login_required if authentication is needed.",
        ),
    },
    "layered_test_gap": {
        "ch": (
            "分层测试覆盖缺失",
            "函数 `{name}`（在 `{file}` 中）被 {callers} 调用，但没有直接对应的测试代码。",
            "为该函数添加单元测试，测试其独立行为，而非仅靠调用者测试间接覆盖。",
        ),
        "en": (
            "Missing Layered Test Coverage",
            "Function `{name}` (in `{file}`) is called by {callers} but has no direct tests.",
            "Add unit tests for this function to verify its behavior independently, not just through caller tests.",
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
    def _extract_symbols(file_path: str) -> list[tuple[str, list[str]]]:
        """Extract symbols from a source file. Delegates to structure_builder."""
        return sb.extract_symbols(file_path)

    def _build_file_tree(self, subdir: str | None = None) -> str:
        """Generate a project file tree. Delegates to structure_builder."""
        return sb.build_file_tree(self.all_files, subdir=subdir)

    def _render_tree(self, node: dict, lines: list[str], prefix: str) -> None:
        sb._render_tree(node, lines, prefix)

    def _render_symbols(self, symbols, lines, prefix, has_more_after):
        sb._render_symbols(symbols, lines, prefix, has_more_after)

    def _build_mermaid_diagram(self, subdir: str | None = None) -> str:
        """Generate a Mermaid flowchart. Delegates to structure_builder."""
        return sb.build_mermaid_diagram(self.all_files, subdir=subdir)

    def generate_hierarchical_structure_docs(self, output_dir: str) -> list[str]:
        """Generate hierarchical structure docs. Delegates to structure_builder."""
        return sb.generate_hierarchical_structure_docs(self.all_files, output_dir)

    def generate_structure_json(self, output_dir: str) -> dict:
        """Build structured JSON data. Delegates to structure_builder."""
        return sb.generate_structure_json(self.all_files, output_dir)

    def to_markdown(self) -> str:
        self.sort_findings()
        L = lambda k: _lbl(k, self.lang)  # noqa: E731
        lines = []

        lines.append(f"# {L('code_review_report')}\n")
        lines.append(f"**{L('target')}**: {self.target}\n")

        # Reference to separate structure doc
        lines.append("---\n")
        lines.append("> 项目结构总览见 [../structure.md](../structure.md)\n")
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
