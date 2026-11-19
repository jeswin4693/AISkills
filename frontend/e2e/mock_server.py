"""A real SkillForge API with a scripted fake model, for the browser test (frontend/e2e/run.mjs). Not part of the product.

Everything is real except the model: the database, the library, the checklist, the quote verification, the checks and
the build run exactly as in production. The fake model only answers the two kinds of question the builder asks, and
only fills a checklist item when the person's words really contain it, the way an honest model would.

Markers in the person's words steer the scenarios:
  [model-down]  the model fails once ("unreachable"), then works: the builder shows a retryable failure
  [draft]       the design has no test covering the acceptance criterion, so the skill is a DRAFT
The model counts as "not set up" until the file named by E2E_MODEL_FLAG exists, like a missing .env.
Run with PYTHONPATH set to the backend folder and SKILLFORGE_DATA_DIR set to a throwaway folder.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import uvicorn

from skillforge.api import create_app
from skillforge.build.models import Extraction, IOField, SkillDraft, SkillTest, Slot, Step
from skillforge.builder import Builder, JobRunner
from skillforge.db import Database
from skillforge.library import Library
from skillforge.providers import MockProvider, ProviderError

DELAY = float(os.environ.get("E2E_MODEL_DELAY", "0.8"))  # long enough for the page to be seen "working"
FLAG = Path(os.environ["E2E_MODEL_FLAG"])
DATA = Path(os.environ["SKILLFORGE_DATA_DIR"])
PORT = int(os.environ.get("E2E_API_PORT", "8000"))

# checklist item -> (a phrase of the person's words that fills it, what the fake model records)
ITEMS = {
    "goal": ("counts TODO and FIXME comments", "Count TODO and FIXME comments in a folder"),
    "inputs": ("in a folder", "a folder path"),
    "outputs": ("report of counts per file", "a report of the counts for each file"),
    "constraints": ("never edit any file", "never edit any file"),
    "acceptance_criteria": ("works when it lists every file", "it lists every file with its TODO and FIXME counts"),
    "failure_behavior": ("cannot be read it stops and says so", "stop and say so when the folder cannot be read"),
}
down_once = {"used": False}


def slot(words: str, key: str, marker: str = "") -> Slot:
    phrase, value = ITEMS[key]
    if phrase.lower() not in words.lower():
        return Slot(values=[], quote="")
    return Slot(values=[value + marker], quote=phrase)


def extraction(prompt: str) -> Extraction:
    words = prompt.split("<user_words>")[-1].split("</user_words>")[0]
    if "[model-down]" in words and not down_once["used"]:
        down_once["used"] = True
        raise ProviderError("The model could not be reached (simulated by the test).")
    marker = " [draft]" if "[draft]" in words else ""
    return Extraction(
        kind="skill", goal=slot(words, "goal", marker), inputs=slot(words, "inputs"), outputs=slot(words, "outputs"),
        constraints=slot(words, "constraints"), acceptance_criteria=slot(words, "acceptance_criteria"),
        failure_behavior=slot(words, "failure_behavior"),
    )


def design(prompt: str) -> SkillDraft:
    covers = [] if "[draft]" in prompt else ["AC1"]
    return SkillDraft(
        name="todo-counter-e2e",
        description="Counts TODO and FIXME comments in a folder and reports the counts for each file.",
        triggers=["count TODO comments", "how many FIXMEs are left", "make a tidy-up list"],
        does=["Count TODO and FIXME comments", "Report the counts for each file"],
        does_not=["Edit any file"],
        inputs=[IOField(name="folder_path", type="string", description="The folder to read", required=True)],
        outputs=[IOField(name="counts", type="list", description="Each file with its counts", required=True)],
        workflow=[
            Step(title="Read the folder", instruction="List the files under `folder_path`.", on_failure="Stop and say the folder cannot be read."),
            Step(title="Count", instruction="Count the lines with TODO or FIXME in each file.", on_failure="Report which file could not be read."),
            Step(title="Report", instruction="Return `counts`: every file with its counts.", on_failure="Say what is missing."),
        ],
        permissions=["read_files"],
        error_handling=["If the folder is unreadable, stop and say so."],
        limitations=["Only exact TODO and FIXME words are counted."],
        tests=[
            SkillTest(name="counts a file", kind="positive", input_description="A folder with one TODO", expected_result="The file is listed with 1", covers=covers),
            SkillTest(name="unreadable folder", kind="negative", input_description="A path that does not exist", expected_result="It stops and says so", covers=covers),
            SkillTest(name="empty folder", kind="edge", input_description="A folder with no files", expected_result="An empty list", covers=covers),
        ],
    )


def respond(schema, prompt, system):
    time.sleep(DELAY)
    if schema is Extraction:
        return extraction(prompt)
    if schema is SkillDraft:
        return design(prompt)
    raise ProviderError(f"The fake model has no answer for {schema.__name__}.")


def provider():
    if not FLAG.exists():
        raise ProviderError("LLM_PROVIDER is ''. Supported: custom, gemini, groq, mistral, openai, openrouter. Set it in .env.")
    return MockProvider(respond)


def main() -> None:
    library = Library(DATA / "library")
    database = Database(f"sqlite:///{(DATA / 'e2e.db').as_posix()}")
    database.migrate()
    builder = Builder(
        database, library, DATA / "builds", provider_factory=provider, runner=JobRunner(),
        sandbox_note=lambda: "unavailable. (the browser test does not use the sandbox)",
    )
    uvicorn.run(create_app(library, builder=builder), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
