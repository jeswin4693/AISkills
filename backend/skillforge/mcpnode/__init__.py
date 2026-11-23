"""What every generated Node MCP server is pinned to: the SDK, zod, Node, and the lockfile that goes with them.

These are facts checked by a real install and a real run on 2026-11-23 (docs/mcp-builder-node.md), kept in one place so the builder, the
reader and the image all say the same thing. A server's folder gets a `package.json` with these exact versions (no `scripts`), the
lockfile in `lock.template.json` with only the package name filled in, and the README says `npm ci --ignore-scripts`.
"""

from __future__ import annotations

import json
from pathlib import Path

SERVER_SDK = "@modelcontextprotocol/server"
CLIENT_SDK = "@modelcontextprotocol/client"  # the test harness only: a generated server never imports it
SDK_VERSION = "2.4.0"
ZOD_VERSION = "4.6.7"
PINNED = {SERVER_SDK: SDK_VERSION, "zod": ZOD_VERSION}
NODE_VERSION = "24"  # `node server.ts` strips types and `--permission` works: both were run on 24.13
SERVER_FILE = "server.ts"
PACKAGE_FILE = "package.json"
LOCK_FILE = "package-lock.json"
FIRST_VERSION = "0.1.0"
_TEMPLATE = Path(__file__).with_name("lock.template.json")


def package_json(name: str) -> str:
    """The package.json of a generated server. `"type": "module"` is required: without it Node reads server.ts as CommonJS and fails."""
    data = {"name": name, "version": FIRST_VERSION, "private": True, "type": "module", "dependencies": dict(PINNED)}
    return json.dumps(data, indent=2) + "\n"


def package_lock(name: str) -> str:
    """The pinned lockfile for a server called `name` (only the root's name differs between servers)."""
    data = json.loads(_TEMPLATE.read_text(encoding="utf-8"))
    data["name"] = name
    data["packages"][""]["name"] = name
    return json.dumps(data, indent=2) + "\n"


def is_our_lock(text: str, name: str) -> bool:
    """True when `text` is exactly the lockfile this builder writes for `name` (compared as data, so line endings and spacing do not matter)."""
    try:
        return json.loads(text) == json.loads(package_lock(name))
    except (ValueError, RecursionError):
        return False


def start_command(folder: str = "<full path to the folder>") -> list[str]:
    """The command that starts a server under Node's permission model: it may read its own folder and nothing else, write nothing and start nothing."""
    return ["node", "--permission", f"--allow-fs-read={folder}", f"{folder}/{SERVER_FILE}"]
