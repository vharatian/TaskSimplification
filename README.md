# nl2repo-skillgen

Skill (round 1) and hint (round 2) generation for Harbor NL2Repo tasks, driven by Claude Code:
the scripts are deterministic Python (stdlib only, no API keys) and the analysis and writing
stages are done by Claude Code subagents following the prompts.

- `harbor-skill-gen/`: failed runs -> gap analysis -> general skills -> per-task skills_dir
- `harbor-hint-gen/`: gap analysis -> short task-specific Supplementary Instruction
- `DESIGN.md`: what changed from the received version, why, and the experiment design

History: the first commit is the pipeline as received; later commits are the changes.

Quick start (Claude Code, from this repo):
```
/harbor-skill-gen export: <path to Data-OS export with runs>  model: GLM-5.3  runs per task: 8
```
