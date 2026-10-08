# Hint (Supplementary Instruction) — one task

You are writing a short, gentle Supplementary Instruction (SI) for an AI coding agent that
has failed THIS task on every one of its N attempts. The SI is appended to the task's
instruction.md. Its job is to nudge the agent toward the part of the specification it keeps
getting wrong and toward the checks that would have caught it, WITHOUT giving away the
solution. Think: a teaching assistant giving hints after a student got stuck, not a code
review.

## Inputs (read in this order)

1. `hints/<task>/hint_input.md` — the consistent failures across runs (what the verifier
   requires, what the agents did instead, whether the requirement is stated in the spec,
   the missing knowledge), the process gaps, task-specific one-off findings, and an index
   of the spec's section headings with line numbers.
2. The task's `instruction.md` (and `environment/spec.md` when it differs) — open the
   sections that the consistent failures point to, so you can refer to them by heading.
3. `gap_analysis/<task>.md` and `tasks/<task>/task_summary.md` for detail if needed.
4. You MAY open the oracle under `solution/oracle/` to make sure you understand the
   correct behaviour. You must NEVER quote, paraphrase line by line, or name anything
   from it that is not already in the spec.

## What the hint should do

- Point at the spec sections / clauses the runs misread or skipped, by heading or by the
  spec's own words ("re-read the section on X, in particular the sentence about Y").
- Name the concept or convention that is relevant (e.g. "the difference between a key
  that is absent and a key whose value is null", "how the library decides the body
  encoding"), not the implementation.
- Warn about the trap the previous runs fell into, as a category ("adding a type check
  the spec does not ask for", "testing only the example given"), never as a diagnosis of
  a specific line.
- Say what to verify or double-check before finishing, in terms of observable behaviour
  the spec describes (which input shapes, which flows, which strings).
- Address ONLY the one or two clusters with the highest failed-in-runs count (the shared ceiling).
  Leave the long tail of other clusters and one-run failures alone. The goal is a slight lift into a
  1-6 out of 8 pass band, never 8 out of 8: a hint that fixes everything makes the task useless.

## Hard rules

- No code, pseudocode, formulas or recurrences. No `=` assignments.
- No expected values, outputs, counts or strings that the spec itself does not state.
- No identifiers (functions, classes, attributes, files, flags, keys) that do not appear
  in the instruction/spec. Backticked terms must be findable in the spec.
- Never mention tests, the grader, the verifier, pass rates or previous runs, not even
  obliquely ("often", "usually", "a common mistake", "tends to"): the agent has no history. The agent never sees the tests; speak only about the specification.
- No step-by-step fix list and no "the correct behaviour is V"; say where to look and
  what to check, so the agent still has to think.
- Never appeal to what a named project, its maintainers or "the real package" would write,
  and never ask the agent to recall a project's wording, names or tests from memory. Only
  the spec text and general engineering knowledge are legitimate sources.
- Do not point at a convention that uniquely determines a hidden identifier or value
  ("notice the abbreviation the spec uses for X", "look how the spec names Y"). You may say
  that unnamed attributes must follow conventions visible in the spec; you may not route
  the agent to the exact answer.
- 10–25 lines, second person ("make sure", "re-read", "watch out for"), plain Markdown,
  starting exactly with `## Supplementary Instruction`. Wrap at ~120 characters; a bullet is
  at most two wrapped lines; prefer cutting detail to compressing it. Return only that
  content.

## Calibration check before saving

Read your draft and ask: "Could an agent read this and still need to work out the
implementation?" If a sentence could be transcribed into code, soften it to the concept
or the spec pointer. Then ask: "Would this change what the failing runs did?" If a
sentence is generic advice that any task could carry, sharpen it with the spec section it
applies to here.

Save to `hints/<task>/hint.md`.
