# Skill and hint generation for NL2Repo: design notes

Working notes for the GLM-5.3 difficulty-band experiment: take tasks GLM-5.3 scores 0/8 on,
add skills (round 1) and, for tasks still outside 1-6/8, hints (round 2).

## What changed from the received pipeline

1. **Separate skills, delivered natively.** The received pipeline merged every skill into one
   `environment/skills.md` and told the agent to read it. Harbor already supports Agent Skills:
   a task sets `[environment] skills_dir`, and terminus-2 lists each `<name>/SKILL.md` by name and
   description in its prompt, so the agent opens only what it judges relevant.
   `scripts/build_skills_dir.py` builds that layout.
2. **Two kinds of skill.**
   - *Ecosystem skills* hold knowledge about what a task depends on: a database driver's type
     mapping, a web framework's conventions, a tokenizer's behaviour on a new Python version.
     These transfer to any task with the same dependency.
   - *Process skills* are general working habits (reading a long spec in a small terminal,
     verifying every clause). Keep only a few.
   - The package being rebuilt is never a skill's subject. On NL2Repo it is the answer. The
     builder refuses a skill that names the task's own target package.
3. **2-3 skills per task, chosen before running.** Selection (`prompts/stage4_skill_selection.md`)
   uses only what the agent sees: instruction, spec, dependency pins. It never uses the task's
   runs or tests.
4. **Fixed bugs and weak checks.** See the second commit: a crash in `collect_gaps.py`, leak
   checks that missed dotted names, single-digit values and oracle identifiers, and a hint-input
   label that pushed writers to leak.
5. **Hints aim low.** Hints address only the top one or two shared failures. The target is 1-6
   of 8 passing; 8/8 makes the task useless for the band.

## Why (short research summary)

- A few focused skills beat many. In SkillsBench, 2-3 skills gave +18.6pp, 4 or more gave
  +5.9pp, and "comprehensive" bundles were below baseline. Software engineering gained least,
  at +4.5pp.
- Selection matters. Tool-selection accuracy was 13.6% with everything in the prompt and 43.1%
  with retrieval first. Accuracy also drops past a critical library size, mostly because of
  near-duplicate skills.
- Short, abstracted lessons transfer. Summaries of about 200 tokens beat full trajectories,
  and subtask-level lessons beat instance-level memory.
- Agents copy what they retrieve, so an over-specific skill spreads its errors and leaks
  answers. That is why the target-package gate and the selection rule above exist.

Numbers come from 2025-26 preprints read at summary level. Verify them before external use.

## Experiment design

| Arm | Skills per task | Purpose |
|---|---|---|
| A. baseline | none (existing 0/8 runs) | reference |
| B. matched | 2-3 selected | the treatment |
| C. full library | all (`--all-skills`) | does extra noise hurt? |

- Same model, harness, timeout (3600 s) and 8 runs per task in every arm.
- Report per-task pass counts, how many tasks got worse, and token cost.
- From the transcripts, count whether each skill was actually opened; a skill present but never
  read cannot explain an improvement.
- Honest uplift needs held-out tasks: mine skills on one set of tasks and test on another, or
  rebuild the library leaving each task out. Mining from a task's own runs and testing on that
  task overstates the effect.

## Open questions for the next round

- Do ecosystem skills get opened by GLM-5.3 at all? Check the transcripts before writing more of them.
- Pin the Harbor version on Data-OS. `skills_dir` and `schema_version` need a recent Harbor
  (verified locally on 0.21.0).
- Round 2 hints should be mined from the round-1 runs, not the original runs; the failures move.
