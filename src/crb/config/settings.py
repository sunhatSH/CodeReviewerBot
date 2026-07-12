"""Configuration settings for the code reviewer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ComplexityThresholds:
    cyclomatic: int = 10
    function_lines: int = 50
    class_lines: int = 200
    nesting_depth: int = 4


@dataclass
class RetryThresholds:
    max_retries: int = 3


@dataclass
class PythonAnalyzerConfig:
    complexity: ComplexityThresholds = field(default_factory=ComplexityThresholds)
    retry: RetryThresholds = field(default_factory=RetryThresholds)
    ignore_decorators: list[str] = field(
        default_factory=lambda: ["complex_func"]
    )
    style_enabled: bool = True


@dataclass
class LLMConfig:
    """LLM provider configuration.

    Reads from environment variables by default.
    - CRB_LLM_API_URL: OpenAI-compatible API endpoint (default: https://api.openai.com/v1)
    - CRB_LLM_API_KEY: API key (required)
    - CRB_LLM_MODEL: Model name (default: gpt-4o)
    - CRB_LLM_MAX_TOKENS: Max output tokens (default: 4096)
    """
    api_url: str = ""
    api_key: str = ""
    model: str = ""

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            api_url=os.environ.get("CRB_LLM_API_URL", ""),
            api_key=os.environ.get("CRB_LLM_API_KEY", ""),
            model=os.environ.get("CRB_LLM_MODEL", ""),
        )

    def is_valid(self) -> bool:
        return bool(self.api_url and self.api_key)


@dataclass
class AppConfig:
    python: PythonAnalyzerConfig = field(default_factory=PythonAnalyzerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    report_dir: str = "report"
    sort_order: list[str] = field(
        default_factory=lambda: ["Blocker", "Critical", "Major"]
    )
