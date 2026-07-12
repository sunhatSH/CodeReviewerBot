# Config Module

## 结构图

```mermaid
graph TD
    CONFIG["Config Module<br/>src/crb/config/"] --> SETTINGS["settings.py<br/>Dataclass Definitions"]
    CONFIG --> CLI["CLI Module<br/>../../cli/structure.md"]
    SETTINGS --> APP["AppConfig<br/>Top-level config"]
    SETTINGS --> LLMCFG["LLMConfig<br/>LLM settings"]
    SETTINGS --> PYANAL["PythonAnalyzerConfig<br/>Python analyzer settings"]
    SETTINGS --> COMPLEX["ComplexityThresholds<br/>Complexity limits"]
    SETTINGS --> RETRY["RetryThresholds<br/>Retry detection limits"]
    LLMCFG --> ENV["Environment Variables<br/>CRB_LLM_*"]
    click CONFIG "../../src/crb/config/" "Config module directory"
    click SETTINGS "../../src/crb/config/settings.py" "Settings dataclasses"
    click CLI "../../cli/structure.md" "CLI module structure"
    click APP "../../src/crb/config/settings.py" "AppConfig class"
    click LLMCFG "../../src/crb/config/settings.py" "LLMConfig class"
    click PYANAL "../../src/crb/config/settings.py" "PythonAnalyzerConfig class"
    click COMPLEX "../../src/crb/config/settings.py" "ComplexityThresholds class"
    click RETRY "../../src/crb/config/settings.py" "RetryThresholds class"
    click ENV "../../src/crb/config/settings.py" "Environment variable config"
```

## 文件树

| 节点 | 路径 | 功能 |
|------|------|------|
| settings.py | `src/crb/config/settings.py` | 定义所有配置数据类，支持环境变量读取 |

### 关键函数

| 函数 | 所在文件 | 功能 |
|------|---------|------|
| `ComplexityThresholds` | `settings.py` | 复杂度阈值数据类（行数、嵌套深度等） |
| `RetryThresholds` | `settings.py` | 重试检测阈值数据类 |
| `PythonAnalyzerConfig` | `settings.py` | Python分析器配置（包含复杂度与重试阈值） |
| `LLMConfig` | `settings.py` | LLM配置（从环境变量读取URL、Key、Model） |
| `AppConfig` | `settings.py` | 顶层应用配置（包含LLM和Python分析器配置） |

> 上层结构：[项目总图](../../STRUCTURE.md)
