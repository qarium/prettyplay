"""Facade of the prettyplay.config cell: validated project settings."""

from .loader import ConfigurationError, load_config
from .models import BrowserConfig, PrettyConfig

__all__ = ["BrowserConfig", "ConfigurationError", "PrettyConfig", "load_config"]
