"""SkillForge hook: block-force-push.

Runs before Claude's shell tools (Bash, PowerShell) and stops a `git push` that forces: --force, -f (alone or inside a group such
as -fu), --force-with-lease, --force-if-includes, or a refspec that starts with +. It reads the command as text, one simple command
at a time (split on ; & | and new lines), so an alias, a script, or a push built from variables is not seen. It exits 2 (which
blocks) with the reason on stderr. It does not write files, use the network or start programs. If it cannot understand the event
it does NOT block: it exits 1, which Claude Code shows as a non-blocking error.
"""

import json
import re
import shlex
import sys

SPLIT = re.compile(r"[;&|\n]+")
SHORT_GROUP = re.compile(r"-[A-Za-z]*f[A-Za-z]*")
LONG_FORCE = ("--force", "--force-with-lease", "--force-if-includes")


def fail(reason):
    sys.stderr.write("block-force-push: " + reason + " It did not block anything.\n")
    return 1


def words(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()  # an unbalanced quote: read it as plain words rather than miss a push


def is_git(word):
    name = word.replace("\\", "/").split("/")[-1].lower()
    return name in ("git", "git.exe")


def forced_push(segment):
    tokens = words(segment)
    for start, token in enumerate(tokens):
        if not is_git(token):
            continue
        rest = tokens[start + 1:]
        if "push" not in rest:
            continue
        for option in rest[rest.index("push") + 1:]:
            if option.startswith("--"):
                if option == "--force" or option.split("=")[0] in LONG_FORCE:
                    return True
            elif option.startswith("-"):
                if SHORT_GROUP.fullmatch(option):
                    return True
            elif "+" in option.split(":")[-1][:1] or option.startswith("+"):
                return True
    return False


def main():
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return fail("Claude Code sent something that is not JSON.")
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return fail("the event has no tool_input.")
    command = event["tool_input"].get("command")
    if not isinstance(command, str):
        return fail("the input of " + str(event.get("tool_name"))[:40] + " has no command in it.")
    for segment in SPLIT.split(command):
        if forced_push(segment):
            sys.stderr.write("block-force-push: this would force-push, so it was blocked. Ask the person to do it themselves, or to change this hook.\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
