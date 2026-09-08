"""The openai SDK implementation of the LlmProvider port."""

from ..config import Config
from .provider import LlmProvider


class OpenAiProvider(LlmProvider):
    """The LlmProvider implementation served by the openai SDK.

    Full parity with :class:`AnthropicProvider`: the same operations, the
    same inputs, the same output shapes. The constructor reads no
    environment and constructs no client; the SDK client is created lazily
    on the first request, so the library starts without LLM credentials.
    """

    def __init__(self, config: Config) -> None:
        """Keep the config; the SDK client stays unconstructed until the first request.

        Args:
            config: project settings; the effective models and the optional
                base_url endpoint override come from it.
        """
        self._config = config
        self._client: object | None = None
