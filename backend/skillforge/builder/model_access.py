"""Which model a person's calls use, and whether they may use it now (slice AI, docs/per-person-keys.md).

Every place that needs a model for somebody asks `provider_for(user_id)`; nothing else decides:

- **The owner** (local use, the access token, a Bearer header) always gets the server's model, and is never limited.
- **A person with a model of their own** gets a provider built from their own key (opened here, handed to the builder for that one provider, never kept anywhere else).
  Their calls are recorded as `key_source = "own"` and never touch the server's allowance.
- **A person with none** gets the server's model only if the host shares it (`SKILLFORGE_SHARED_KEY_CALLS_PER_DAY`), behind a gate that counts their
  `server` calls of today (UTC) before every attempt, so runs started together cannot each take the whole allowance. With sharing off, the server's model is NOT
  borrowed: they are told to add their own key.

Every provider returned gets the usage recorder attached, so a suggestion run or a Testing Lab run (which have no builder session) leaves rows under the right person.
A key is never returned by anything here, not even its end.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..ai import AIService, UsageRecord, service_from_env
from ..ai.doctor import check_models
from ..db import LOCAL_USER_ID, Database, ModelCall
from ..db.user_models import ModelStore, StoredModel
from ..providers import LLMProvider, ProviderError
from ..providers.factory import key_variables
from ..settings import PERSON_PROVIDERS, SettingsError, check_person_model
from .keybox import KeyBox, KeyBoxError
from .provider import provider_status
from .usage import DbUsageRecorder

NO_KEY = (
    "This server's model is not shared with you. Add your own model key in Settings (My model), then try again."
)
OWNER_NOTE = "You are the owner of this server: its own model settings are used, and nothing here applies to you."
INFLIGHT_SECONDS = 600.0  # an attempt that never wrote its usage row (it died) stops holding a slot after this long: longer than any model call is allowed to take


_MODEL_HINT = re.compile(r"Check LLM_MODEL in \.env\.?")
_KEY_HINT = re.compile(r"Check [A-Z][A-Z0-9_]* in \.env\.?")


def _for_a_person(message: str) -> str:
    """A provider's error says "Check GROQ_API_KEY in .env": advice for the owner. A person's own key is fixed under Settings, My model."""
    message = _MODEL_HINT.sub("Check the model name under Settings, My model.", message)
    return _KEY_HINT.sub("Check your key under Settings, My model.", message)


class ModelAccessError(Exception):
    """A request about a person's model that cannot be done (the owner has no personal model; this server cannot keep keys). The message is for the person."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ModelOptions:
    keybox: KeyBox | None = None  # None: people cannot save keys here (local use, a server with no accounts)
    shared_calls_per_day: int = 0  # 0: the server's model is the owner's alone
    build: Callable[[Mapping[str, str]], LLMProvider] = service_from_env  # what turns {LLM_PROVIDER, LLM_MODEL, <key>} into a provider; tests replace it
    clock: Callable[[], datetime] = utc_now  # tests replace it to cross midnight


class _GivesBackASlot(DbUsageRecorder):
    """A usage recorder that, once an attempt's row is written, gives back the in-flight slot the allowance gate took for it."""

    def __init__(self, *args, release: Callable[[], None], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._release = release

    def record(self, rec: UsageRecord) -> None:
        try:
            super().record(rec)
        finally:
            if rec.status != "cache":  # a cache hit never took a slot: it never reached a model
                self._release()


class ModelAccess:
    def __init__(self, db: Database, server_provider: Callable[[], LLMProvider], options: ModelOptions = ModelOptions()) -> None:
        self.db = db
        self.server_provider = server_provider  # the owner's model: the server's own settings (builder.provider.env_provider)
        self.options = options
        self.store = ModelStore(db)
        self._lock = threading.Lock()
        self._inflight: dict[str, list[float]] = {}  # per person: when each attempt that has passed the gate but not yet written its row began

    # ---- the model for one person ------------------------------------------------------------------------------

    def provider_for(self, user_id: str, *, session_id: str | None = None, job_id: int | None = None) -> LLMProvider:
        """The model this person's call should use, with the usage recorder attached. Raises ProviderError (retryable: adding a key or waiting helps)."""
        if user_id == LOCAL_USER_ID:
            return self._recorded(self.server_provider(), user_id, session_id, job_id, "server", None)
        stored = self.store.get(user_id)
        if stored is not None:
            return self._recorded(self._own_provider(user_id, stored), user_id, session_id, job_id, "own", None)
        if self.options.shared_calls_per_day > 0:
            return self._recorded(self.server_provider(), user_id, session_id, job_id, "server", self._gate(user_id))
        raise ProviderError(NO_KEY, kind="auth", retryable=True)

    def _recorded(self, provider: LLMProvider, user_id: str, session_id: str | None, job_id: int | None, source: str, gate: Callable[[], None] | None) -> LLMProvider:
        if gate is not None and not isinstance(provider, AIService):
            provider = AIService.single(provider)  # a bare provider has no place to put a gate
        if isinstance(provider, AIService):
            if gate is None:
                recorder: DbUsageRecorder = DbUsageRecorder(self.db, session_id, job_id, user_id, source)
            else:
                recorder = _GivesBackASlot(self.db, session_id, job_id, user_id, source, release=lambda: self._release(user_id))
            return provider.with_recorder(recorder, gate=gate)
        return provider

    def _own_provider(self, user_id: str, stored: StoredModel) -> LLMProvider:
        key_variable = key_variables().get(stored.provider)
        if key_variable is None:
            raise ProviderError("The provider you saved is no longer supported. Choose your model again in Settings.", kind="auth", retryable=True)
        key = self._open(user_id, stored)
        # ONLY these three entries: nothing of the server's environment (its keys, its tiers, its backups) comes along into a person's provider.
        service = self.options.build({"LLM_PROVIDER": stored.provider, "LLM_MODEL": stored.model, key_variable: key})
        if isinstance(service, AIService):
            service.reword = _for_a_person  # its errors say "Settings, My model", not "the .env file" (a person on a hosted server has none)
        return service

    def _open(self, user_id: str, stored: StoredModel) -> str:
        if self.options.keybox is None:
            raise ProviderError("This server cannot open saved keys. Ask the person who runs it.", kind="auth", retryable=False)
        try:
            return self.options.keybox.open(user_id, stored.key_ciphertext, stored.key_nonce)
        except KeyBoxError as exc:
            raise ProviderError(str(exc), kind="auth", retryable=True) from None

    def _readable(self, user_id: str, stored: StoredModel) -> bool:
        try:
            self._open(user_id, stored)
            return True
        except ProviderError:
            return False

    # ---- the allowance -----------------------------------------------------------------------------------------

    def used_today(self, user_id: str, source: str = "server") -> int:
        """Attempts this person made on the server's model since 00:00 UTC (`source` "own": on their own key, which never counts toward an allowance and is
        only shown to the owner). Their own-key attempts, other people's and yesterday's are not counted."""
        midnight = self.options.clock().astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00")  # created_at is ISO text in UTC: it sorts as text
        with self.db.session() as s:
            return s.execute(
                select(func.count()).select_from(ModelCall).where(
                    ModelCall.user_id == user_id, ModelCall.key_source == source, ModelCall.created_at >= midnight,
                    ModelCall.status != "cache",  # an answer served from the cache never reached a model: it costs nothing
                )
            ).scalar_one()

    def _gate(self, user_id: str) -> Callable[[], None]:
        limit = self.options.shared_calls_per_day

        def gate() -> None:
            # Runs before every attempt. Rows written + attempts still in flight: the count of rows alone would let six runs that start at the same instant
            # all see "none used" and all go. A slot is taken here and given back when the attempt's row is written (see _GivesBackASlot).
            with self._lock:
                now = time.monotonic()
                held = [t for t in self._inflight.get(user_id, []) if now - t < INFLIGHT_SECONDS]
                if self.used_today(user_id) + len(held) >= limit:
                    self._inflight[user_id] = held
                    raise ProviderError(
                        f"You have used today's allowance of {limit} model calls on this server's model (it resets at midnight UTC). "
                        "Add your own model key in Settings to go on.", kind="allowance", retryable=True,
                    )
                held.append(now)
                self._inflight[user_id] = held

        return gate

    def _release(self, user_id: str) -> None:
        with self._lock:
            held = self._inflight.get(user_id)
            if held:
                held.pop(0)

    def _allowance(self, user_id: str) -> dict | None:
        limit = self.options.shared_calls_per_day
        return {"limit": limit, "used": self.used_today(user_id)} if limit > 0 else None

    # ---- what the pages are shown (never a key) ----------------------------------------------------------------

    def my_model(self, user_id: str) -> dict:
        view = {
            "mode": "none", "provider": "", "model": "", "key_saved": False, "key_saved_at": "", "key_readable": True, "allowance": None,
            "providers": list(PERSON_PROVIDERS), "message": "",
        }
        if user_id == LOCAL_USER_ID:
            return {**view, "mode": "owner", "message": OWNER_NOTE}
        stored = self.store.get(user_id)
        if stored is not None:
            readable = self._readable(user_id, stored)
            message = "Your own key is used for everything you start here." if readable else (
                "Your saved key cannot be opened any more (the server's access token changed). Enter your key again."
            )
            return {**view, "mode": "own", "provider": stored.provider, "model": stored.model, "key_saved": True, "key_saved_at": stored.updated_at,
                    "key_readable": readable, "message": message}
        if self.options.shared_calls_per_day > 0:
            limit = self.options.shared_calls_per_day
            return {**view, "mode": "shared", "allowance": self._allowance(user_id),
                    "message": f"You are using this server's model, up to {limit} calls a day. Add your own key to remove that limit."}
        return {**view, "message": NO_KEY}

    def status_for(self, user_id: str) -> dict:
        """What GET /api/provider says for this person: the shape the pages already read, plus where the model comes from."""
        if user_id != LOCAL_USER_ID:
            stored = self.store.get(user_id)
            if stored is not None:
                return {**provider_status(lambda: self._own_provider(user_id, stored)), "source": "own", "allowance": None}
            if self.options.shared_calls_per_day > 0:
                return {**provider_status(self.server_provider), "source": "server", "allowance": self._allowance(user_id)}
            return {
                "configured": False, "provider": "", "model": "", "detail": NO_KEY, "tiers": [], "escalation": None, "capabilities": None,
                "fallbacks": [], "source": "none", "allowance": None,
            }
        return {**provider_status(self.server_provider), "source": "server", "allowance": None}

    # ---- changing it -------------------------------------------------------------------------------------------

    def save(self, user_id: str, provider: str, model: str, key: str) -> dict:
        """Seal and keep this person's model. SettingsError (naming each field, never the key) for what the rules refuse."""
        self._person_only(user_id)
        if self.options.keybox is None:
            raise ModelAccessError("This server cannot keep personal model keys.")
        kept = None  # an empty key box keeps a saved key that can still be opened: changing only the model name must not mean pasting the key again
        if not key.strip():
            stored = self.store.get(user_id)
            if stored is not None and self._readable(user_id, stored):
                kept = stored
        provider, model, key = check_person_model(provider, model, key, keep_key=kept is not None)
        if kept is not None:
            if provider != kept.provider:  # the saved key belongs to another provider
                raise SettingsError([{"name": "key", "message": f"Paste your key for the new provider: the saved key is for {kept.provider}."}])
            self.store.put(user_id, provider, model, kept.key_ciphertext, kept.key_nonce)
            return self.my_model(user_id)
        ciphertext, nonce = self.options.keybox.seal(user_id, key)
        self.store.put(user_id, provider, model, ciphertext, nonce)
        return self.my_model(user_id)

    def remove(self, user_id: str) -> dict:
        self._person_only(user_id)
        self.store.delete(user_id)
        return self.my_model(user_id)

    def test(self, user_id: str) -> dict:
        """One tiny call to this person's OWN model, so they can see the key works. The server's model is never tried for a person."""
        stored = None if user_id == LOCAL_USER_ID else self.store.get(user_id)
        if stored is None:
            detail = OWNER_NOTE if user_id == LOCAL_USER_ID else "You have no key of your own to test. Add one first."
            return {"configured": False, "detail": detail, "checks": []}
        try:
            provider = self._own_provider(user_id, stored)
        except ProviderError as exc:
            return {"configured": False, "detail": str(exc), "checks": []}
        return {"configured": True, "detail": "", "checks": check_models(provider)}

    @staticmethod
    def _person_only(user_id: str) -> None:
        if user_id == LOCAL_USER_ID:
            raise ModelAccessError("The owner's model is set in the server's own settings (the Settings page when run locally, the environment on a host), not here.")
