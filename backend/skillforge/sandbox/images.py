"""Which container image and command run a script in each language, inside the strict sandbox.

The sandbox is read-only with a non-executable /tmp. That suits interpreters (the script is read, nothing is
built), so only interpreter-style languages are listed. Compiled languages (Go, Rust, C, C++, C#, Kotlin) need a
writable, executable area to build into, which the strict sandbox refuses on purpose; they are not runnable yet.
"""

from __future__ import annotations

from ..mcpnode import CLIENT_SDK, NODE_VERSION, SDK_VERSION, SERVER_SDK, ZOD_VERSION

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


# The image that runs a generated MCP server. It is not a public image: it is built ONCE, with network, from the two lines below
# (`python -m skillforge sandbox-build-mcp`), and never built or pulled when a server is tested.
MCP_SDK_VERSION = "2.3.0"  # the official `mcp` package; its names were settled by a real install on 2026-11-20 (docs/mcp-builder.md)
MCP_IMAGE = f"skillforge-mcp:{MCP_SDK_VERSION}"
MCP_DOCKERFILE = f"FROM python:3.13-slim\nRUN pip install --no-cache-dir mcp=={MCP_SDK_VERSION}\n"


def mcp_build_command(status, image: str = MCP_IMAGE) -> list[str]:
    """The exact `docker build`, reaching docker the way `status` says. The Dockerfile is sent on standard input: no files, no context."""
    return [*status.prefix, "build", "-t", image, "-"]


# The image that runs a generated Node MCP server, built once the same way (`python -m skillforge sandbox-build-mcp-node`). The SDK, the client the
# harness uses and zod are installed in `/opt/sdk` and linked at `/node_modules`, so they are found from a server mounted at `/skill` (Node looks in
# every parent folder). No install scripts run. (`npm install --prefix /` fails: npm cannot use the root folder as a project.)
MCP_NODE_IMAGE = f"skillforge-mcp-node:{SDK_VERSION}"
NODE_SDK_DIR = "/opt/sdk"
MCP_NODE_DOCKERFILE = (
    f"FROM node:{NODE_VERSION}-slim\n"
    f"WORKDIR {NODE_SDK_DIR}\n"
    f"RUN npm init -y > /dev/null && npm install --ignore-scripts --no-audit --no-fund --save-exact "
    f"{SERVER_SDK}@{SDK_VERSION} {CLIENT_SDK}@{SDK_VERSION} zod@{ZOD_VERSION} && ln -s {NODE_SDK_DIR}/node_modules /node_modules\n"
)


def runnable_languages() -> list[str]:
    return sorted(RUNNERS)


def command_for(language: str, script: str) -> tuple[str, list[str]] | None:
    """(image, argv) to run `script` (a path relative to the skill folder), or None when the language cannot run here."""
    found = RUNNERS.get(language)
    if found is None:
        return None
    image, interpreter = found
    return image, [*interpreter, f"/skill/{script.lstrip('/')}"]
