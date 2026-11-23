"""The Settings page's backend: a fixed list of what can be changed, what a value may look like, and a careful `.env` editor.
See docs/settings.md."""

from .catalogue import GROUPS, Setting, catalogue, setting_named
from .envfile import edit_env_text
from .rules import SettingsError, check_value
from .store import EnvSettings, default_env_file, default_settings

__all__ = [
    "EnvSettings", "GROUPS", "Setting", "SettingsError", "catalogue", "check_value", "default_env_file", "default_settings",
    "edit_env_text", "setting_named",
]
