---
name: harbor-skill-gen
description: >
  End-to-end: from a Data-OS / Harbor export of tasks with their failed terminus-2 runs
  (pass@N = 0) to tasks that ship general skills. Extracts all runs, analyses each task
  across its N attempts, clusters general patterns, writes SKILL.md + compact cards, injects
  a per-task environment/skills.md, patches Dockerfile + instruction, and emits a flat
  delivery folder with traceability. Use whenever the user has <task>/rev_*/task_files +
  evaluations/ folders (or any Harbor task + eval dirs) and asks to: find why pass@8 is 0,
  find the missing skill or domain knowledge across runs, compare trajectories/workspaces
  with the oracle, generate skills from failed runs, or build skill-injected tasks.
  Keywords: harbor, terminus, trajectory.json, tg_score, golden tests, oracle, pass@8,
  gap analysis, skill generation, nl2repo, GLM runs, skills.md.
---

# harbor-skill-gen — runbook

Stage 0 and Stages 4–5 are scripts. Stages 1–3 are done by Claude Code (you) reading the
extracted files and writing JSON/Markdown. No external LLM API, no network.

Core idea: for a task with pass@N = 0, analyse **all N trajectories and workspaces
together** and ask what knowledge or habit was missing from every attempt. Skills must be
GENERAL (transfer to unseen repos); task-specific findings are kept as one-off issues.

## Locating this skill's files

Everything needed ships next to this SKILL.md: `scripts/extract_gaps.py`,
`scripts/collect_gaps.py`, `scripts/check_skills.py`, `scripts/assemble_task_skills.py`,
`scripts/build_task_delivery.py`, `prompts/stage1_task_gap_analysis.md`,
`prompts/stage2_pattern_synthesis.md`, `prompts/stage3_skill_generation.md`.

```bash
for d in "$PWD/.claude/skills/harbor-skill-gen" "$HOME/.claude/skills/harbor-skill-gen"; do
  [ -f "$d/SKILL.md" ] && echo "$d" && break
done
```
Use that as `<skill_dir>`. Requirements: Python 3.8+ standard library only.

## Inputs to confirm with the user (ask only what is missing)

- `<export_root>`: folder of `<task>/rev_*/{task_files,evaluations}` (or explicit
  `--task-dir/--eval-dir` pairs). The skill does NOT download runs; they must be present.
- Model to analyse (`--model-filter`, e.g. `GLM-5.3`) when the export mixes models.
- Expected runs per task `N` (default 8 → `--expect-runs 8`).
- `<work_dir>` for analysis outputs and `<out_dir>` for the final tasks-with-skills folder.

## Stage 0 — extract (script)

```bash
python3 <skill_dir>/scripts/extract_gaps.py --delivery-dir <export_root> --model-filter <model> --expect-runs <N> -o <work_dir>
```
Writes `index.md`, `tasks/<task>/task_summary.md|json` (the cross-run Stage-1 input: per-run
table, tests failed in EVERY run with verifier source + trace, error signatures, files
missing vs oracle, trajectory digests) and `bundles/<task>__<trial>/` (per-run evidence).
All scored, non-passing runs are bundled; API/rate-limit runs never; timed-out runs are
flagged (`--exclude-timeouts` to drop).

**pass@N gate (mandatory).** Read the WARNINGS section at the top of `index.md`. If any
task has fewer than N scored runs, has passing runs, or has duplicate batches, STOP and ask
the user how to proceed for those tasks (skip them, include with fewer runs, include
passing runs with `--include-passed`, or obtain more runs). Only continue when the
warnings are resolved or explicitly accepted. Zero warnings → continue without asking.

## Stage 1 — per-task cross-run gap analysis (parallel subagents, mandatory)

One subagent per task, `general-purpose`, launched in parallel (batches of ~10 if there
are many). Do not analyse tasks yourself in the main context: summaries are 25–65 KB and
bundles up to 100 KB each. Prompt template (fill the placeholders):

```
You are performing Stage 1 of the harbor-skill-gen pipeline for ONE task. Read
<skill_dir>/prompts/stage1_task_gap_analysis.md first and follow it exactly.
Task: <task>   Work dir: <work_dir>
Input: <work_dir>/tasks/<task>/task_summary.md (read fully), then open at least two run
bundles listed in it (highest-reward run and one other): failed_tests.md, file_inventory.md,
bundle.md prioritized diffs, trajectory.md; open diffs/ files as needed.
[If task_summary shows 0 always-failed tests: say failures are inconsistent and use the
"failed in most runs" list.]
Output: <work_dir>/gap_analysis/<task>.json (exact schema from the prompt; must parse) and
<work_dir>/gap_analysis/<task>.md.
Focus on what ALL N runs got wrong in common and the missing knowledge/skill behind it; cite
bundle files and trajectory steps. Do not paste oracle code. Report a 5-line summary.
```
After all return: verify every JSON parses and has keys `task, n_runs, consistent_failures,
process_gaps, missing_skills, generalizable_lesson`; re-run a subagent for any malformed file.

## Stage 2 — cross-task pattern synthesis (you)

```bash
python3 <skill_dir>/scripts/collect_gaps.py <work_dir> --out <work_dir>/gap_digest.md          # ≤15 tasks
python3 <skill_dir>/scripts/collect_gaps.py <work_dir> --compact --out <work_dir>/gap_digest.md # >15 tasks
```
For more than ~30 tasks, synthesise hierarchically: subagents each digest a batch
(`--tasks ...`) into candidate patterns, then you merge. Follow
`prompts/stage2_pattern_synthesis.md` (generality gate; no benchmark gaming) →
`<work_dir>/pattern_synthesis.json` + `.md`. `tasks_affected` per pattern is the
task↔skill link used by every later stage; keep it accurate.

## Stage 3 — skills (parallel subagents)

One subagent per one or two patterns, in parallel. Template:

```
Stage 3 of harbor-skill-gen. Read <skill_dir>/prompts/stage3_skill_generation.md first and
follow it exactly, including the anti-hint self-check and the no-benchmark-gaming rule.
Work dir W = <work_dir>. Write pattern `<name>` -> W/skills/<name>/SKILL.md and
W/skills/<name>/CARD.md. Evidence: W/pattern_synthesis.json entry +
`python3 <skill_dir>/scripts/collect_gaps.py W --pattern <name>` + the relevant
W/gap_analysis/<task>.json files. Audience: an AI coding agent building a Python package
from a long spec in a sandbox, graded by a hidden pytest suite it never sees.
HARD RULES: fully general — no task/repo/module/class/function/test names, config keys, CLI
flags, literal error strings or file paths from the analysed tasks; never tell the agent to
recall a named upstream project's tests or wording. Do NOT write INDEX.md. Report paths,
line counts and what the anti-hint grep made you remove.
```
Then you write `<work_dir>/skills/INDEX.md` (one line per skill: name, kind, source tasks,
trigger summary; plus the one-off issues rejected as task-specific) and run:
```bash
python3 <skill_dir>/scripts/check_skills.py <work_dir>    # exit 1 = leak or benchmark-gaming phrasing; fix and re-run
```

## Stage 4 — delivery folder (script)

```bash
python3 <skill_dir>/scripts/build_task_delivery.py <work_dir> --delivery-dir <export_root> --out <out_dir>
```
Copies each analysed task's task files (no runs) flat into `<out_dir>/<task>/`, writes
`environment/skills.md` (related cards by phase + shared finish checklist), adds
`COPY skills.md /opt/skills.md` to the Dockerfile, appends the read-the-skills block to
`instruction.md`, refreshes `manifest.json` where present, and writes `MANIFEST.json`,
`TRACEABILITY.md|json` and `README.md`. Then run the hygiene check and fix anything it reports:
```bash
python3 <skill_dir>/scripts/check_delivery.py <out_dir> --expect-skills --fix   # strips author notes (FIX_NOTES*, NOTES*, TODO*, .DS_Store …), verifies skills.md / COPY / instruction pointer / manifest
```
Exit 0 is required before handing the folder over. Spot-check one task's Dockerfile,
instruction tail and skills.md.

## Stage 5 — report

Tell the user: tasks and runs analysed, warnings and how they were resolved, tasks with
consistent vs inconsistent failures, the patterns with task counts, the one-off issues,
skills written, leak-check result, and the delivery folder path. Everything is linked:
`gap_analysis/<task>.json` → `pattern_synthesis.json[tasks_affected]` → `skills/<pattern>/`
→ `<out_dir>/MANIFEST.json` + `TRACEABILITY.md`.

## Guardrails

- Never instruct the agent to recall or reproduce a named upstream project's tests,
  wording or code; skills infer only from the spec text, the sandbox and general practice.
- Skills are GENERAL, never hints: no identifiers from the analysed tasks. Stage 2 gate +
  Stage 3 self-check + `check_skills.py` must all pass. Task-specific findings go to
  `one_off_issues` (input for separate hint/SI generation).
- Ground every claim in a bundle file or trajectory step and cite it.
- Never modify the export folder; write only under `<work_dir>` and `<out_dir>`.
- Never ship author scratch files (FIX_NOTES*, NOTES*, TODO*) in a delivery; `check_delivery.py` must exit 0.
- Never skip the pass@N gate or the subagent fan-out to save time.
