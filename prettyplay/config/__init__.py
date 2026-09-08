"""Facade of the prettyplay.config cell: validated project settings."""

from .loader import load_config
from .models import Config

__all__ = ["Config", "load_config"]
