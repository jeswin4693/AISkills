"""SkillForge hook: log-tool-calls.

Runs after every tool call and adds one line, {"time": ..., "tool": ...}, to tool-calls.log in the plugin's data folder (the folder
Claude Code names in CLAUDE_PLUGIN_DATA). It records the tool's NAME and the time and nothing else: never what the tool was given
or what it returned. The log is renamed to tool-calls.log.1 when it reaches 1 MB. It does not use the network or start programs,
and it writes only that one file. If it cannot read the event or write the line it says so on stderr and exits 1 (a non-blocking
error); it never blocks anything, because it guards nothing: a missing log must not stop anyone's work.
"""

import datetime
import json
import os
import sys

LIMIT = 1_000_000
NAME = "tool-calls.log"


def fail(reason):
    sys.stderr.write("log-tool-calls: " + reason + " Nothing was logged.\n")
    return 1


def main():
    folder = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not folder:
        return fail("Claude Code did not give a data folder (CLAUDE_PLUGIN_DATA).")
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return fail("Claude Code sent something that is not JSON.")
    tool = event.get("tool_name") if isinstance(event, dict) else None
    if not isinstance(tool, str) or not tool:
        return fail("the event has no tool_name.")
    clean = "".join(ch for ch in tool if ch.isprintable())[:100]
    line = json.dumps({"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "tool": clean})
    path = os.path.join(folder, NAME)
    try:
        os.makedirs(folder, exist_ok=True)
        try:
            if os.path.exists(path) and os.path.getsize(path) >= LIMIT:
                os.replace(path, path + ".1")
        except FileNotFoundError:
            pass  # another hook rotated it first: the line below starts a fresh log
        with open(path, "a", encoding="utf-8") as log:
            log.write(line + "\n")
    except OSError as exc:
        return fail("could not write to " + NAME + " (" + type(exc).__name__ + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
