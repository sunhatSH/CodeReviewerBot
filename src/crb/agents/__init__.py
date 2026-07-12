"""Base agent class with LLM access."""
from __future__ import annotations

from crb.config.settings import AppConfig, LLMConfig
from crb.llm.client import LLMError, chat


class BaseAgent:
    """Base class for LLM-powered agents in the review pipeline.

    Provides access to the configured LLM client and common utilities.
    """

    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig()
        self.llm = self.config.llm

    def is_llm_available(self) -> bool:
        """Check if LLM is configured and usable."""
        return self.llm.is_valid()

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt to the LLM and return the response.

        Raises:
            LLMError: If LLM is not configured or the call fails.
        """
        return chat(self.llm, system_prompt, user_prompt, temperature)
