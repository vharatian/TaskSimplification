# Stage 1 — Per-task, cross-run gap analysis

You are an expert software engineer diagnosing why an AI coding agent failed the same
Harbor task on EVERY one of its N independent attempts (pass@N = 0). Each attempt
started from an empty workspace, read the same instruction/spec, and built the project
from scratch; a hidden pytest suite ("golden tests") then graded the result.

Your input is `tasks/<task>/task_summary.md` (cross-run view) and, for drill-down, the
per-run bundles it points to (`bundle.md`, `failed_tests.md`, `file_inventory.md`,
`diffs/`, `trajectory.md`, `agent_commands.sh`).

## What to figure out

The question is NOT "what bug did run 3 have". It is: **what knowledge, skill or habit was
missing from the agent such that eight independent tries all fell short?** Separate:

1. **Consistent gaps** — golden tests that failed in every (or nearly every) run, with the
   same error signature. These point at missing domain knowledge, a misread spec
   requirement, or an API/behavioural convention the agent does not know.
2. **Process gaps** — things visible in the trajectories across runs: never ran the
   package's own smoke test, never re-read the spec section it was implementing, marked
   the task complete while its own commands still showed errors, spent the budget on
   scaffolding, repeated the same failing command, ignored a traceback, etc. Use the per-run
   columns in the Runs table (pytest cmds, py runs, spec reads, err steps, timed out).
3. **Incidental failures** — tests that failed in only some runs. Mention briefly; they are
   not the skill gap.

Procedure:
- Read task_summary.md fully. Note the "failed in EVERY run" tests, their error
  signatures, the verifier test source, and which oracle files are missing/different in
  all runs.
- Open at least two bundles (the best-reward run and one other). In `failed_tests.md`
  and the prioritized diffs, compare what the oracle does vs what the agent did for the
  consistently failing tests. Check `trajectory.md` for how the agent reasoned about that
  part of the spec and whether it ever tested it.
- Ask for each consistent failure: was the requirement stated in the instruction? If yes,
  did the agent read it and misinterpret it, or skip it? If no, what domain/library
  convention would a strong engineer have known (e.g. "pytest's `mock.assert_called_with`
  compares SQL strings byte-for-byte", "textual CSS variables must be declared", "argparse
  Namespace attributes come from `dest`, not the flag")?

## Output

Write `gap_analysis/<task>.json` with EXACTLY this shape (no extra prose outside the file):

```json
{
  "task": "<task folder name>",
  "n_runs": 8,
  "rewards": [0.98, 0.97, ...],
  "runs_timed_out": 0,
  "consistent_failures": [
    {
      "tests": ["tests.x::test_a", "tests.x::test_b"],
      "failed_in_runs": "8/8",
      "error_signature": "normalised exception line",
      "what_the_test_requires": "plain-English statement of the behaviour the verifier checks",
      "what_agents_did_instead": "what the runs implemented (common to the runs, not one run's bug)",
      "requirement_in_instruction": "quoted | implied | absent",
      "missing_knowledge": "the concept / convention / domain fact the agent lacked, stated generally",
      "evidence": ["bundle path + file:line or trajectory step that shows it", "..."],
      "severity": "critical | major | minor"
    }
  ],
  "process_gaps": [
    {
      "gap": "e.g. never executed the package's public entry point before marking complete",
      "seen_in_runs": "7/8",
      "evidence": ["trajectory step refs"],
      "consequence": "which consistent failures this plausibly let slip through"
    }
  ],
  "incidental_failures": ["one line each, with run count"],
  "what_agents_did_well": ["..."],
  "missing_skills": [
    {
      "skill": "short name of the reusable skill/knowledge (not task specific)",
      "domain": "e.g. python-packaging | pytest-mocking | CLI-arg-parsing | async | TUI/textual | data-serialisation | spec-reading | self-verification",
      "why_it_would_have_helped": "one or two sentences",
      "generality": "task-specific | repo-family | general"
    }
  ],
  "generalizable_lesson": "one paragraph that would help on SIMILAR future tasks"
}
```

Also write `gap_analysis/<task>.md`: a short human-readable version (headline, the
consistent failures with evidence, the process gaps, the missing skills).

Rules:
- Ground every claim in a bundle file or trajectory step you actually read; cite it.
- Distinguish "ran out of time" from "wrong approach" when runs timed out.
- Do not paste oracle code into the JSON; describe behaviour.
- If the always-failed set is empty, use the "failed in most runs" list and say so.
