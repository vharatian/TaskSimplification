# harbor-skill-gen — a Claude Code skill

Turns FAILED Harbor / terminus-2 agent runs into **general, reusable SKILL.md skills** by
analysing all attempts of each task together (the pass@N = 0 view) and comparing agent
trajectories and workspaces with the oracle solution.

Self-contained: one folder, Python 3.8+ standard library only, no API keys. Claude Code
performs the analysis stages itself by reading the extracted files.

## Install

**User-level (available in every project):**
```bash
mkdir -p ~/.claude/skills
cp -r harbor-skill-gen ~/.claude/skills/harbor-skill-gen     # or unzip harbor-skill-gen.zip there
```

**Project-level (shared via the repo):**
```bash
mkdir -p <repo>/.claude/skills
cp -r harbor-skill-gen <repo>/.claude/skills/harbor-skill-gen
```

Start (or restart) Claude Code in the project; the skill appears in the skills list.

## Use

In Claude Code:
```
/harbor-skill-gen generate skills from the failed runs in <path-to-export>
```
or simply ask: *"find the missing skill behind the pass@8 = 0 runs in `<export>`"* — the
skill's description triggers on Harbor / terminus / trajectory / gap-analysis requests.

Claude will:
0. run `scripts/extract_gaps.py` (deterministic, ~1 min per 80 runs) and STOP to ask you if any
   task does not have the expected N scored, non-passing runs (pass@N gate),
1. write `gap_analysis/<task>.json` per task from the cross-run summaries (one subagent per
   task, in parallel),
2. cluster into general patterns with a generality gate (Stage 2),
3. write `skills/<pattern>/SKILL.md` + `CARD.md` + `skills/INDEX.md` (parallel subagents) and
   run the leak check,
4. run `scripts/build_task_delivery.py`: flat copy of the tasks (no runs) with
scripts/check_delivery.py        delivery hygiene: strips author notes / stray files, verifies skills+hints structure and manifest (exit 1 on findings)
   `environment/skills.md`, Dockerfile `COPY skills.md /opt/skills.md`, instruction block,
   manifest refresh, `MANIFEST.json` + `TRACEABILITY.md`,
5. report. Any number of tasks; >15 tasks uses the compact digest, >30 a hierarchical Stage 2.

The skill does not download runs from Data-OS; start from an export folder that already
contains them.

You can also run the extractor by hand:
```bash
python3 scripts/extract_gaps.py --delivery-dir <export_root> -o <work_dir> [--model-filter GLM-5.3] [--tasks a b] [--exclude-timeouts]
python3 scripts/extract_gaps.py --help      # size caps and selection flags
python3 scripts/collect_gaps.py <work_dir>  # digest of Stage-1 JSONs (after Stage 1)
python3 scripts/check_skills.py <work_dir>  # after Stage 3: fail if any task identifier leaked into a skill
```

## Expected input layout

Data-OS "task with runs" export (default):
```
<export_root>/<task>/rev_N__<id>/
  task_files/   instruction.md, task.toml, solution/oracle/, tests/assets/scaffold/tests/, tests/assets/golden_nodeids.json
  evaluations/eval_<id>__attempt_<k>__<agent>__<model>/eval_files/
      result.json, verifier/{reward.json,tg_score.json,report.xml,test-stdout.txt,ctrf.json},
      agent/trajectory.json, artifacts/workspace/ or artifacts/workspace.tar.gz
```
Any Harbor task + eval pair also works: `--task-dir <task_files> --eval-dir <eval_dir>` (repeatable).

## Output layout (`<work_dir>`)

```
index.md / index.json                 every run, which were bundled, one row per task summary
tasks/<task>/task_summary.md|json     Stage-1 input: per-run table, tests failed in EVERY run (+ verifier
                                      source + representative trace), error signatures, files missing vs
                                      oracle across runs, per-run trajectory digests
bundles/<task>__<trial>/              per-run evidence: bundle.md, failed_tests.md, file_inventory.md,
                                      diffs/*.diff (oracle -> agent), trajectory.md, agent_commands.sh
gap_analysis/<task>.json|md           Stage 1 (written by Claude)
gap_digest.md, pattern_synthesis.json|md   Stage 2
skills/<pattern>/SKILL.md + CARD.md, skills/INDEX.md  Stage 3
<flat_tasks_dir>/<task>/environment/skills.md     assemble_task_skills.py (optional injection step)
```

## Folder contents

```
SKILL.md                          what Claude Code loads
scripts/extract_gaps.py           Stage 0 extraction
scripts/collect_gaps.py           Stage-1 digest for Stages 2/3
scripts/check_skills.py           leak check: greps skills for task identifiers (exit 1 on hit)
scripts/assemble_task_skills.py   per-task environment/skills.md from the skills' CARD.md files
scripts/build_task_delivery.py    Stage 4: flat task copy + skills.md + Dockerfile/instruction/manifest + traceability
prompts/stage1_task_gap_analysis.md
prompts/stage2_pattern_synthesis.md
prompts/stage3_skill_generation.md
README.md
```

## Design notes

- Stage 1 is per TASK across all its runs, not per run: with pass@8 = 0 the signal is what
  every attempt got wrong in common (missing domain knowledge, misread spec, missing habit
  such as never running the package before marking complete).
- Skills must be general. Stage 2 rejects anything that cannot be stated without repo /
  module / function / test names; Stage 3 greps drafts for such identifiers. Task-specific
  findings land in `one_off_issues` for separate hint (SI) generation.
- Runs that died on API or rate-limit errors are never bundled; timed-out runs are bundled
  but flagged (`--exclude-timeouts` to drop them).
- Agent tarballs often carry a `workspace/` prefix; the extractor aligns agent and oracle
  trees by maximising path overlap.
- Per-test tracebacks come from the JUnit `report.xml`; `test-stdout.txt` can be truncated.

## Troubleshooting

- *"no runs found"* — check the export root contains `<task>/rev_*/evaluations/`, or pass
  explicit `--task-dir/--eval-dir` pairs.
- *always-failed set is empty for a task* — its failures are inconsistent across runs; Stage 1
  will use the "failed in most runs" list and say so.
- *`ws=NO` in the extractor log* — that run has no workspace artifact; diffs are skipped and
  the analysis relies on tests + trajectory.
- Bundles are large (task summaries 25–65 KB, bundles up to ~100 KB); run Stage 1 with one
  subagent per task.
