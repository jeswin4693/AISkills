"""The guide: documents -> one model call -> checks by code -> the diagram as plain data.

`build_guide` is the one function the web API and the command line both call. The answer holds no path of the person's: documents are named
relative to the repository, folders likewise.
"""

from __future__ import annotations

from typing import Any

from ..ai.tasks import Task
from ..graph.model import RepoGraph
from ..providers.base import LLMProvider
from ..providers.retry import generate_with_retry
from .docs import DocSet
from .models import LAYERS, GuideDraft
from .prompt import SYSTEM, build_prompt, folder_facts
from .verify import check

NOTES: tuple[str, ...] = (
    "Each quote is in the documents, word for word: code looked it up, and a part or step with a quote that is not there was dropped. "
    "That does not prove the quote is about that part, or that the documents are up to date.",
    "The summaries, the steps' wording, what goes in and out, and the plain-words pictures are the model's own words and are not checked. "
    "\"Folder found\" means the folder the model named exists, not that the part really lives there.",
    "A solid hop means the code really imports that way (the numbers and a few file pairs are shown). Anything else is only what the documents say.",
)


def _answer(status: str, name: str, docs: DocSet, **more: Any) -> dict[str, Any]:
    return {
        "status": status, "name": name, "docs": docs.view(), "docs_skipped": dict(docs.skipped),
        "layers": [{"id": i, "label": label} for i, label in LAYERS], "parts": [], "journeys": [], "dropped": [], "notes": [],
        "provider": "", "model": "", "attempts": 0, **more,
    }


def no_docs(name: str, docs: DocSet) -> dict[str, Any]:
    """The answer for a repository with nothing to read. No model was asked, so no key was needed."""
    return _answer(
        "no_docs", name, docs,
        notes=["This repository has no README or docs that SkillForge can read, so there is nothing to draw from. "
               "The map above still shows how its folders import each other."],
    )


def build_guide(g: RepoGraph, docs: DocSet, provider: LLMProvider, name: str, *, attempts: int = 2) -> dict[str, Any]:
    draft, used = generate_with_retry(provider, GuideDraft, build_prompt(docs, folder_facts(g), name), SYSTEM, attempts, task=Task.GUIDE)
    checked = check(draft, docs, g)
    status = "ok" if len(checked.parts) >= 2 else "thin"
    notes: list[str] = list(NOTES)
    if status == "thin":
        notes.insert(0, "Fewer than two parts could be checked against the documents, so nothing is drawn. The documents may not describe how the project works.")
    elif not checked.journeys:
        notes.insert(0, "No route through the parts could be checked against the documents, so the layers are shown without one.")
    if any(d.truncated for d in docs.files):
        notes.append("A long document was cut before it was read: only its first part was given to the model.")
    if docs.skipped.get("limit"):
        notes.append(f"{docs.skipped['limit']} more document(s) were not read: only the first few are given to the model.")
    return _answer(
        status, name, docs,
        parts=checked.parts if status == "ok" else [], journeys=checked.journeys if status == "ok" else [], dropped=checked.dropped, notes=notes,
        provider=provider.name, model=provider.model, attempts=used,
    )
