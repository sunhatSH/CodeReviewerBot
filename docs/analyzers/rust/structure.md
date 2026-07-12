# Rust Analyzer Module

## 结构图

```mermaid
graph TD
    RUST["Rust Analyzer<br/>src/crb/analyzers/rust/"] -->|wraps| GENERIC["Generic Analyzer<br/>src/crb/analyzers/generic.py"]
    RUST -->|called by| CLI["CLI Module<br/>src/crb/cli/"]
    RUST -->|produces| REPORT["Report Module<br/>src/crb/report/"]
    click RUST "../../src/crb/analyzers/rust/reporter.py" "Rust analyzer source"
    click GENERIC "../generic/structure.md" "Generic analyzer documentation"
    click CLI "../../cli/structure.md" "CLI module documentation"
    click REPORT "../../report/structure.md" "Report module documentation"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| Rust Analyzer | `src/crb/analyzers/rust/reporter.py` | Orchestrates Rust file analysis using generic line-based analyzer |

### 关键函数

| 函数 | 所在文件 | 功能 |
|------|---------|------|
| `analyze_files()` | `reporter.py` | Analyzes all Rust files in the given list, delegates to generic analyzer |

> 上层结构：[分析器总图](../structure.md)
