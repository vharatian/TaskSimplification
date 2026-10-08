# Hint review — one task

You are reviewing a Supplementary Instruction written for an AI coding agent. Decide
whether it is (a) solution-free and (b) specific enough to change behaviour, and fix it.

Read: `hints/<task>/hint.md`, `hints/<task>/hint_input.md`, the task's `instruction.md`.

Check, sentence by sentence:
1. **Leakage.** Does it state what the implementation IS (a value, a structure, a name,
   an algorithm step) rather than where to look or what to verify? Does it use any
   identifier, literal or number absent from the spec? Does it mention tests, graders or
   run outputs? Any yes → rewrite that sentence to a concept or a spec pointer.
2. **Strength.** Does it address only the top one or two clusters? If it covers more,
   remove the weaker ones: the target is 1-6 out of 8 passing, not 8 out of 8.
3. **Specificity.** Is any sentence so generic it could be pasted into another task?
   Anchor it to a spec section or clause of this task, or delete it.
4. **Form.** Starts with `## Supplementary Instruction`; 10–25 non-empty lines wrapped at
   ~120 characters; second person; no code fences; no bullet longer than two wrapped lines.
5. **No memorisation appeals.** Any sentence that leans on what a named project / its
   maintainers / "the real package" would write or name, or that routes the agent to a
   hidden identifier via a uniquely determining convention pointer, is removed or rewritten
   to spec-derivable reasoning.
6. **Automated findings.** Resolve every item in `hints/<task>/hint_check.json` if present
   (false positives such as common English words matching a literal may be noted as such).

Output:
- `hints/<task>/hint_review.json`:
  `{"verdict": "ok | revised | rejected", "leakage_fixes": [...], "coverage_added": [...],
    "generic_removed": [...], "notes": "..."}`
- If anything changed, overwrite `hints/<task>/hint.md` with the revised version.
