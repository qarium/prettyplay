"""Facade of the prettyplay.config cell: validated project settings."""

from .loader import ConfigurationError, adopt_config, load_config
from .models import BrowserConfig, PrettyConfig

__all__ = ["BrowserConfig", "ConfigurationError", "PrettyConfig", "adopt_config", "load_config"]
