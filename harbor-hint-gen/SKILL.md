---
name: harbor-hint-gen
description: >
  Generate gentle, task-specific hints (Supplementary Instructions) for Harbor / terminus-2
  tasks an agent keeps failing (pass@N = 0), from the cross-run gap analysis of all N runs,
  and write them into each task's instruction.md in a flat delivery folder. Companion to
  harbor-skill-gen: skills are general, hints are per task and point the agent at the spec
  sections and concepts it misread, without giving away the solution. Use whenever the user
  asks for hints, SI, supplementary instructions, nudges, or "help the agent pass this task"
  on a Data-OS export of tasks with runs. Keywords: hint, SI, supplementary instruction,
  harbor, terminus, pass@8, gap analysis, nl2repo, GLM runs.
---

# harbor-hint-gen — runbook (gentle hints only)

Stages 0, 2, 5 and 6 are scripts; Stages 1, 3 and 4 are done by Claude Code via parallel
subagents. No external LLM API, no network. A hint is 10–25 lines appended to the task's
instruction.md under `## Supplementary Instruction`: spec pointers, relevant concepts, the
category of trap previous runs fell into, and what to verify. Never code, values,
identifiers absent from the spec, or any mention of tests. The agent must still think.

## Locating this skill's files

Next to this SKILL.md: `scripts/extract_gaps.py` (same as harbor-skill-gen),
`scripts/prepare_hint_inputs.py`, `scripts/check_hints.py`, `scripts/apply_hints.py`,
`prompts/stage1_task_gap_analysis.md`, `prompts/hint.md`, `prompts/hint_review.md`.
```bash
for d in "$PWD/.claude/skills/harbor-hint-gen" "$HOME/.claude/skills/harbor-hint-gen"; do
  [ -f "$d/SKILL.md" ] && echo "$d" && break
done
```
Python 3.8+ standard library only.

## Inputs to confirm (ask only what is missing)

- `<export_root>`: `<task>/rev_*/{task_files,evaluations}` with the runs to learn from
  (use the most recent runs, e.g. the skills-injected re-run if one exists).
- `--model-filter`, expected runs `N` (default 8), `<work_dir>`, `<out_dir>`.
- `<tasks_src>` for the delivery: the export itself, or a flat folder of already-prepared
  tasks (e.g. the tasks-with-skills delivery) so hints stack on top of skills.
- Which tasks: default = tasks with no passing run (`--only-zero-pass`).

## Stage 0 — extract + pass@N gate (script)

```bash
python3 <skill_dir>/scripts/extract_gaps.py --delivery-dir <export_root> --model-filter <model> --expect-runs <N> -o <work_dir>
```
Read the WARNINGS block in `<work_dir>/index.md`. Tasks with passing runs do not need a
hint; tasks with fewer than N runs: ask the user whether to proceed. Skip this stage if
`<work_dir>` already holds a current extraction.

## Stage 1 — per-task gap analysis (parallel subagents; skip if already present)

If `<work_dir>/gap_analysis/<task>.json` exists for the tasks in scope and was produced
from these runs, reuse it. Otherwise one `general-purpose` subagent per task, in parallel,
with this prompt (fill placeholders):
```
You are performing Stage 1 of the harbor pipeline for ONE task. Read
<skill_dir>/prompts/stage1_task_gap_analysis.md first and follow it exactly.
Task: <task>   Work dir: <work_dir>
Input: <work_dir>/tasks/<task>/task_summary.md (read fully), then at least two run bundles
it lists (highest-reward run and one other): failed_tests.md, file_inventory.md, bundle.md
diffs, trajectory.md. Output: <work_dir>/gap_analysis/<task>.json (exact schema; must parse)
and <work_dir>/gap_analysis/<task>.md. Focus on what ALL N runs got wrong in common; cite
evidence; do not paste oracle code. Report a 5-line summary.
```
Verify each JSON parses and has `consistent_failures`, `process_gaps`, `missing_skills`.

## Stage 2 — hint inputs (script)

```bash
python3 <skill_dir>/scripts/prepare_hint_inputs.py <work_dir> --only-zero-pass [--tasks ...]
```
Writes `<work_dir>/hints/<task>/hint_input.md`: consistent-failure clusters (what the spec
requires / what runs did / is it stated / missing knowledge), process gaps, one-off
findings, a spec heading index, and a never-quote background block.

## Stage 3 — write hints (parallel subagents, one per task)

```
Write the Supplementary Instruction for ONE task. Read <skill_dir>/prompts/hint.md first and
follow it exactly. Task: <task>. Inputs: <work_dir>/hints/<task>/hint_input.md, the task's
instruction.md / environment/spec.md (open the sections the clusters point to),
<work_dir>/gap_analysis/<task>.md. You may read solution/oracle to understand, never quote.
Output: <work_dir>/hints/<task>/hint.md, 10-25 lines, starting '## Supplementary
Instruction'. Hard rules: no code, values, identifiers or strings absent from the spec; never
mention tests/graders/runs; cover every cluster; the agent must still have to think. Report
the hint text back verbatim.
```

## Stage 4 — review (parallel subagents, one per hint, different from the writer)

```
Review the Supplementary Instruction for ONE task. Read <skill_dir>/prompts/hint_review.md
and follow it exactly. Task: <task>. Files: <work_dir>/hints/<task>/hint.md, hint_input.md,
the task's instruction.md. Write hint_review.json; overwrite hint.md only if you changed it.
Report verdict and what you changed.
```

## Stage 5 — automated leak check (script)

```bash
python3 <skill_dir>/scripts/check_hints.py <work_dir>     # exit 1 on findings
```
Fix every finding (edit the hint yourself; re-run). Identifiers that ARE in the spec but
the checker misses can be allow-listed with `--allow`; never allow-list oracle-only names.

## Stage 6 — apply (script)

```bash
python3 <skill_dir>/scripts/apply_hints.py <work_dir> --tasks-src <tasks_src> --out <out_dir>
```
Copies each hinted task's files (no runs) flat into `<out_dir>/<task>/`, appends or
replaces the `## Supplementary Instruction` section of `instruction.md`, refreshes
`manifest.json` where present, writes `MANIFEST.json` + `README.md`. Then:
```bash
python3 <skill_dir>/scripts/check_delivery.py <out_dir> --expect-hints [--expect-skills] --fix   # strips author notes, verifies SI placed once and last, skills intact if stacked, manifest consistent
```
Exit 0 is required before handing the folder over.

## Stage 7 — report

Tasks hinted, the clusters each hint addresses, review verdicts, leak-check result,
delivery path, and tasks skipped (passing runs / too few runs). Show each hint text.

## Guardrails

- A hint is task-specific by design, but solution-free: where to look and what to verify,
  never what the answer is. If the agent could transcribe a sentence into code, soften it.
- Never mention tests, the grader, or previous runs' outputs; the agent only has the spec.
- Never quote or name oracle-only identifiers; `check_hints.py` must pass.
- Strong / escalated hints are out of scope for this skill.
- Never modify the export; write only under `<work_dir>` and `<out_dir>`.
- Never ship author scratch files (FIX_NOTES*, NOTES*, TODO*) in a delivery; `check_delivery.py` must exit 0.
