"""SkillForge hook: block-force-push.

Runs before Claude's shell tools (Bash, PowerShell) and stops a `git push` that forces: --force, -f (alone or inside a group such
as -fu), --force-with-lease, --force-if-includes or --mirror (or the start of one of them, which git also accepts), or a refspec
that starts with +. It reads the command as text: a lexer splits it into simple commands (on ; & | ( ) and new lines outside
quotes, and at every backtick or $( anywhere), keeps quoted text together, joins line continuations, looks inside `bash -c`,
`powershell -Command`, `cmd /c` and `eval`, and accepts git.exe and git.cmd. An alias, a script, a variable or an encoded command
that pushes is NOT seen: this is a policy aid, not a security boundary. It exits 2 (which blocks) with the reason on stderr. It does
not write files, use the network or start programs. If it cannot understand the event, or the command is too long to read, it BLOCKS
(exit 2) and says so: a guard that cannot see what it is guarding does not wave it through. (If it cannot be started at all, for
example because python is not on the PATH, hooks.json says onFailure "block".)
"""

import json
import sys

MAX_COMMAND = 50_000
MAX_DEPTH = 3
LONG_FORCE = ("--force", "--force-with-lease", "--force-if-includes")
MIRROR = "--mirror"
GIT_NAMES = ("git", "git.exe", "git.cmd", "git.bat")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd", "eval")
SEPARATORS = ";&|()\n\r"


def fail(reason):
    sys.stderr.write("block-force-push: " + reason + " It blocked this to be safe.\n")
    return 2


def tokenize(text, backtick_separates):
    """The simple commands of `text`, each a list of words. Quotes group and are removed; a backslash before a letter, digit, dot or
    colon is kept (a Windows path), before anything else it escapes; a backtick is a separator (command substitution) or, when
    `backtick_separates` is false, an escape (PowerShell)."""
    for joined in ("\\\r\n", "\\\n", "`\r\n", "`\n"):
        text = text.replace(joined, " ")
    segments, words, word, quote, started = [], [], [], "", False
    i, size = 0, len(text)

    def end_word():
        nonlocal word, started
        if started:
            words.append("".join(word))
        word, started = [], False

    def end_segment():
        nonlocal words
        end_word()
        if words:
            segments.append(words)
        words = []

    while i < size:
        ch = text[i]
        if ch == "$" and i + 1 < size and text[i + 1] == "(":
            end_segment()  # $( runs a command, even inside double quotes
            quote = ""
            i += 2
            continue
        if ch == "$" and i + 1 < size and text[i + 1] in "'\"" and not quote:
            i += 1  # $'...' (ANSI-C quoting): the dollar sign is not part of the word
            continue
        if ch == "`":
            if backtick_separates:
                end_segment()
                quote = ""
            i += 1
            continue
        if quote:
            if ch == quote:
                quote = ""
            else:
                word.append(ch)
        elif ch in "'\"":
            quote, started = ch, True
        elif ch == "\\" and i + 1 < size:
            nxt = text[i + 1]
            if nxt.isalnum() or nxt in "_.:":
                word.append(ch)
            else:
                word.append(nxt)
                i += 1
            started = True
        elif ch in SEPARATORS:
            end_segment()
        elif ch.isspace():
            end_word()
        else:
            word.append(ch)
            started = True
        i += 1
    end_segment()
    return segments


def base(word):
    return word.replace("\\", "/").rsplit("/", 1)[-1].lower()


def forcing(option):
    if option.startswith("--"):
        name = option.split("=")[0]
        if len(name) >= 4 and any(full.startswith(name) for full in LONG_FORCE):  # git accepts the start of a long option, such as --forc
            return True
        return len(name) >= 3 and MIRROR.startswith(name)  # --mirror updates every ref by force
    if option.startswith("-"):
        return len(option) > 1 and "f" in option[1:] and option[1:].isalpha()  # -f, -fu
    return option.startswith("+") and len(option) > 1 or ":+" in option  # +main, HEAD:+main


def forced_push(words):
    git = next((i for i, word in enumerate(words) if base(word) in GIT_NAMES), -1)
    if git < 0:
        return False
    push = next((i for i in range(git + 1, len(words)) if words[i] == "push"), -1)
    return push >= 0 and any(forcing(option) for option in words[push + 1:])


def blocked(text, depth=0):
    for backtick_separates in (True, False):
        for words in tokenize(text, backtick_separates):
            if forced_push(words):
                return True
            head = base(words[0]).removesuffix(".exe") if words else ""
            if depth < MAX_DEPTH and head in SHELLS:
                for word in words[1:]:  # the script a shell is given: `bash -c '...'`, `cmd /c "..."`, `eval '...'`
                    if " " in word or "\t" in word or head == "eval":
                        if blocked(" ".join(words[1:]) if head == "eval" else word, depth + 1):
                            return True
    return False


def main():
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return fail("Claude Code sent something that is not JSON.")
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return fail("the event has no tool_input.")
    command = event["tool_input"].get("command")
    if not isinstance(command, str):
        return fail("the input of " + str(event.get("tool_name"))[:40] + " has no command in it.")
    if len(command) > MAX_COMMAND:
        return fail("the command is too long to read.")
    if blocked(command):
        sys.stderr.write("block-force-push: this would force-push, so it was blocked. Ask the person to do it themselves, or to change this hook.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
