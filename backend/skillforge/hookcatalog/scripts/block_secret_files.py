"""SkillForge hook: block-secret-files.

Runs before Claude's file tools (Read, Write, Edit, NotebookEdit) and stops them when the file's name looks like one that holds a
secret. It reads one JSON event on stdin, looks only at the file's name, and exits 2 (which blocks) with the reason on stderr.
It does not write files, use the network or start programs. If it cannot understand the event it BLOCKS (exit 2) and says so:
a guard that cannot see what it is guarding does not wave it through, and a changed format is noticed at once, never silently
ignored. (If it cannot be started at all, for example because python is not on the PATH, hooks.json says onFailure "block".)

Extra names to protect come as `--also NAME` (letters, digits and . _ - * ? only).
"""

import fnmatch
import json
import sys

PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", ".netrc", ".pgpass", ".git-credentials",
)
EXAMPLES = (".env.example", ".env.sample", ".env.template", ".env.dist")  # meant to be committed: they hold no secret
PATH_KEYS = ("file_path", "notebook_path", "path")


def fail(reason):
    sys.stderr.write("block-secret-files: " + reason + " It blocked this to be safe.\n")
    return 2


def base_name(path):
    """The last part of a path written either way, as the file system sees it: no trailing dots or spaces, no stream name, lower case."""
    name = path.replace("\\", "/").rstrip("/").split("/")[-1]
    name = name.split(":")[0].rstrip(" .")
    return name.lower()


def reads_as_secret(name, extra):
    if any(fnmatch.fnmatchcase(name, pattern.lower()) for pattern in extra):
        return True
    return name not in EXAMPLES and any(fnmatch.fnmatchcase(name, pattern) for pattern in PATTERNS)


def main(argv):
    extra = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == "--also"]
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return fail("Claude Code sent something that is not JSON.")
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return fail("the event has no tool_input.")
    tool_input = event["tool_input"]
    paths = [tool_input[key] for key in PATH_KEYS if isinstance(tool_input.get(key), str) and tool_input[key]]
    if not paths:
        return fail("the input of " + str(event.get("tool_name"))[:40] + " has no file path in it.")
    for path in paths:
        name = base_name(path)
        if reads_as_secret(name, extra):
            sys.stderr.write(
                "block-secret-files: '" + name[:80] + "' looks like a file that holds secrets, so this was blocked. "
                "Ask the person to do it themselves, or to change this hook.\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
