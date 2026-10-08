# Stage 2 — Cross-task pattern synthesis

Input: every `gap_analysis/<task>.json` from Stage 1 (use `scripts/collect_gaps.py` to get a
compact digest, then open individual JSONs as needed).

Goal: find the RECURRING missing skills / knowledge / habits across tasks that a reusable
skill document could teach. A pattern must be general enough to help on unseen tasks of the
same kind (here: build-a-Python-package-from-spec tasks graded by hidden pytest suites).

Group by the `missing_skills[].domain` and `consistent_failures[].missing_knowledge`
fields first; then check `process_gaps` for shared habits (self-verification, spec reading,
completion criteria). Count tasks per pattern honestly.

## Generality gate (apply to every candidate pattern)

A pattern becomes a skill ONLY if all of these hold:
- **Transfers to unseen repos.** You can state it without naming any repo, module, class,
  function, test, CLI flag, config key, or error string from the analysed tasks. If the
  statement needs one of those to make sense, it is a hint, not a skill → `one_off_issues`.
- **Recurs or is clearly structural.** Seen in ≥2 tasks, OR it is a well-known engineering
  convention (e.g. "mock-based tests compare call arguments exactly", "a CLI's parsed
  attribute names follow `dest`") that any similar task could hit.
- **Teaches a method, not an answer.** The skill tells the agent how to *find out* the right
  behaviour (where to look in the spec, what to run, what property to assert) rather than
  what the right behaviour *was* for a given task.
- **Abstract to the level of the library/ecosystem, not the project.** "Textual CSS variables
  must be declared before use" (library-level, general) is fine; "define `$background1` in
  the theme" (project-level) is not.

- **Not an exploit of the benchmark.** A candidate that amounts to "recall the upstream
  project's tests/code/wording" is not a skill; it is memorisation. Drop it (or restate it as
  spec/sandbox-derived inference).


## Two kinds of skill (decide for every candidate)

- **Ecosystem skill**: knowledge about a third-party library, standard-library area, framework
  or protocol that the task DEPENDS ON (a database driver's type mapping, a web framework's
  status-code conventions, a tokenizer's behaviour on a new Python version, a CLI library's
  argument model). These are the most reusable: any task that pins the same dependency
  benefits. Analogy: "how networking works between serverless functions" is a skill; "the
  message format these two functions exchange in this project" is a hint.
- **Process skill**: a working habit for this task family (reading a long spec in a small
  terminal, verifying every clause). Keep at most 2-3 of these in the whole library.

Never make the package being rebuilt the subject of a skill. In NL2Repo the target package is
the answer; knowledge about it is a leak, however general it sounds. Ecosystem skills are about
its dependencies, never about it.

Record `"skill_kind": "ecosystem | process"` and, for ecosystem skills, `"applies_when"`: the
dependency names or spec features that make a task eligible. Stage 4 selects on these.

Record the decision per candidate: `"generality": "general | library-level | task-specific"`
and put only `general`/`library-level` ones in `patterns`. Everything task-specific goes to
`one_off_issues` — that list is the input for hint (SI) generation, not for skills.

Write `pattern_synthesis.json`:

```json
{
  "patterns": [
    {
      "pattern_name": "short-kebab-case-name",
      "title": "Human readable title",
      "kind": "domain-knowledge | library-convention | spec-reading | self-verification | process",
      "generality": "general | library-level",
      "abstract_statement": "one sentence with NO repo/module/function/test names",
      "description": "what keeps going wrong and why",
      "tasks_affected": ["task1", "task2"],
      "n_tasks": 2,
      "representative_evidence": ["task: one-line evidence", "..."],
      "skill_recommendation": "what the SKILL.md should teach (strategy, checks, pitfalls)"
    }
  ],
  "one_off_issues": [{"task": "...", "issue": "..."}],
  "priority_order": ["pattern_name1", "..."],
  "overall_assessment": "2-3 sentences on the agent's main weaknesses on this task family"
}
```

and `pattern_synthesis.md` with the same content as readable prose + a table
(pattern | kind | tasks | recommendation).
