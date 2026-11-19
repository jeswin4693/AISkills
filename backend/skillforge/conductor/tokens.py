"""Plan what to read and what to create, and what that costs in tokens, BEFORE doing any of it.

The numbers are estimates: about 4 characters to a token, which is rough and differs between model providers (code and
non-English text usually cost more). They are good for comparing options and for noticing a plan that is far too big,
not for billing. This plan covers the context to READ and the files to CREATE. It does not cover the model's own
reasoning or its replies, and it is not a promise about total spend.

The cheapest useful context comes first: the rule files, then exactly the functions the task names (the graph knows
each function's first and last line), then the direct callers and callees, then tests. A whole file is the fallback.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from ..graph.model import RepoGraph, Symbol
from .models import CreateItem, Mention, ReadItem, Reach, TokenPlan

MAX_TESTS = 3  # tied test files planned per task: a widely imported file is tied to dozens
NARROW_AT = 1_500  # a whole file at least this big gets a hint about naming a function instead
_STOP = {"the", "and", "for", "that", "this", "with", "from", "into", "not", "are", "all", "any", "can", "does", "its", "has", "have", "how", "must", "should", "will", "work", "use", "add", "fix", "change", "make", "new", "when", "then", "than", "other", "only", "keep", "read", "print", "prints", "command", "commands"}
CHARS_PER_TOKEN = 4
METHOD = f"about {CHARS_PER_TOKEN} characters per token: an estimate, not a measurement"
BUDGETS = {0: 8_000, 1: 30_000, 2: 100_000, 3: 250_000}  # tokens of context to read, by tier: defaults, not rules
CREATE_TOKENS = {"small": 400, "medium": 1_200, "large": 3_000}
MAX_NEIGHBOURS = 8  # callers, and callees, per named function


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def words_of(text: str) -> set[str]:
    """Lower-case words of three letters or more, splitting snake_case, camelCase and paths, without filler words."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return {w for w in re.findall(r"[a-z0-9]+", spaced.lower()) if len(w) >= 3 and w not in _STOP}


def relevance(prompt_words: set[str], name: str) -> int:
    """How many of the person's words appear in a name or path. A hint for ranking, never a measurement."""
    return len(prompt_words & words_of(name))


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


class _Reader:
    """Reads each file once, and says what a whole file or a range of lines would cost."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._text: dict[str, str | None] = {}

    def text(self, rel: str) -> str | None:
        if rel not in self._text:
            self._text[rel] = _read(self.root, rel)
        return self._text[rel]

    def whole(self, rel: str) -> int | None:
        t = self.text(rel)
        return None if t is None else estimate_tokens(t)

    def lines(self, rel: str, first: int, last: int) -> int | None:
        t = self.text(rel)
        return None if t is None else estimate_tokens("".join(t.splitlines(keepends=True)[first - 1:last]))


def _slice(rd: _Reader, s: Symbol, why: str, priority: int) -> ReadItem | None:
    tokens, whole = rd.lines(s.file, s.line, s.end_line), rd.whole(s.file)
    if tokens is None or whole is None:
        return None
    return ReadItem(kind="slice", path=s.file, symbol=s.qualname, lines=f"{s.line}-{s.end_line}", tokens=tokens, whole_file_tokens=whole, why=why, priority=priority)


def _whole(rd: _Reader, path: str, why: str, priority: int) -> ReadItem | None:
    whole = rd.whole(path)
    return None if whole is None else ReadItem(kind="file", path=path, symbol="", lines="", tokens=whole, whole_file_tokens=whole, why=why, priority=priority)


def _narrowing_hint(g: RepoGraph, rd: _Reader, path: str, whole_tokens: int, pwords: set[str]) -> list[str]:
    """A big file read whole is the costly choice. If functions in it match the person's words, say so, with their cost."""
    if whole_tokens < NARROW_AT or path not in g.files:
        return []
    cands = []
    for s in g.files[path].symbols:
        if s.kind in ("function", "method", "class"):
            score = relevance(pwords, s.qualname)
            cost = rd.lines(path, s.line, s.end_line)
            if score > 0 and cost is not None:
                cands.append((-score, cost, s.qualname, cost))
    cands.sort()
    if not cands:
        return []
    shown = ", ".join(f"`{q}` ({c:,} tokens)" for _, _, q, c in cands[:3])
    return [
        f"`{path}` costs {whole_tokens:,} tokens read whole. Functions in it whose names match your words: {shown}. "
        "Name the one you mean (for example in backticks) and only its lines are planned. This is a guess from names, not a measurement."
    ]


def plan_tokens(
    g: RepoGraph | None, root: Path | None, mentions: list[Mention], reach: list[Reach], rule_files: list[str],
    new_files: list[tuple[str, str, str]], tier: int, budget: int | None = None, prompt: str = "",
) -> tuple[TokenPlan, list[str]]:
    """Returns the plan and notes about anything that could not be planned. `new_files` are (path, purpose, size).

    `prompt` is only used to rank candidates (which tests, which functions look relevant): it never decides anything."""
    notes: list[str] = []
    budget = budget if budget is not None else BUDGETS.get(tier, BUDGETS[2])
    items: list[ReadItem] = []
    left_out: list[ReadItem] = []  # not planned for a reason other than the budget
    pwords = words_of(prompt)

    if g is not None and root is not None:
        rd = _Reader(root)
        for rel in rule_files:
            it = _whole(rd, rel, "the rules for this repository", 0)
            if it:
                items.append(it)
        covered_files: set[str] = set()
        named_whole = {m.target for m in mentions if m.kind == "file" and m.target}  # a file read whole already holds its functions
        for m in mentions:
            if m.ambiguous or not m.target:
                continue
            if m.kind == "file":
                it = _whole(rd, m.target, f"you named this file ({m.text})", 1)
                if it:
                    items.append(it)
                    covered_files.add(m.target)
                    notes += _narrowing_hint(g, rd, m.target, it.tokens, pwords)
                continue
            sym = g.symbols.get(m.target)
            if sym is None:
                continue
            it = None if sym.file in named_whole else _slice(rd, sym, f"you named this function ({m.text})", 1)
            if it:
                items.append(it)
                covered_files.add(sym.file)
            for direction, edges in (("calls it", g.callers_of(sym.id)), ("is called by it", g.callees_of(sym.id))):
                taken = 0
                for e in edges:
                    other = e.src if direction == "calls it" else e.dst
                    s = g.symbols.get(other)
                    if e.conf != "resolved" or s is None or taken >= MAX_NEIGHBOURS:
                        continue
                    nit = _slice(rd, s, f"{s.qualname} {direction} ({'a test' if g.files[s.file].is_test else 'proven link'})", 2)
                    if nit:
                        items.append(nit)
                        taken += 1
        slices_files = {i.path for i in items if i.kind == "slice"}
        tied: dict[str, str] = {}  # test file -> the target it is tied to
        for r in reach:
            for t in r.tests_tied:
                if t not in slices_files and t not in covered_files:
                    tied.setdefault(t, r.target)
        # Only the few most relevant tests are planned: a widely imported file is tied to dozens, and reading them all is the
        # opposite of a plan. Relevance is a ranking by how many of the person's words appear in the test's path.
        ranked = sorted(tied, key=lambda t: (-relevance(pwords, t), rd.whole(t) or 0, t))
        for i, t in enumerate(ranked):
            why = f"a test tied to {tied[t]}"
            if i < MAX_TESTS:
                it = _whole(rd, t, why, 3)
                if it:
                    items.append(it)
            else:
                it = _whole(rd, t, f"{why}; only the {MAX_TESTS} most relevant of {len(ranked)} tied test files are planned", 3)
                if it:
                    left_out.append(it)
        if any(i.kind == "file" and i.priority == 1 for i in items):
            notes.append("A whole file you named is planned as a whole file: the graph can only cut out single functions.")
    else:
        notes.append("No repository was given, so there is no reading plan: only the files to create are costed.")

    unique: dict[tuple[str, str, str], ReadItem] = {}
    for it in items:
        key = (it.path, it.symbol, it.lines)
        if key not in unique or it.priority < unique[key].priority:
            unique[key] = it
    ordered = sorted(unique.values(), key=lambda i: (i.priority, i.tokens, i.path, i.lines))

    reads: list[ReadItem] = []
    dropped: list[ReadItem] = list(left_out)
    spent = 0
    for it in ordered:
        if it.priority == 0 or spent + it.tokens <= budget:  # the rules are always read: they cost what they cost
            reads.append(it)
            spent += it.tokens
        else:
            dropped.append(it)
    whole_total = sum({i.path: i.whole_file_tokens for i in reads}.values())

    create: list[CreateItem] = []
    for path, purpose, size in new_files:
        create.append(CreateItem(path=path, purpose=purpose, size=size, tokens=CREATE_TOKENS.get(size, CREATE_TOKENS["medium"])))
    over_budget = [d for d in dropped if d not in left_out]
    plan = TokenPlan(
        budget=budget, reads=reads, dropped=dropped, read_total=spent, whole_files_total=whole_total, create=create,
        create_total=sum(c.tokens for c in create), fits_budget=spent <= budget and not over_budget, method=METHOD,
    )
    if over_budget:
        notes.append(f"{len(over_budget)} item(s) do not fit the {budget:,}-token reading budget and are left out, lowest priority first.")
    if spent > budget:
        notes.append(f"The rule files alone cost {spent:,} tokens, more than the {budget:,}-token budget.")
    return plan, notes
