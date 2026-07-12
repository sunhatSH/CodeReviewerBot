# Generic Analyzer Module

## 结构图

```mermaid
graph TD
    CLI["CLI Entry<br/>review command"] -->|--lang option| DETECTOR["Language Detector<br/>detector.py"]
    DETECTOR -->|non-Python| GENERIC["Generic Analyzer<br/>generic.py"]
    GENERIC -->|findings| REPORT["Report Module<br/>models.py"]
    GENERIC -->|regex analysis| FUNC_EST["Function Estimation<br/>_estimate_function_lines"]
    FUNC_EST -->|line counting| LINE_COUNT["Line Counter<br/>_count_lines_in_function"]
    click CLI "../../cli/structure.md" "CLI module structure"
    click DETECTOR "../../src/crb/analyzers/detector.py" "Language detector source"
    click GENERIC "../../src/crb/analyzers/generic.py" "Generic analyzer source"
    click REPORT "../../report/structure.md" "Report models"
    click FUNC_EST "../../src/crb/analyzers/generic.py" "Function estimation logic"
    click LINE_COUNT "../../src/crb/analyzers/generic.py" "Line counting logic"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| Generic Analyzer | `src/crb/analyzers/generic.py` | Line-based analysis for non-Python languages (C/C++, Go, Rust) |
| Language Detector | `src/crb/analyzers/detector.py` | Detects programming language from file extensions |

## 关键函数

| 函数 | 所在文件 | 功能 |
|------|---------|------|
| `analyze_file()` | `generic.py` | Main entry point: analyzes a single source file for complexity issues |
| `_estimate_function_lines()` | `generic.py` | Estimates function length using regex pattern matching |
| `_count_lines_in_function()` | `generic.py` | Counts actual lines within a detected function block |

> 上层结构：[分析器总图](../structure.md)
