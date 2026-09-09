"""Facade of the prettyplay.config cell: validated project settings."""

from .loader import ConfigurationError, load_config
from .models import Config

__all__ = ["Config", "ConfigurationError", "load_config"]
