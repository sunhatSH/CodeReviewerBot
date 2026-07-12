# 项目结构总览


## Structure Diagram

```mermaid
graph TD
    ___[...]
    CodeReviewerBot[CodeReviewerBot]
    docs[docs (5)]
    scripts[scripts (5)]
    src[src (2)]
    src_codereviewerbot_egg_info[codereviewerbot.egg-info (6)]
    src_crb[crb (2)]
    src_crb_agents[agents (7)]
    src_crb_analyzers[analyzers (5)]
    src_crb_c_src[c_src (2)]
    src_crb_cli[cli (2)]
    src_crb_config[config (1)]
    src_crb_llm[llm (2)]
    src_crb_templates[templates (2)]
    tests[tests (3)]

    CodeReviewerBot --> docs
    CodeReviewerBot --> scripts
    CodeReviewerBot --> src
    CodeReviewerBot --> tests
    src --> src_codereviewerbot_egg_info
    src --> src_crb
    src_crb --> src_crb_agents
    src_crb --> src_crb_analyzers
    src_crb --> src_crb_c_src
    src_crb --> src_crb_cli
    src_crb --> src_crb_config
    src_crb --> src_crb_llm
    src_crb --> src_crb_templates
    src_crb_analyzers --> ___
    src_crb_c_src --> ___
```
## File Tree

```
CodeReviewerBot
├── docs
│   └── README.md, structure_en.md, structure_zh.md, 需求文档.md, 项目进度.md
├── scripts
│   └── build.py, docs_gen_agent.py, structure_en.md, structure_zh.md, test_docs_stability.py
├── src
│   ├── codereviewerbot.egg-info
│   │   └── PKG-INFO, SOURCES.txt, dependency_links.txt, entry_points.txt, requires.txt, top_level.txt
│   ├── crb
│   │   ├── agents
│   │   │   └── __init__.py, commit_organizer_agent.py, doc_consistency_agent.py, fix_agent.py, review_agent.py, semantic_agent.py, structure_agent.py
│   │   ├── analyzers
│   │   │   ├── c_cpp
│   │   │   │   └── __init__.py, reporter.py
│   │   │   ├── generic
│   │   │   │   └── __init__.py, structure_analyzer.py
│   │   │   ├── go
│   │   │   │   └── __init__.py, reporter.py
│   │   │   ├── python
│   │   │   │   └── __init__.py, auth_detector.py, bloat_detector.py, bug_detector.py, comment_detector.py, complexity.py, dead_code_detector.py, dependency_detector.py, design_detector.py, edge_case_detector.py, layered_test_detector.py, multi_agent.py, orphan_detector.py, reporter.py, retry_detector.py, style_checker.py, test_theater_detector.py, third_party_suggester.py
│   │   │   ├── rust
│   │   │   │   └── __init__.py, reporter.py
│   │   │   └── __init__.py, call_chain.py, detector.py, generic.py, secret_detector.py
│   │   ├── c_src
│   │   │   ├── third_party
│   │   │   │   └── json.hpp
│   │   │   └── CMakeLists.txt, static_analyzer.cpp
│   │   ├── cli
│   │   │   └── __init__.py, main.py
│   │   ├── config
│   │   │   └── settings.py
│   │   ├── llm
│   │   │   └── __init__.py, client.py
│   │   ├── templates
│   │   │   └── __init__.py, ci_templates.py
│   │   └── __init__.py, __main__.py
│   └── structure_en.md, structure_zh.md
├── tests
│   └── structure_en.md, structure_zh.md, test_python_analyzer.py
└── LICENSE, README.md, STRUCTURE.md, build_binary.py, build_linux.py, config.yaml.example, crb.spec, crb_test.spec, pyproject.toml, structure-data.json, structure-viewer.html, structure_en.md, structure_zh.md, test_click.spec, test_pyi.spec
```
## Modules

- [docs](docs/structure.md)
- [scripts](scripts/structure.md)
- [src](src/structure.md)
- [tests](tests/structure.md)
