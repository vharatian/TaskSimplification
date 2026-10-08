# Stage 3 — SKILL.md generation

For each pattern in `pattern_synthesis.json` (in `priority_order`), write
`skills/<pattern_name>/SKILL.md`. Use the pattern entry plus the supporting
`gap_analysis/<task>.json` files for its `tasks_affected`.

The SKILL.md is for an AI coding agent that will face SIMILAR but NOT IDENTICAL tasks
(build a Python project from a natural-language spec; hidden pytest grading). It must:

1. Start with YAML frontmatter:
   ```
   ---
   name: <Title Case name>
   description: >
     <"pushy" trigger text: when to use it, concrete keywords and contexts so the agent
      actually loads it — e.g. "whenever the spec mentions …", "before marking a packaging
      task complete", "if tests mock a DB cursor …">
   ---
   ```
2. **General strategy** — the approach, not task steps.
3. **Common pitfalls** — table: what goes wrong | how to recognise it | how to avoid it.
   Each row should trace back to a real failure in the gap analyses, stated generally.
4. **Verification checklist** — concrete checks the agent can run before declaring done
   (commands to run, properties to assert, spec sections to re-read).
5. **Diagnostic patterns** — "if you see X in your output / tests, it means Y".

Rules:
- Never include oracle code, repo-specific function names, class names, test names, config
  keys, CLI flags, error strings, or file paths from the analysed tasks. Describe
  behaviours and conventions at the level of the language/library/ecosystem.
- A skill must be usable on a task whose repo you have never seen. Every bullet should
  read as "when you face a situation of type X, do Y and check Z" — never "the correct
  value is V" or "implement W".
- Prefer teaching *how to discover* the requirement (which spec sections to re-read, which
  command to run, which property to assert, how to read a mock-assertion diff) over
  stating the requirement.
- **No benchmark gaming.** Never instruct the agent to recall, reproduce or guess a named
  upstream project's source, tests, wording or conventions from memory, or to treat "the
  hidden suite is that project's own tests" as a strategy. Skills must work when the upstream
  is unknown: infer only from the spec text, the sandbox (installed packages, pinned test
  tooling, library signatures) and general engineering practice. Say "a maintainer-style test
  suite", never "the upstream project's suite".
- Be concrete and actionable; avoid generic advice ("be careful").
- Keep it under ~150 lines.

## Also write a compact card: `skills/<pattern_name>/CARD.md`

Same content, condensed to 15-30 lines for injection into a task's `environment/skills.md`
(the agent reads it through a 40-row terminal, so brevity matters). Format:

```
---
phase: read | implement | verify | finish      # when in the workflow the skill applies
title: <short imperative title>
---
**Rule:** one or two sentences.
Do: 4-8 bullets.  Don't: 1-3 bullets.
If you see: 3-5 "<symptom> -> <cause/fix>" items in one short paragraph.
```
No tables (they wrap badly in a terminal). Same anti-hint rules as the SKILL.md.
`scripts/assemble_task_skills.py <work_dir> <tasks_dir>` turns the cards into per-task files.

## Anti-hint self-check (run before saving each SKILL.md and CARD.md)

1. grep your draft for every identifier that appears in the supporting gap analyses
   (task names, module/class/function/test names, config keys, literal error messages).
   Any hit → rewrite that line generically or delete it.
2. Read each pitfall row and ask: "would this row make sense to an agent working on a
   different repo in the same ecosystem?" If not, generalise or drop it.
3. Ask: "does any sentence give away *what the answer was* rather than *how to find it*?"
   If yes, rewrite as a method.
3b. grep for `upstream`, `named open-source`, `re-implements a named`, `you remember`,
   `canonical wording`: any hit that leans on knowledge of the specific upstream project is
   benchmark gaming → delete or rewrite to spec/sandbox-derived inference.
4. If after the self-check the skill has fewer than two substantive pitfalls, the pattern
   was not general enough: do not write the skill; record it under `skills/INDEX.md` →
   "rejected as task-specific" with the reason.
- After writing all skills, write `skills/INDEX.md`: one line per skill (name, trigger
  summary, tasks it came from) and a short note on patterns judged too task-specific to
  become skills.
