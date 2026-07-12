# C/C++ Analyzer Module

## 结构图

```mermaid
graph TD
    C_CPP["C/C++ Analyzer<br/>src/crb/analyzers/c_cpp/"] -->|wraps| GENERIC["Generic Analyzer<br/>src/crb/analyzers/generic.py"]
    C_CPP -->|uses| DETECTOR["Language Detector<br/>src/crb/analyzers/detector.py"]
    C_CPP -->|produces| REPORT["Report Module<br/>src/crb/report/models.py"]
    click C_CPP "../../src/crb/analyzers/c_cpp/reporter.py" "C/C++ analyzer source"
    click GENERIC "../generic/structure.md" "Generic analyzer documentation"
    click DETECTOR "../../src/crb/analyzers/detector.py" "Language detector source"
    click REPORT "../../report/structure.md" "Report models and formatting"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| C/C++ Reporter | `src/crb/analyzers/c_cpp/reporter.py` | Entry point for C/C++ analysis, wraps generic analyzer |

### 关键函数

| 函数 | 所在文件 | 功能 |
|------|---------|------|
| `analyze_files()` | `reporter.py` | Orchestrates C/C++ file analysis using generic line-based analyzer |

> 上层结构：[分析器总图](../../../STRUCTURE.md)
