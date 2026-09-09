"""Validated project settings of prettyplay.

The single source of the immutable configuration part. Secrets (LLM API keys)
never live here: they come only from environment variables.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, PositiveInt


class Config(BaseModel):
    """Validated project settings loaded from ``[tool.prettyplay]``.

    Every field has an empty default so the model can be constructed before a
    pyproject.toml section exists; ``load_config`` fills and resolves it.

    Attributes:
        provider: the LLM provider of the {openai, anthropic} set; default openai.
        browser: browser of the {chromium, firefox, webkit, chrome, msedge} set;
            chrome and msedge launch the locally installed browser through the
            driver channel mechanism; default chromium.
        model: main LLM model name.
        generation_model: optional generation override; empty falls back to ``model``.
        classification_model: optional classification override; empty falls back to ``model``.
        base_url: optional custom LLM API endpoint.
        cache_root: cache root; empty means the default resolved at load.
        generation_attempts: generation attempt budget per step per run; default 3.
        healing_attempts: healing attempt budget per step per run; default 2.
        send_screenshots: whether screenshots are attached to LLM requests.
        headless: run the browser without a visible window; default True.
    """

    model_config = ConfigDict(kw_only=True)

    provider: Literal["openai", "anthropic"] = "openai"
    browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"] = "chromium"
    model: str = ""
    generation_model: str = ""
    classification_model: str = ""
    base_url: str = ""
    cache_root: str = ""
    generation_attempts: PositiveInt = 3
    healing_attempts: PositiveInt = 2
    send_screenshots: bool = False
    headless: bool = True

    @property
    def effective_generation_model(self) -> str:
        """Return generation_model when non-empty, otherwise model."""
        return self.generation_model if self.generation_model else self.model

    @property
    def effective_classification_model(self) -> str:
        """Return classification_model when non-empty, otherwise model."""
        return self.classification_model if self.classification_model else self.model
