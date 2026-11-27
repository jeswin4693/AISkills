import { describe, expect, it } from "vitest";
import {
  answerProblem, answersRequest, approvalSentence, blockedSentence, draftProblem, draftsOf, eventLine, isDirty, MAX_ANSWER, statusSentence, stopsOf, summaryLine,
  type Drafts,
} from "./planSession";
import type { PlanApproval, PlanSessionView, PlanSummary, TaskPlan } from "./types";

const plan = {} as TaskPlan; // the logic here reads only the session's own lists

function view(over: Partial<PlanSessionView> = {}): PlanSessionView {
  return {
    id: "a".repeat(32), status: "open", created_at: "2026-11-27T10:00:00+00:00", updated_at: "2026-11-27T10:00:00+00:00", rev: 3, plan,
    questions: [
      { index: 0, question: "What should the JSON look like?", why: "w", blocking: true, source: "model", answer: null },
      { index: 1, question: "Which file holds the command?", why: "w", blocking: true, source: "code", answer: null },
      { index: 2, question: "Should the old output stay the default?", why: "w", blocking: false, source: "model", answer: null },
    ],
    assumptions: [
      { index: 0, text: "The option is off by default.", why: "w", decision: null },
      { index: 1, text: "The output goes to the terminal.", why: "w", decision: null },
    ],
    missing: [], unanswered: [], can_approve: false, approval: null, events: [], ...over,
  };
}

const empty: Drafts = { questions: {}, assumptions: {} };

describe("draftsOf", () => {
  it("starts from what the server holds: an answer as written and a decision, and nothing for what is blank", () => {
    const v = view();
    v.questions[0].answer = "A list of names.";
    v.assumptions[1].decision = "reject";
    expect(draftsOf(v)).toEqual({ questions: { 0: "A list of names.", 1: "", 2: "" }, assumptions: { 0: "", 1: "reject" } });
  });
});

describe("answerProblem", () => {
  it("accepts a blank box (it removes the answer) and an answer with a letter or a digit in any alphabet", () => {
    for (const ok of ["", "   ", "names", "42", "é", "日本語", "x?"]) expect(answerProblem(ok), ok).toBeNull();
  });

  it("refuses an answer with no word in it", () => {
    for (const bad of ["???", "...", "-", "  ?  ", "!!! ... ???"]) expect(answerProblem(bad), bad).toContain("words");
  });

  it("allows exactly 2,000 characters after trimming and refuses one more, naming the limit", () => {
    expect(answerProblem("a".repeat(MAX_ANSWER))).toBeNull();
    expect(answerProblem(`  ${"a".repeat(MAX_ANSWER)}  `)).toBeNull();
    expect(answerProblem("a".repeat(MAX_ANSWER + 1))).toContain("2,000");
  });

  it("counts a character as one however it is written, as the server does (a letter outside the basic plane is not two)", () => {
    const letter = String.fromCodePoint(0x1d49c); // a letter that takes two UTF-16 units
    expect(answerProblem(letter.repeat(MAX_ANSWER))).toBeNull();
    expect(answerProblem(`${letter.repeat(MAX_ANSWER)}a`)).toContain("2,000");
  });

  it("does not take a symbol such as an emoji for a word, as the server does not", () => {
    expect(answerProblem(String.fromCodePoint(0x1f600))).toBe("Write the answer in words.");
  });
});

describe("draftProblem", () => {
  it("names the question number of the first answer that cannot be kept", () => {
    expect(draftProblem(view(), { questions: { 0: "fine", 1: "???" }, assumptions: {} })).toBe("Question 2: write the answer in words.");
    expect(draftProblem(view(), { questions: { 2: "a".repeat(2001) }, assumptions: {} })).toContain("Question 3");
    expect(draftProblem(view(), { questions: { 0: "fine" }, assumptions: {} })).toBeNull();
  });
});

describe("stopsOf", () => {
  it("lists what would stop an approval from the boxes as they are now, in the plan's order", () => {
    expect(stopsOf(view(), empty)).toEqual([
      "Answer: What should the JSON look like?", "Answer: Which file holds the command?",
      "Decide: The option is off by default.", "Decide: The output goes to the terminal.",
    ]);
  });

  it("stops listing a blocking question once its box has a word, and an assumption once it has a decision, saved or not", () => {
    expect(stopsOf(view(), { questions: { 0: "names" }, assumptions: { 1: "reject" } })).toEqual(["Answer: Which file holds the command?", "Decide: The option is off by default."]);
  });

  it("treats a box with only spaces as empty, and never lists a question that is not blocking", () => {
    expect(stopsOf(view(), { questions: { 0: "   ", 1: "cli.py" }, assumptions: { 0: "approve", 1: "approve" } })).toEqual(["Answer: What should the JSON look like?"]);
    expect(stopsOf(view(), { questions: { 0: "a", 1: "b" }, assumptions: { 0: "approve", 1: "approve" } })).toEqual([]);
  });

  it("treats a blank decision as undecided", () => {
    expect(stopsOf(view(), { questions: { 0: "a", 1: "b" }, assumptions: { 0: "", 1: "approve" } })).toEqual(["Decide: The option is off by default."]);
  });
});

describe("blockedSentence", () => {
  it("says how many blocking questions and assumptions are missing, in the singular and the plural, as the server does", () => {
    expect(blockedSentence(stopsOf(view(), empty))).toBe("Not ready to approve: 2 blocking questions have no answer, and 2 assumptions have no decision.");
    expect(blockedSentence(["Answer: x", "Decide: y"])).toBe("Not ready to approve: 1 blocking question has no answer, and 1 assumption has no decision.");
    expect(blockedSentence(["Decide: y"])).toBe("Not ready to approve: 1 assumption has no decision.");
    expect(blockedSentence(["Answer: x", "Answer: z"])).toBe("Not ready to approve: 2 blocking questions have no answer.");
  });
});

describe("isDirty", () => {
  it("is false for what the server holds and true for any change in an answer or a decision", () => {
    const v = view();
    v.questions[0].answer = "names";
    v.assumptions[0].decision = "approve";
    const same = draftsOf(v);
    expect(isDirty(v, same)).toBe(false);
    expect(isDirty(v, { ...same, questions: { ...same.questions, 0: "names!" } })).toBe(true);
    expect(isDirty(v, { ...same, questions: { ...same.questions, 2: "new" } })).toBe(true);
    expect(isDirty(v, { ...same, assumptions: { ...same.assumptions, 0: "reject" } })).toBe(true);
    expect(isDirty(v, { ...same, assumptions: { ...same.assumptions, 1: "approve" } })).toBe(true);
    expect(isDirty(v, { ...same, assumptions: { ...same.assumptions, 0: "" } })).toBe(true);
  });

  it("does not count spaces around an answer, or a Windows line break the server turns into a plain one, as a change", () => {
    const v = view();
    v.questions[0].answer = "line one\nline two";
    expect(isDirty(v, { ...draftsOf(v), questions: { ...draftsOf(v).questions, 0: "  line one\r\nline two  " } })).toBe(false);
  });
});

describe("answersRequest", () => {
  it("names the state the person saw, sends every answer and decision with its position, and leaves out what is blank", () => {
    const req = answersRequest(view({ rev: 7 }), { questions: { 0: "  names  ", 1: "   ", 2: "yes" }, assumptions: { 0: "approve", 1: "" } });
    expect(req).toEqual({ rev: 7, questions: { "0": "names", "2": "yes" }, assumptions: { "0": "approve" } });
  });

  it("sends an empty set when everything is blank, which removes whatever was saved", () => {
    expect(answersRequest(view(), empty)).toEqual({ rev: 3, questions: {}, assumptions: {} });
  });
});

describe("statusSentence", () => {
  it("says what is missing while it is, and that nothing is when nothing is", () => {
    expect(statusSentence(view(), empty)).toBe("Not ready to approve: 2 blocking questions have no answer, and 2 assumptions have no decision.");
    expect(statusSentence(view(), { questions: { 0: "a", 1: "b", 2: "c" }, assumptions: { 0: "approve", 1: "approve" } })).toBe("Ready to approve. Nothing blocking is missing.");
  });

  it("says a question that is not blocking was left open, once the rest is ready, counted from the boxes as they are now", () => {
    expect(statusSentence(view(), { questions: { 0: "a", 1: "b", 2: "c" }, assumptions: { 0: "approve", 1: "approve" } })).not.toContain("unanswered");
    expect(statusSentence(view(), { questions: { 0: "a", 1: "b" }, assumptions: { 0: "approve", 1: "approve" } })).toBe(
      "Ready to approve. Nothing blocking is missing. 1 question that does not block is left unanswered.",
    );
    expect(statusSentence(view(), { questions: { 0: "a", 1: "b", 2: "   " }, assumptions: { 0: "approve", 1: "approve" } })).toContain("left unanswered");
  });

  it("says 'are' for more than one question left open", () => {
    const v = view();
    v.questions.push({ index: 3, question: "Another?", why: "w", blocking: false, source: "model", answer: null });
    expect(statusSentence(v, { questions: { 0: "a", 1: "b" }, assumptions: { 0: "approve", 1: "approve" } })).toContain("2 questions that do not block are left unanswered.");
  });

  it("describes an approved plan by its approval", () => {
    const a: PlanApproval = { approved_at: "2026-11-27T10:00:00+00:00", fingerprint: "ab".repeat(32), tier: 2, intact: true };
    expect(statusSentence(view({ status: "approved", approval: a }), empty)).toBe(approvalSentence(a));
  });
});

describe("approvalSentence", () => {
  const a: PlanApproval = { approved_at: "2026-11-27T10:00:00+00:00", fingerprint: "abcdef0123456789".repeat(4), tier: 3, intact: true };

  it("says the tier and the start of the fingerprint, and that the fingerprint is not a signature", () => {
    const s = approvalSentence(a);
    expect(s).toContain("Approved");
    expect(s).toContain("Tier 3");
    expect(s).toContain("abcdef012345");
    expect(s).not.toContain("abcdef0123456789abcdef0123456789");
  });

  it("warns, in words, when the kept record no longer matches the fingerprint", () => {
    expect(approvalSentence(a)).not.toContain("changed");
    expect(approvalSentence({ ...a, intact: false })).toContain("does not match");
  });
});

describe("eventLine", () => {
  it("words each kind of event", () => {
    const at = "2026-11-27T10:00:00+00:00";
    expect(eventLine({ at, what: "made" })).toContain("Plan made");
    expect(eventLine({ at, what: "answers saved" })).toContain("Answers saved");
    expect(eventLine({ at, what: "approved" })).toContain("Approved");
    expect(eventLine({ at, what: "reopened" })).toContain("Approval withdrawn");
  });
});

describe("summaryLine", () => {
  const s = (over: Partial<PlanSummary> = {}): PlanSummary => ({
    id: "a".repeat(32), status: "open", created_at: "2026-11-27T10:00:00+00:00", updated_at: "2026-11-27T10:00:00+00:00", approved_at: null, task: "t", repo: "shop", mode: "model",
    readable: true, tier: 2, tier_name: "Feature or refactor", questions: { total: 3, blocking: 2, answered: 1, blocking_answered: 1 }, assumptions: { total: 2, decided: 0 }, ...over,
  });

  it("tells where a plan stands: the tier, the questions answered, the blocking ones, the assumptions decided", () => {
    expect(summaryLine(s())).toBe("Tier 2 · 1 of 3 questions answered (1 of 2 blocking) · 0 of 2 assumptions decided");
  });

  it("leaves out what the plan does not have", () => {
    expect(summaryLine(s({ questions: { total: 0, blocking: 0, answered: 0, blocking_answered: 0 }, assumptions: { total: 0, decided: 0 } }))).toBe("Tier 2 · no questions · no assumptions");
    expect(summaryLine(s({ questions: { total: 1, blocking: 0, answered: 0, blocking_answered: 0 } }))).toContain("0 of 1 question answered");
  });

  it("says a plan an older version made cannot be shown", () => {
    expect(summaryLine(s({ readable: false, tier: undefined, questions: undefined, assumptions: undefined }))).toBe("Made by an older version: it cannot be shown. Delete it.");
  });
});
