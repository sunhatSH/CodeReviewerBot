# CodeReviewerBot

基于 AI 的代码审查助手，支持 **Python、C/C++、Go、Rust** 四种语言的代码审查。

## 快速使用

```bash
# 审查源文件（自动检测语言）
crb review src/main.py

# 指定语言
crb review --lang python src/

# 输出中文报告（默认）
crb review --lang python src/ --output-lang ch

# 英文报告
crb review --lang python src/ --output-lang en

# 双语报告
crb review --lang python src/ --output-lang ch_en

# JSON 格式输出
crb review --lang python src/ -o json

# 自定义排序
crb review --lang python src/ --sort critical-first
```

## 安装

### 通过 pip 本地安装

```bash
git clone https://github.com/sunhatSH/CodeReviewerBot.git
cd CodeReviewerBot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 直接下载二进制

从 [Releases](https://github.com/sunhatSH/CodeReviewerBot/releases) 下载对应平台的二进制文件。

## LLM 配置

代码审查需要配置 LLM API（OpenAI 兼容格式）：

```bash
export CRB_LLM_API_URL="https://api.openai.com/v1"
export CRB_LLM_API_KEY="sk-..."
export CRB_LLM_MODEL="gpt-4o"       # 可选，默认 gpt-4o
```

配置后可用 `crb doctor` 验证连接。

## 命令

| 命令 | 功能 |
|------|------|
| `crb review <paths>` | 审查源代码 |
| `crb review --lang python <paths>` | 指定语言审查 |
| `crb list-langs` | 列出支持的语言 |
| `crb list-sort-presets` | 列出排序预设 |
| `crb doctor` | 诊断 LLM 配置 |

### review 选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--lang` / `-l` | 自动检测 | 语言：python, c_cpp, go, rust |
| `--sort` | `default` | 排序策略：default, severity-up, critical-first |
| `-o` / `--output` | `markdown` | 输出格式：markdown, json |
| `--report-dir` | `report` | 报告输出目录 |
| `--output-lang` | `ch` | 报告语言：ch, en, ch_en |

## 支持的语言

| 语言 | 分析方式 | 状态 |
|------|---------|------|
| Python | AST 深度分析（复杂度、重试检测、风格检查、第三方库建议） | ✅ 已实现 |
| C/C++ | 基于行的估算分析 | ✅ 已实现 |
| Go | 基于行的估算分析 | ✅ 已实现 |
| Rust | 基于行的估算分析 | ✅ 已实现 |

## 配置

创建 `config.yaml`（参考 `config.yaml.example`）：

```yaml
REPORT_DIR: "report"

PYTHON_ANALYZER:
  COMPLEXITY:
    CYCLOMATIC_THRESHOLD: 10
    FUNCTION_LINES_THRESHOLD: 50
    CLASS_LINES_THRESHOLD: 200
    NESTING_DEPTH_THRESHOLD: 4
  RETRY:
    MAX_RETRIES: 3
  IGNORE_DECORATORS:
    - "complex_func"
  STYLE_ENABLED: true

LLM:
  API_URL: "https://api.openai.com/v1"
  API_KEY: "<YOUR_API_KEY>"
  MODEL: "gpt-4o"
```

> 环境变量 `CRB_LLM_*` 会覆盖配置文件中对应的值。

### @complex_func 装饰器

对于有意设计的复杂函数/类，可通过 `@complex_func` 装饰器消除复杂度警告：

```python
@complex_func
def intentionally_complex_function():
    # 这个函数不会触发复杂度警告
    ...
```

## 报告格式

审查报告包含：

1. **项目结构** — 文件树，精确到类/函数级
2. **Issues** — 按严重程度排序（Blocker → Critical → Major）
3. **Style Issues** — 代码风格问题，统一放在末尾

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 审查自身代码
crb review src/crb/
```

## 文档

- [项目结构](docs/structure.md) — 模块关系总览
- [CLI 模块](docs/cli/structure.md) — 命令行接口
- [配置模块](docs/config/structure.md) — 配置项说明
- [报告模型](docs/report/structure.md) — 数据模型与本地化
- [LLM 客户端](docs/llm/structure.md) — LLM 集成
- [分析器文档](docs/analyzers/generic/structure.md) — 各语言分析器详细说明

## 文档生成

```bash
# 生成缺失的模块文档
python scripts/docs_gen_agent.py

# 重新生成所有文档
python scripts/docs_gen_agent.py --all

# 稳定性测试（生成 5 次并对比）
python scripts/test_docs_stability.py
```

## 许可证

MIT
