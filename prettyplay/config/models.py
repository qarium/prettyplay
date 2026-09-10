"""Validated project settings of prettyplay.

The single source of the immutable configuration part. Secrets (LLM API keys)
never live here: they come only from environment variables.
"""

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, PositiveInt, field_validator

#: The browser matrix the group ``name`` setting is validated against.
_BROWSER_MATRIX = ("chromium", "firefox", "webkit", "chrome", "msedge")


class BrowserConfig(BaseModel):
    """The nested browser group of the project settings.

    Every field has an empty or neutral default so the group validates before
    a ``[tool.prettyplay.browser]`` section exists; ``load_config`` fills it.

    Attributes:
        name: browser of the {chromium, firefox, webkit, chrome, msedge} set;
            chrome and msedge launch the locally installed browser through the
            driver channel mechanism; default chromium; empty means unset in
            the programmatic overlay — ``load_config`` rejects an empty name
            arriving from the file or env layer.
        screen: the single size setting; empty — the Playwright default; WxH —
            a fixed viewport; fullscreen — the maximized window of a local
            headed launch, a fixed 1920x1080 elsewhere; any other value — a
            Playwright device name applied as the full descriptor. Validated
            at format level only: a WxH-shaped value must carry positive
            integers; every other value — including fullscreen and device
            names — passes through unresolved, because the device registry
            belongs to the running Playwright, never to the config.
        headless: run the browser without a visible window of a local launch;
            default True; ignored on a remote connect.
        endpoint: ws endpoint of a remote browser; empty means the local
            launch.
    """

    model_config = ConfigDict(kw_only=True, extra="forbid")

    name: str = "chromium"
    screen: str = ""
    headless: bool = True
    endpoint: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Check that a non-empty name belongs to the browser matrix.

        Args:
            value: the raw name setting; empty means unset in the programmatic
                overlay and passes through — ``load_config`` rejects an empty
                name arriving from the file or env layer.

        Returns:
            The unchanged name when empty or inside the matrix.

        Raises:
            ValueError: when a non-empty name is outside the matrix.
        """
        if value and value not in _BROWSER_MATRIX:
            raise ValueError("must be one of: chromium, firefox, webkit, chrome, msedge")

        return value

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint(cls, value: str) -> str:
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

    @field_validator("screen")
    @classmethod
    def _validate_screen(cls, value: str) -> str:
        """Check the format of a WxH-shaped screen value; pass everything else through.

        Args:
            value: the raw screen setting; empty, fullscreen and device names
                stay unresolved by design.

        Returns:
            The unchanged screen value.

        Raises:
            ValueError: when a WxH-shaped value carries a non-positive
                width or height.
        """
        if not value:
            return value

        match = re.fullmatch(r"(\d+)x(\d+)", value)
        if match is None:
            return value  # fullscreen, device names — the driver resolves them

        width, height = int(match.group(1)), int(match.group(2))
        if width <= 0 or height <= 0:
            raise ValueError("must be positive integers in WxH form")

        return value


class Config(BaseModel):
    """Validated project settings loaded from ``[tool.prettyplay]``.

    Every field has an empty default so the model can be constructed before a
    pyproject.toml section exists; ``load_config`` fills and resolves it.

    Attributes:
        provider: the LLM provider of the {openai, anthropic} set; default openai.
        browser: the nested browser group — a :class:`BrowserConfig` with the
            engine, the screen mode, the window visibility and the remote
            endpoint.
        model: main LLM model name.
        generation_model: optional generation override; empty falls back to ``model``.
        classification_model: optional classification override; empty falls back to ``model``.
        base_url: optional custom LLM API endpoint.
        cache_root: cache root; empty means the default resolved at load.
        generation_prompt: user instructions for generation requests; non-empty
            renders a separate USER INSTRUCTIONS block in generation and
            regeneration requests; empty means no block.
        classification_prompt: user instructions for classification requests;
            non-empty renders a separate USER INSTRUCTIONS block in
            classification requests only; takes no part in the step address;
            empty means no block.
        strict: replay-only mode; True — cached code executes honestly and
            nothing is ever (re)generated; default False.
        generation_attempts: generation attempt budget per step per test; default 3.
        healing_attempts: healing attempt budget per step per test; default 2.
        send_screenshots: whether screenshots are attached to LLM requests.
    """

    model_config = ConfigDict(kw_only=True, extra="forbid")

    provider: Literal["openai", "anthropic"] = "openai"
    browser: BrowserConfig = BrowserConfig()
    model: str = ""
    generation_model: str = ""
    classification_model: str = ""
    base_url: str = ""
    cache_root: str = ""
    generation_prompt: str = ""
    classification_prompt: str = ""
    strict: bool = False
    generation_attempts: PositiveInt = 3
    healing_attempts: PositiveInt = 2
    send_screenshots: bool = False

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
