"""SkillForge hook: block-secret-files.

Runs before Claude's file tools (Read, Write, Edit, NotebookEdit) and stops them when the file's name looks like one that holds a
secret. It reads one JSON event on stdin, looks only at the file's name, and exits 2 (which blocks) with the reason on stderr.
It does not see Grep, Glob or shell commands, and it matches names only: it is a policy aid, not a security boundary. It does not
write files, use the network or start programs. If it cannot understand the event it BLOCKS (exit 2) and says so: a guard that
cannot see what it is guarding does not wave it through. (If it cannot be started at all, for example because python is not on the
PATH, hooks.json says onFailure "block".)

The name is judged the way Windows and macOS would open it: both slash styles, `.` and `..` folded away, a drive letter followed by
a name (C:.env) read as that name, trailing dots and spaces and stream names dropped, capitals ignored, and a short 8.3 name such as
ENV~1 refused because it can stand for a protected file.

Extra names to protect come as `--also NAME` (letters, digits and . _ - * ? only).
"""

import fnmatch
import json
import posixpath
import re
import sys

PATTERNS = (
    ".env", ".env.*", ".envrc", "*.pem", "*.key", "*.ppk", "*.p8", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "id_ecdsa_sk", "id_ed25519_sk", "credentials", "credentials.json", "credentials.yml", "credentials.yaml", "secrets.yml", "secrets.yaml", ".netrc",
    ".npmrc", ".pypirc", ".pgpass", ".htpasswd", ".git-credentials", "*.tfstate", "*.tfstate.backup", "*.tfvars",
)
EXAMPLES = (".env.example", ".env.sample", ".env.template", ".env.dist")  # meant to be committed: they hold no secret
PATH_KEYS = ("file_path", "notebook_path", "path")
SHORT_NAME = re.compile(r"[a-z0-9_]{1,6}~[0-9]+(\.[a-z0-9_]{0,3})?")
DRIVE = re.compile(r"^[A-Za-z]:(?=[^/\\])")


def fail(reason):
    sys.stderr.write("block-secret-files: " + reason + " It blocked this to be safe.\n")
    return 2


def base_name(path):
    """The last part of a path as the file system would open it, in lower case."""
    path = DRIVE.sub("", path.replace("\\", "/"))
    path = posixpath.normpath(path)
    name = path.rstrip("/").split("/")[-1]
    name = name.split(":")[0].rstrip(" .")
    return name.lower()


def reason_to_block(name, extra):
    if any(fnmatch.fnmatchcase(name, pattern.lower()) for pattern in extra):
        return "looks like a file that holds secrets"
    if name not in EXAMPLES and any(fnmatch.fnmatchcase(name, pattern) for pattern in PATTERNS):
        return "looks like a file that holds secrets"
    if SHORT_NAME.fullmatch(name):
        return "looks like a Windows short name, which can stand for a file that holds secrets"
    return ""


def main(argv):
    extra = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == "--also"]
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return fail("Claude Code sent something that is not JSON.")
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return fail("the event has no tool_input.")
    tool_input = event["tool_input"]
    paths = [tool_input[key] for key in PATH_KEYS if isinstance(tool_input.get(key), str) and tool_input[key]]
    if not paths:
        return fail("the input of " + str(event.get("tool_name"))[:40] + " has no file path in it.")
    for path in paths:
        name = base_name(path)
        why = reason_to_block(name, extra)
        if why:
            sys.stderr.write("block-secret-files: '" + name[:80] + "' " + why + ", so this was blocked. Ask the person to do it themselves, or to change this hook.\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
