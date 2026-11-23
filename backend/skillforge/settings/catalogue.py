"""What the Settings page may change: a fixed list, written here and nowhere else.

The page must never become a way to write any line into any file, so a name that is not on this list is refused. The list holds
the model, one key per provider, the custom address, backup models, a model for one kind of work, the escalation model, four limits
and the cache switch. Hosted-mode options (`SKILLFORGE_MODE`, the access token, the data folder) are deliberately not here: they
belong to whoever runs the server, and are never written from a web page.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..providers.factory import key_variables

GROUPS: list[dict] = [
    {"key": "model", "label": "Your model", "advanced": False,
     "help": "The model that does the work. Pick a provider, a model name your key can use, and add that provider's key below."},
    {"key": "keys", "label": "Keys", "advanced": False,
     "help": "One key for each provider you use. A key is saved in the .env file on this computer, is never shown again, "
             "and is sent only to its own provider."},
    {"key": "backups", "label": "Backup models", "advanced": False,
     "help": "Asked in order when the first model is rate limited, out of quota or not reachable. Each one needs its provider's key above."},
    {"key": "work", "label": "A different model for one kind of work", "advanced": True,
     "help": "Leave all of these empty and one model does everything. A kind of work that names another provider needs that provider's key."},
    {"key": "limits", "label": "Limits", "advanced": True,
     "help": "Optional caps. Empty means no cap."},
]

PROVIDER_LABELS = {
    "gemini": "Google Gemini", "openai": "OpenAI", "groq": "Groq", "openrouter": "OpenRouter", "mistral": "Mistral",
    "custom": "Custom (OpenAI-compatible)", "anthropic": "Anthropic (Claude)",
}

# the kinds of work, in plain words (docs/ai-engine.md)
WORK = {
    "FAST": "reading your words",
    "DESIGN": "writing a skill",
    "CODE": "writing scripts",
    "ACTOR": "running a skill's tests",
    "ESCALATION": "a second try when a design still fails its checks",
}  # a test keeps these names equal to the engine's tiers (ai.Tier) plus ESCALATION


@dataclass(frozen=True)
class Setting:
    name: str
    group: str
    label: str
    help: str
    kind: str  # secret | choice | text | url | number | flag
    provider: str = ""  # for a key: the provider it belongs to
    maximum: float = 0.0  # for a number
    integer: bool = False  # for a number


def _build() -> tuple[Setting, ...]:
    found: list[Setting] = [
        Setting("LLM_PROVIDER", "model", "Provider", "Who runs the model.", "choice"),
        Setting("LLM_MODEL", "model", "Model", "A model name your key can use. Models get retired while still listed, so use "
                "'Test my models' after you save.", "text"),
    ]
    for provider, variable in sorted(key_variables().items()):
        label = PROVIDER_LABELS.get(provider, provider.title())
        found.append(Setting(variable, "keys", f"{label} key", f"The key for {label}. Never shown again once saved.", "secret", provider=provider))
    found.append(Setting("LLM_BASE_URL", "keys", "Custom endpoint address",
                         "Only for the Custom provider: the address of an OpenAI-compatible API, for example http://localhost:1234/v1.", "url",
                         provider="custom"))
    found.append(Setting("LLM_FALLBACKS", "backups", "Backup models", "provider:model, separated by commas, for example "
                         "groq:openai/gpt-oss-20b,gemini:gemini-2.5-flash.", "text"))
    for prefix, what in WORK.items():
        found.append(Setting(f"LLM_{prefix}_PROVIDER", "work", f"Provider for {what}", "Leave empty to use your main provider.", "choice"))
        found.append(Setting(f"LLM_{prefix}_MODEL", "work", f"Model for {what}", "Leave empty to use your main model.", "text"))
    found += [
        Setting("LLM_TIMEOUT_S", "limits", "Seconds to wait for one answer", "Default 90 (180 when writing scripts).", "number", maximum=3600),
        Setting("LLM_MAX_CALLS", "limits", "Most model calls in one run", "Stops a run after this many attempts. Helps a free quota.", "number",
                maximum=100000, integer=True),
        Setting("LLM_MAX_INPUT_TOKENS", "limits", "Most words sent in one request", "A request bigger than this is not sent. Counted in tokens.",
                "number", maximum=10_000_000, integer=True),
        Setting("SKILLFORGE_LLM_CACHE", "limits", "Remember answers", "Set to 1 so the same request is not paid for twice. "
                "Off by default: a repeat then returns the same answer.", "flag"),
    ]
    return tuple(found)


@lru_cache(maxsize=1)
def _all() -> tuple[Setting, ...]:
    return _build()


def catalogue() -> tuple[Setting, ...]:
    """Every setting the page may change, in the order the page shows them."""
    return _all()


def setting_named(name: object) -> Setting | None:
    """The setting with exactly this name, or None for anything else (case and spaces count)."""
    if not isinstance(name, str):
        return None
    return next((s for s in _all() if s.name == name), None)
