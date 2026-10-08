# harbor-hint-gen — a Claude Code skill (gentle hints)

Companion to `harbor-skill-gen`. Where skills are general and shared across tasks, a hint is a
10–25 line **Supplementary Instruction** appended to ONE task's `instruction.md`: it points the
agent at the spec sections and concepts it kept misreading across all N failed runs and says what
to verify, without code, expected values, oracle identifiers, or any mention of tests.

Self-contained: Python 3.8+ standard library, no API keys. Claude Code writes and reviews the
hints via parallel subagents; scripts do extraction, input preparation, leak checking and delivery.

## Install
```bash
mkdir -p ~/.claude/skills && cp -r harbor-hint-gen ~/.claude/skills/harbor-hint-gen   # or <repo>/.claude/skills/
```

## Use
```
/harbor-hint-gen
Export with runs: <path>   Model: GLM-5.3   Runs per task: 8
Work dir: <path>   Tasks source for delivery: <export or tasks-with-skills folder>   Out: <path>
Hints only for tasks with no passing run.
```
Pipeline: extract (+pass@N gate) → per-task gap analysis (subagents; reused if present) →
hint inputs → hints (subagents) → review (subagents) → `check_hints.py` → `apply_hints.py` → report.

## Folder
```
SKILL.md                         runbook Claude Code loads
prompts/hint.md                  how to write a gentle hint
prompts/hint_review.md           reviewer pass (leakage / coverage / specificity / form)
prompts/stage1_task_gap_analysis.md   same Stage-1 prompt as harbor-skill-gen
scripts/extract_gaps.py          same extractor as harbor-skill-gen
scripts/prepare_hint_inputs.py   gap analysis → hints/<task>/hint_input.md
scripts/check_hints.py           automated leak/form check (exit 1 on findings)
scripts/apply_hints.py           hint → instruction.md, flat delivery folder, MANIFEST.json
scripts/check_delivery.py        delivery hygiene: strips author notes / stray files, verifies hint placement (+skills if stacked) and manifest
```

## Notes
- Strong/escalated hints (after a gentle hint fails) are intentionally not included yet.
- `check_hints.py` compares the hint against the task's instruction/spec (public), the oracle
  (private identifiers) and the verifier tests (private literals); anything private that shows up
  in the hint is a finding.
