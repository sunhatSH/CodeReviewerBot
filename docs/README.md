# CodeReviewerBot 文档

## 文档树

```
docs/
├── README.md                    # ← 本页，文档入口
├── 需求文档.md                   # 项目需求规格
├── structure.md                 # 项目结构总览（Mermaid 图 + 文件树）
├── cli/
│   └── structure.md             # CLI 模块（click 命令、选项）
├── config/
│   └── structure.md             # 配置模块（AppConfig、LLMConfig、阈值）
├── report/
│   └── structure.md             # 报告模型（Finding、ReviewReport、Severity）
├── llm/
│   └── structure.md             # LLM 客户端（OpenAI 兼容）
└── analyzers/
    ├── generic/
    │   └── structure.md         # 通用行级分析器
    ├── python/
    │   └── structure.md         # Python AST 分析器
    ├── c_cpp/
    │   └── structure.md         # C/C++ 分析器
    ├── go/
    │   └── structure.md         # Go 分析器
    └── rust/
        └── structure.md         # Rust 分析器
```

## 阅读建议

| 目标 | 文档 |
|------|------|
| 了解整体架构 | [项目结构总览](structure.md) |
| 了解 CLI 用法 | [CLI 模块](cli/structure.md) |
| 配置说明 | [配置模块](config/structure.md) 或 `config.yaml.example` |
| 报告数据模型 | [报告模型](report/structure.md) |
| LLM 集成 | [LLM 客户端](llm/structure.md) |
| Python 审查逻辑 | [Python 分析器](analyzers/python/structure.md) |
| C/C++/Go/Rust 审查逻辑 | [通用分析器](analyzers/generic/structure.md) |
| 项目需求 | [需求文档](需求文档.md) |

## LLM 配置

```bash
export CRB_LLM_API_URL="https://api.deepseek.com"
export CRB_LLM_API_KEY="sk-..."
export CRB_LLM_MODEL="deepseek-chat"
```

用 `crb doctor` 验证连接。

## 文档生成

```bash
# 生成缺失文档
python scripts/docs_gen_agent.py

# 生成全部文档到指定目录
python scripts/docs_gen_agent.py --all --output-dir /tmp/docs_out

# 稳定性测试
python scripts/test_docs_stability.py
```
