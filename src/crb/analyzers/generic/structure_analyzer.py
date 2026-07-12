"""Structure-based AI code spread analyzer.

Detects patterns of AI-generated code dispersion in the target project:
- Over-fragmented files (1-2 symbols per file)
- Unnecessary abstraction layers
- Deep directory nesting
- Scattered related logic
- Bloated single-purpose modules

Uses the file tree and symbol data from structure docs to identify
consolidation opportunities.

Requirements: 2.2 代码审查能力 — AI 代码膨胀趋势
"""

from __future__ import annotations

import os
from pathlib import Path
from collections import defaultdict

from crb.report.models import Finding, FindingCategory, Severity, OutputLang
from crb.report.structure_builder import extract_symbols, build_file_tree


_SPREAD_THRESHOLDS = {
    "min_symbols_per_file": 2,       # Files with fewer than this are "over-fragmented"
    "max_depth": 5,                   # Nesting deeper than this is "deep nesting"
    "max_files_per_module": 20,       # More files than this per module = possible scatter
    "one_class_files_ratio": 0.3,     # If >30% of files have only 1 class = over-abstracted
    "max_empty_symbols": 0.5,         # If >50% files have 0 symbols = possibly config/data scatter
}


def analyze_structure(
    all_files: list[str],
    project_root: str | None = None,
    lang: OutputLang = OutputLang.CH,
) -> list[Finding]:
    """Analyze project file structure for AI code spread patterns.

    Args:
        all_files: All project source files (absolute paths).
        project_root: Project root directory.
        lang: Output language.

    Returns:
        List of findings about structural issues.
    """
    findings: list[Finding] = []

    if not all_files:
        return findings

    # Normalize file list — resolve all to absolute paths
    source_files = [str(Path(f).resolve()) for f in all_files if _is_source_file(f)]
    if not source_files:
        return findings

    # 1. Over-fragmented files: many files with few symbols
    findings.extend(_check_fragmentation(source_files))

    # 2. Deep nesting: overly deep directory trees
    findings.extend(_check_deep_nesting(source_files))

    # 3. Module scatter: module with too many files
    findings.extend(_check_module_scatter(source_files, project_root))

    # 4. One-class-per-file syndrome
    findings.extend(_check_one_class_per_file(source_files))

    # 5. Empty/skeleton files
    findings.extend(_check_empty_files(source_files))

    return findings


def _is_source_file(fp: str) -> bool:
    """Check if file is a source file with expected symbols."""
    ext = os.path.splitext(fp)[1].lower()
    if ext not in (".py", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"):
        return False
    parts = Path(fp).parts
    skip_parts = {"__pycache__", "node_modules", ".git", "build", "dist",
                  ".egg-info", ".venv", "venv", "report", "archived"}
    if any(p in skip_parts or p.startswith(".") for p in parts):
        return False
    # Skip __init__.py (expected to be empty of custom symbols)
    if Path(fp).name == "__init__.py":
        return False
    return True


def _check_fragmentation(source_files: list[str]) -> list[Finding]:
    """Detect over-fragmented files (fewer than threshold symbols)."""
    findings: list[Finding] = []
    low_symbol_files: list[tuple[str, int]] = []

    for fp in source_files:
        symbols = extract_symbols(fp)
        # Count top-level symbols (classes + functions)
        count = len(symbols)
        if count < _SPREAD_THRESHOLDS["min_symbols_per_file"]:
            low_symbol_files.append((fp, count))

    if not low_symbol_files:
        return findings

    ratio = len(low_symbol_files) / len(source_files)
    if ratio < 0.15:
        return findings  # Not significant enough

    # Group by directory to find clusters of over-fragmentation
    dir_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for fp, count in low_symbol_files:
        dir_name = str(Path(fp).parent)
        dir_groups[dir_name].append((fp, count))

    # Report worst directories
    for dir_name, files in sorted(dir_groups.items(),
                                  key=lambda x: -len(x[1]))[:5]:
        if len(files) < 3:
            continue

        file_list = "\n".join(
            f"  - {Path(f).name} ({cnt} symbols)"
            for f, cnt in files[:8]
        )
        if len(files) > 8:
            file_list += f"\n  ... and {len(files) - 8} more"

        dir_label = Path(dir_name).name or dir_name
        findings.append(
            Finding(
                file=dir_name,
                line=0,
                severity=Severity.MAJOR,
                category=FindingCategory.DESIGN,
                title=f"文件过于碎片化: {dir_label}",
                message=(
                    f"目录 '{dir_label}' 中有 {len(files)} 个文件内容过少 "
                    f"(< {_SPREAD_THRESHOLDS['min_symbols_per_file']} 个符号)。"
                    f"占总文件数 {len(low_symbol_files)}/{len(source_files)} "
                    f"({ratio:.0%})。\n\n"
                    f"AI 生成代码倾向于将功能拆散到过多小文件中，"
                    f"增加认知负荷而缺乏实际收益。\n\n"
                    f"文件列表:\n{file_list}"
                ),
                suggestion=(
                    "考虑合并相关的小文件：\n"
                    "1. 将同一模块下功能相关的代码合并到 2-3 个文件中\n"
                    "2. 避免为每个类或函数单独建文件\n"
                    "3. 参照同一项目中手写代码的粒度来组织"
                ),
            )
        )

    return findings


def _check_deep_nesting(source_files: list[str]) -> list[Finding]:
    """Detect overly deep directory nesting."""
    findings: list[Finding] = []
    max_depth = _SPREAD_THRESHOLDS["max_depth"]

    # Track deepest directories
    depth_counts: dict[int, int] = defaultdict(int)
    deep_dirs: set[str] = set()

    root = _find_root(source_files)
    if root:
        for fp in source_files:
            try:
                rel = Path(fp).resolve().relative_to(root)
                depth = len(rel.parent.parts)
            except ValueError:
                depth = len(Path(fp).resolve().parts)
            depth_counts[depth] += 1
    else:
        for fp in source_files:
            depth = len(Path(fp).resolve().parts)
            depth_counts[depth] += 1
        if depth > max_depth:
            deep_dirs.add(str(rel.parent))

    if not deep_dirs:
        return findings

    deep_ratio = sum(
        count for depth, count in depth_counts.items() if depth > max_depth
    ) / len(source_files)

    if deep_ratio < 0.05:
        return findings  # Only a few deep files, not a pattern

    deep_list = "\n".join(sorted(deep_dirs)[:8])
    if len(deep_dirs) > 8:
        deep_list += f"\n... and {len(deep_dirs) - 8} more"

    findings.append(
        Finding(
            file=source_files[0],
            line=0,
            severity=Severity.MAJOR,
            category=FindingCategory.COMPLEXITY,
            title="目录嵌套过深",
            message=(
                f"项目存在 {len(deep_dirs)} 个深度超过 {max_depth} 层的目录。"
                f"深度嵌套 {deep_ratio:.0%} 的文件。\n\n"
                f"AI 倾向于创建多层目录结构来组织代码，"
                f"但超过 5 层的嵌套会显著降低可维护性。\n\n"
                f"深层目录:\n{deep_list}"
            ),
            suggestion=(
                "考虑扁平化目录结构：\n"
                "1. 将深度超过 4 层的目录上提\n"
                "2. 使用更宽的命名空间而非更深的目录\n"
                "3. 将深层子模块作为独立包提取"
            ),
        )
    )

    return findings


def _check_module_scatter(
    source_files: list[str], project_root: str | None,
) -> list[Finding]:
    """Detect modules with too many files (possible scatter)."""
    findings: list[Finding] = []
    threshold = _SPREAD_THRESHOLDS["max_files_per_module"]

    # Group by top-level module directory
    root = Path(project_root).resolve() if project_root else _find_root(source_files)
    if not root:
        return findings

    module_files: dict[str, list[str]] = defaultdict(list)
    for fp in source_files:
        try:
            rel = Path(fp).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        parts = rel.split("/")
        if len(parts) >= 2:
            module_files[parts[0]].append(fp)

    for mod, files in sorted(module_files.items()):
        if len(files) <= threshold:
            continue

        # Check if many files have few symbols (indicating scatter)
        small_files = sum(
            1 for fp in files
            if len(extract_symbols(fp)) < _SPREAD_THRESHOLDS["min_symbols_per_file"]
        )
        small_ratio = small_files / len(files)

        if small_ratio < 0.2:
            # Module has many files but they're substantive — not scatter
            continue

        mod_label = mod.replace("_", " ").replace("-", " ").title()
        findings.append(
            Finding(
                file=str(root / mod),
                line=0,
                severity=Severity.MAJOR,
                category=FindingCategory.DESIGN,
                title=f"模块分散: {mod_label}",
                message=(
                    f"模块 '{mod_label}' 有 {len(files)} 个源文件，"
                    f"其中 {small_files} 个 ({small_ratio:.0%}) 符号少于 "
                    f"{_SPREAD_THRESHOLDS['min_symbols_per_file']} 个。\n\n"
                    f"这可能是 AI 将相关功能过度分散到过多文件中。"
                ),
                suggestion=(
                    f"考虑将模块 '{mod_label}' 的文件数量减少到 {threshold} 个以下：\n"
                    "1. 将功能相关的 2-3 个文件合并为一个\n"
                    "2. 识别并删除仅包含辅助函数的单次使用文件\n"
                    "3. 确保每个文件有独立且清晰的职责"
                ),
            )
        )

    return findings


def _check_one_class_per_file(source_files: list[str]) -> list[Finding]:
    """Detect one-class-per-file syndrome (Java-style in Python/Go)."""
    findings: list[Finding] = []
    source_py = [f for f in source_files if f.endswith(".py")]

    if len(source_py) < 5:
        return findings

    one_class_files = 0
    examples: list[str] = []

    for fp in source_py:
        symbols = extract_symbols(fp)
        classes = [s for s in symbols if s[0].startswith("class ")]
        total_symbols = len(symbols)

        # One class, nothing else (except maybe __init__)
        if total_symbols <= 1 and len(classes) == 1:
            one_class_files += 1
            if len(examples) < 5:
                examples.append(Path(fp).name)

    ratio = one_class_files / len(source_py)
    if ratio < _SPREAD_THRESHOLDS["one_class_files_ratio"]:
        return findings

    findings.append(
        Finding(
            file=source_py[0],
            line=0,
            severity=Severity.MAJOR,
            category=FindingCategory.DESIGN,
            title="单类文件过载",
            message=(
                f"{one_class_files}/{len(source_py)} 个 Python 文件 ({ratio:.0%}) "
                f"仅包含一个类，没有其他函数或代码。\n\n"
                f'这种「一个类一个文件」的模式常见于 AI 生成的代码中，'
                f"它会不必要地增加项目文件数量和维护成本。\n\n"
                f"示例: {', '.join(examples[:5])}"
            ),
            suggestion=(
                "考虑合并细粒度类：\n"
                "1. 将相关的小类放在同一个文件中\n"
                "2. 如果类少于 50 行且只被一处引用，直接合并到使用处\n"
                "3. Python 不要求每个类一个文件 — 利用模块级组织"
            ),
        )
    )

    return findings


def _check_empty_files(source_files: list[str]) -> list[Finding]:
    """Detect non-init files with zero symbols (config, data, or stub files)."""
    findings: list[Finding] = []
    empty_files: list[str] = []

    for fp in source_files:
        if Path(fp).name == "__init__.py":
            continue
        symbols = extract_symbols(fp)
        if len(symbols) == 0:
            empty_files.append(fp)

    if not empty_files:
        return findings

    ratio = len(empty_files) / len(source_files)
    if ratio < _SPREAD_THRESHOLDS["max_empty_symbols"]:
        return findings

    empty_list = "\n".join(
        f"  - {Path(f).relative_to(_find_root(source_files) or '/')}"
        for f in empty_files[:10]
    )
    if len(empty_files) > 10:
        empty_list += f"\n  ... and {len(empty_files) - 10} more"

    findings.append(
        Finding(
            file=empty_files[0],
            line=0,
            severity=Severity.MAJOR,
            category=FindingCategory.DESIGN,
            title="过多的零符号文件",
            message=(
                f"{len(empty_files)}/{len(source_files)} 个文件 ({ratio:.0%}) "
                f"不包含任何类或函数定义。这些可能是配置文件、数据文件或未完成的存根。\n\n"
                f"零符号文件列表:\n{empty_list}"
            ),
            suggestion=(
                "检查这些文件：\n"
                "1. 如果是数据/配置文件，考虑移到 data/ 或 config/ 目录\n"
                "2. 如果是未完成的存根，完成实现或删除\n"
                "3. 如果是 `__init__.py`，确保其有明确的导入或文档"
            ),
        )
    )

    return findings


def _resolve_all(source_files: list[str]) -> list[Path]:
    """Resolve all file paths to absolute."""
    return [Path(f).resolve() for f in source_files]


def _find_root(source_files: list[str]) -> Path | None:
    """Find the common root directory from a list of files."""
    if not source_files:
        return None
    try:
        resolved = _resolve_all(source_files)
        common = os.path.commonpath([str(p) for p in resolved])
        return Path(common)
    except (ValueError, OSError):
        return Path(source_files[0]).resolve().parent
