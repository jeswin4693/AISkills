"""The guide for a repository in the web builder: its README and docs, one model call, and the checks that decide what is drawn (docs/how-it-works.md).

One request and nothing is saved: a guide is a single model call, so it needs no run row or migration, and asking again asks the model again.
It reads a folder (or a downloaded copy of a GitHub repository) on this computer, so it is off in the hosted version like every route that does.
A repository with no README or docs gets its own answer before any model is asked, so that case needs no key.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..graph.build import build_graph
from ..guide.docs import read_docs
from ..guide.pipeline import build_guide, no_docs
from ..providers import LLMProvider, ProviderError
from .errors import BadRequest, UpstreamError
from .provider import env_provider
from .repository import clean_focus, display_name, read_failure, resolve_repo, source_of, source_view


def guide_repo(path: object, focus: object = None, provider_factory: Callable[[], LLMProvider] = env_provider) -> dict[str, Any]:
    repo = resolve_repo(path)  # a link is downloaded here, before any model is asked
    if repo.snapshot is not None and repo.snapshot.docs is None:
        repo = resolve_repo(path, fresh=True)  # a copy made before documents were kept has none: download it again
    focus_text = clean_focus(focus)
    name = display_name(source_of(repo))
    docs = read_docs(repo.folder, focus_text)
    if not docs.files:
        return {**no_docs(name, docs), "source": source_view(repo), "focus": focus_text}
    try:
        provider = provider_factory()  # a missing key stops here, before the graph is built
    except ProviderError as exc:
        raise UpstreamError(str(exc)) from exc
    try:
        g = build_graph(repo.folder, focus=focus_text, with_history=False)
    except (OSError, ValueError) as exc:
        raise BadRequest(read_failure(exc)) from exc
    try:
        answer = build_guide(g, docs, provider, name)
    except ProviderError as exc:  # no quota, an unreachable model, an answer that never fitted the schema: said in the model's own words
        raise UpstreamError(str(exc)) from exc
    return {**answer, "source": source_view(repo), "focus": focus_text}
