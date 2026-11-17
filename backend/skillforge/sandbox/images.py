"""Which container image and command run a script in each language, inside the strict sandbox.

The sandbox is read-only with a non-executable /tmp. That suits interpreters (the script is read, nothing is
built), so only interpreter-style languages are listed. Compiled languages (Go, Rust, C, C++, C#, Kotlin) need a
writable, executable area to build into, which the strict sandbox refuses on purpose; they are not runnable yet.
"""

from __future__ import annotations

# language -> (image, interpreter command that takes the script path as its last argument)
RUNNERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "python": ("python:3.13-slim", ("python",)),
    "javascript": ("node:22-slim", ("node",)),
    "typescript": ("node:22-slim", ("node", "--experimental-strip-types")),
    "bash": ("bash:5", ("bash",)),
    "ruby": ("ruby:3.3-slim", ("ruby",)),
    "php": ("php:8.3-cli", ("php",)),
    "java": ("eclipse-temurin:21-jdk", ("java",)),  # single-file source launch: `java File.java`
}


def runnable_languages() -> list[str]:
    return sorted(RUNNERS)


def command_for(language: str, script: str) -> tuple[str, list[str]] | None:
    """(image, argv) to run `script` (a path relative to the skill folder), or None when the language cannot run here."""
    found = RUNNERS.get(language)
    if found is None:
        return None
    image, interpreter = found
    return image, [*interpreter, f"/skill/{script.lstrip('/')}"]
