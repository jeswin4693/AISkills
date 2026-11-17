# Languages: what is supported, and how deeply

SkillForge AI works on repositories in many programming languages. "Supported" has three honest levels, and
`python -m skillforge languages` prints the table for the version you have.

| Level | Languages | What you get |
|---|---|---|
| **full** | Python, TypeScript, TSX, JavaScript | Functions, classes, imports resolved to files, calls resolved by scope and imports, re-exports, closures. |
| **standard** | Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin | Functions, classes, imports and calls. Links are labelled `resolved` (proven) or `guess` (name only). |
| **basic** | 32 more, including Swift, Dart, Lua, Scala, Haskell, Elixir, Julia, Perl, PowerShell, Bash, SQL, Zig, COBOL, Fortran, and `al` (Business Central) | Definitions (functions, classes, methods) and **duplicate detection**. No calls and no imports are claimed. |
| not parsed | everything else (JSON, YAML, Markdown, XML, images, ...) | Not source code in this sense. |

Duplicate detection works for every language that has a grammar, because it compares the shape of the syntax
tree, not the words.

## How parsers are obtained

Python uses the standard library. TypeScript and JavaScript use ordinary Python packages. **Every other grammar
comes from `tree-sitter-language-pack`, which downloads each native grammar the first time it is needed and
caches it** (`%LOCALAPPDATA%\tree-sitter-language-pack` on Windows). Things to know:

- Grammars are native code downloaded from the pack's release server; the pack verifies them against checksums
  in its manifest. Treat them like any dependency you install.
- If a grammar cannot be fetched (offline, blocked network), that one language degrades: its files are counted
  but not parsed, and the graph's notes say why. Nothing else breaks, and the files are retried next time.
- `SKILLFORGE_OFFLINE=1` forbids downloads; only grammars already cached are used.
- `python -m skillforge languages --download` fetches the standard-level grammars up front, so a first run on
  a new machine does not surprise you. `--download-all` fetches all 45.

## How imports and names are resolved (standard languages)

| Language | Imports map to files by | A bare name can refer to |
|---|---|---|
| Java, Kotlin | package path (`a.b.C` -> `.../a/b/C.java`), tolerating source roots | the same package (directory), imported classes, methods of the same class (implicit `this`) |
| Go | the package's directory (`example.com/proj/util` -> `util/`); the import alias names the directory | the same package (directory); methods through their receiver |
| Rust | `mod x;`, `use crate::a::b::Name`, `self::`, `super::` | the same file; methods of `impl` blocks |
| C, C++ | `#include "x.h"` (relative, else a unique path suffix); `<system>` headers are external | a unique function name in the repository (a **guess**); C++ methods call each other without `this` |
| C# | no file mapping (namespaces span files) | a unique class or function name in the repository (a **guess**) |
| Ruby, PHP | `require_relative`, `require`, `include`; PHP `use Namespace\Class` by path suffix | Ruby/PHP: a unique name in the repository (a **guess**) |

When a name matches several things, no link is made and the call is counted as ambiguous.

## Limits (stated, not hidden)

- Static analysis cannot see reflection, dynamic dispatch, macros, templates or generated code. Method calls on a
  variable of unknown type are only guesses, and are dropped when several classes share the method name.
- `.h` files are read as C (a C++ header with classes will show syntax errors, which are reported).
- Kotlin's grammar has no named fields, so its extraction reads children by position and is the most fragile of
  the standard languages.
- Objective-C (`.m`) is not mapped because the extension is ambiguous (MATLAB).
- `tsconfig`/module-path aliases, Maven/Gradle module layouts and Go `replace` directives are not read; imports
  that cannot be tied to a file are treated as external, not guessed.

## Validators and the sandbox

- The static validators check a skill's scripts for syntax errors in **any** language with a grammar. Capability
  analysis (what a script may do) exists only for Python and JavaScript/TypeScript; for other languages the
  validator says the capabilities were **not** checked.
- The sandbox runs interpreter-style languages: Python, JavaScript, TypeScript, Bash, Ruby, PHP and Java
  (single-file launch). Compiled languages (Go, Rust, C, C++, C#, Kotlin) are not runnable: the strict sandbox is
  read-only with a non-executable `/tmp`, so there is nowhere to build into, and loosening that would weaken the
  locks. See [validate.md](validate.md) and [sandbox-wsl.md](sandbox-wsl.md).
