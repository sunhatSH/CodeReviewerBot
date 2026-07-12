# CodeReviewerBot 项目结构

## 总体结构图

```mermaid
graph TD
    CLI["CLI Entry<br/>crb command"] -->|review| PY["Python Analyzer"]
    CLI -->|"config / list-sort-presets"| CFG[Config]
    PY -->|复杂度分析| COMPLEXITY["complexity.py"]
    PY -->|重试检测| RETRY["retry_detector.py"]
    PY -->|风格检查| STYLE["style_checker.py"]
    PY -->|编排报告| REPORTER["reporter.py"]
    Report["report/models.py"] -->|数据模型| PY
    
    click CLI "cli/structure.md" "CLI module structure"
    click PY "analyzers/python/structure.md" "Python analyzer structure"
    click COMPLEXITY "../src/crb/analyzers/python/complexity.py" "Complexity analysis source"
    click RETRY "../src/crb/analyzers/python/retry_detector.py" "Retry detection source"
    click STYLE "../src/crb/analyzers/python/style_checker.py" "Style check source"
    click REPORTER "../src/crb/analyzers/python/reporter.py" "Reporter source"
    click Report "../src/crb/report/models.py" "Report models source"
    click CFG "../src/crb/config/settings.py" "Config settings source"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| CLI | `src/crb/cli/main.py` | 命令行入口，review/config 子命令 |
| Python Analyzer | `src/crb/analyzers/python/` | Python 代码审查模块 |
| complexity.py | `src/crb/analyzers/python/complexity.py` | 圈复杂度 & 函数行数分析 |
| retry_detector.py | `src/crb/analyzers/python/retry_detector.py` | 错误重试模式检测 |
| style_checker.py | `src/crb/analyzers/python/style_checker.py` | 代码风格检查 |
| reporter.py | `src/crb/analyzers/python/reporter.py` | 审查结果编排 & 报告生成 |
| Report Models | `src/crb/report/models.py` | Finding/Report 数据模型，分级排序 |
| Config | `src/crb/config/settings.py` | 可配置阈值和参数 |

---

> 下层结构文档：
> - [CLI 模块](cli/structure.md)
> - [配置模块](config/structure.md)
> - [报告模型](report/structure.md)
> - [LLM 客户端](llm/structure.md)
> - [通用分析器](analyzers/generic/structure.md)
> - [Python 分析器](analyzers/python/structure.md)
> - [C/C++ 分析器](analyzers/c_cpp/structure.md)
> - [Go 分析器](analyzers/go/structure.md)
> - [Rust 分析器](analyzers/rust/structure.md)
