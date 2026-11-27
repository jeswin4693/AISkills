"""The Task Plan over HTTP (slice AM): the command line's `plan` (step C1) for the web page.

The plan itself is made by `conductor.make_plan`, unchanged. This only does what the command does around it: finds the repository (a folder, or a
public GitHub link downloaded into a copy), gets a model unless the person asked for none, turns what goes wrong into a message the person can act on,
and takes the person's own folder path out of what comes back. Nothing is saved, and nothing in the repository is changed or run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..conductor import PlanError, make_plan, process, render_markdown
from ..conductor.plan import check_task
from ..providers import LLMProvider, ProviderError
from .errors import BadRequest, UpstreamError
from .provider import env_provider
from .repository import display_name, read_failure, resolve_repo, source_of, source_view

# A copy of a GitHub repository holds source files and README and doc files only, so the plan must say its rule files were not read (the command says
# the same: `plan --repo LINK`).
GITHUB_COPY_NOTE = "CLAUDE.md and AGENTS.md are not downloaded, so the rules they hold are not read."


def plan_task(
    task: object, repo: object = None, *, no_ai: bool = False, kind: str | None = None, tier: int | None = None, budget: int | None = None,
    sensitive: Sequence[str] = (), provider_factory: Callable[[], LLMProvider] = env_provider,
) -> dict[str, Any]:
    """A Task Plan as the page shows it: the plan (as `plan --json` gives it), `markdown` (as `plan` prints it) and `source` (where a link came from)."""
    try:
        words = check_task(task if isinstance(task, str) else "")  # a one-word task is refused before a download or a model
    except PlanError as exc:
        raise BadRequest(str(exc)) from exc
    text = repo.strip() if isinstance(repo, str) else ""
    found = resolve_repo(text) if text else None  # a bad path is a BadRequest; a link is downloaded here, before any model is asked
    provider = None
    if not no_ai:
        try:
            provider = provider_factory()  # a missing key stops here, before the graph is built
        except ProviderError as exc:
            raise UpstreamError(str(exc)) from exc
    try:
        plan = make_plan(
            words, provider=provider, repo=found.folder if found else None, task_type=kind, tier=tier, budget=budget, sensitive=tuple(sensitive),
        )
    except PlanError as exc:
        raise BadRequest(str(exc)) from exc
    except ProviderError as exc:  # no quota, an unreachable model, an answer that never fitted the schema: said in the model's own words
        raise UpstreamError(str(exc)) from exc
    except OSError as exc:
        raise BadRequest(read_failure(exc)) from exc
    if found is not None:  # the plan names a folder by its own name, and a download's folder is a hash: a page shows `owner/repo`
        update: dict[str, Any] = {"repo": display_name(source_of(found))}
        if found.link is not None:
            update["notes"] = [*plan.notes, GITHUB_COPY_NOTE]
        plan = plan.model_copy(update=update)
    return {
        **plan.model_dump(), "tier_name": process.TIER_NAMES[plan.tier.tier], "markdown": render_markdown(plan),
        "source": source_view(found) if found is not None else {"kind": "none"},
    }
