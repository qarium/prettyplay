"""Validated project settings of prettyplay.

The single source of the immutable configuration part. Secrets (LLM API keys)
never live here: they come only from environment variables.
"""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, PositiveInt, field_validator


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
        generation_prompt: user instructions for generation requests; non-empty
            renders a separate USER INSTRUCTIONS block in generation and
            regeneration requests; empty means no block.
        browser_endpoint: ws endpoint of a remote browser; empty means the local
            launch; on a remote connect headless is ignored.
        generation_attempts: generation attempt budget per step per test; default 3.
        healing_attempts: healing attempt budget per step per test; default 2.
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
    generation_prompt: str = ""
    browser_endpoint: str = ""
    generation_attempts: PositiveInt = 3
    healing_attempts: PositiveInt = 2
    send_screenshots: bool = False
    headless: bool = True

    @field_validator("browser_endpoint")
    @classmethod
    def _validate_browser_endpoint(cls, value: str) -> str:
        """Check that a non-empty endpoint is a ws/wss URL.

        Args:
            value: the raw endpoint setting; empty means the local launch.

        Returns:
            The unchanged endpoint when empty or a valid ws/wss URL.

        Raises:
            ValueError: when a non-empty endpoint is not a ws/wss URL.
        """
        if not value:
            return value

        parsed = urlparse(value)

        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            raise ValueError("must be a valid ws/wss URL")

        return value

    @property
    def effective_generation_model(self) -> str:
        """Return generation_model when non-empty, otherwise model."""
        return self.generation_model if self.generation_model else self.model

    @property
    def effective_classification_model(self) -> str:
        """Return classification_model when non-empty, otherwise model."""
        return self.classification_model if self.classification_model else self.model


#: The public name of ``Config``: the integrator-facing settings model.
PrettyConfig = Config
