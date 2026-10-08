#!/usr/bin/env python3
"""
prepare_hint_inputs.py — build hints/<task>/hint_input.md from Stage-1 gap analyses.

  python prepare_hint_inputs.py <work_dir> [--tasks t1 t2 ...] [--only-zero-pass]

Reads <work_dir>/gap_analysis/<task>.json, tasks/<task>/task_summary.json (+ .md path),
pattern_synthesis.json (optional, for one_off_issues) and the task's instruction/spec
(for a heading index) and writes a compact, hint-writer-oriented input per task.
Test ids and error signatures are included under a "background, never quote" block.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path


def headings(path: Path, limit: int = 120) -> list[str]:
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if re.match(r"^#{1,4} ", line) or re.match(r"^\d+\.\s+\S", line) and len(line) < 100:
            out.append(f"L{i}: {line.strip()[:110]}")
        if len(out) >= limit:
            out.append("… (truncated)"); break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir"); ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--only-zero-pass", action="store_true", help="skip tasks that have a run with reward 1.0")
    a = ap.parse_args()
    W = Path(a.work_dir).resolve()
    syn = json.loads((W / "pattern_synthesis.json").read_text()) if (W / "pattern_synthesis.json").exists() else {}
    one_offs = syn.get("one_off_issues", [])
    files = sorted((W / "gap_analysis").glob("*.json"))
    if a.tasks:
        files = [f for f in files if f.stem in set(a.tasks)]
    written = []
    for f in files:
        g = json.loads(f.read_text()); task = g["task"]
        if a.only_zero_pass and any((r or 0) >= 1.0 for r in g.get("rewards", [])):
            print(f"  skip {task}: has a passing run"); continue
        ts_path = W / "tasks" / task / "task_summary.json"
        ts = json.loads(ts_path.read_text()) if ts_path.exists() else {}
        task_dir = None
        if ts.get("runs"):
            b = Path(ts["runs"][0]["bundle_dir"]) / "bundle.json"
            if b.exists():
                task_dir = Path(json.loads(b.read_text())["task_dir"])
        out = W / "hints" / task; out.mkdir(parents=True, exist_ok=True)
        md = [f"# Hint input: {task}", "",
              f"- runs: {g.get('n_runs')} | rewards: {g.get('rewards')} | timed out: {g.get('runs_timed_out')}",
              f"- task dir: `{task_dir}`  (instruction.md, environment/spec.md, solution/oracle/ — oracle may be read, never quoted)",
              f"- gap analysis: `{f.with_suffix('.md')}` | cross-run summary: `{W / 'tasks' / task / 'task_summary.md'}`", "",
              "## Consistent failures (hint ONLY the top one or two by run count; leave the rest)", ""]
        for i, cf in enumerate(g.get("consistent_failures", []), 1):
            md += [f"### Cluster {i} — {cf.get('failed_in_runs')} runs, severity {cf.get('severity')}",
                   f"- **The graded behaviour (spec status: {cf.get('requirement_in_instruction')}):** {cf.get('what_the_test_requires')}",
                   f"- **The runs did instead:** {cf.get('what_agents_did_instead')}",
                   f"- **Requirement in instruction:** {cf.get('requirement_in_instruction')}",
                   f"- **Missing knowledge:** {cf.get('missing_knowledge')}", ""]
        md += ["## Process gaps across runs", ""] + [f"- {p.get('gap')} ({p.get('seen_in_runs')}) → {p.get('consequence')}" for p in g.get("process_gaps", [])] + [""]
        mine = [o for o in one_offs if o.get("task") == task]
        md += ["## Task-specific findings (from pattern synthesis one_off_issues)", ""] + ([f"- {o.get('issue')}" for o in mine] or ["- (none recorded)"]) + [""]
        md += ["## Missing skills (for context)", ""] + [f"- [{s.get('domain')}] {s.get('skill')}: {s.get('why_it_would_have_helped')}" for s in g.get("missing_skills", [])] + [""]
        md += ["## Generalizable lesson", "", str(g.get("generalizable_lesson", "")), ""]
        if task_dir:
            md += ["## Spec heading index (point the agent at sections by heading, not line number)", ""]
            hs = headings(task_dir / "instruction.md")
            spec = task_dir / "environment" / "spec.md"
            if spec.exists() and len(hs) < 10:
                hs = headings(spec)
            md += hs or ["(no headings found)"]
            md.append("")
        md += ["## Background — never quote in the hint (test ids, error text)", ""]
        for cf in g.get("consistent_failures", []):
            md.append(f"- tests: {cf.get('tests')} | signature: `{cf.get('error_signature', '')[:120]}`")
        md += ["", "## Rules (summary; full text in prompts/hint.md)", "",
               "- 10-25 lines, starts with `## Supplementary Instruction`, second person.",
               "- No code, values, identifiers or strings absent from the spec; never mention tests/graders/runs.",
               "- Point to spec sections and concepts; say what to verify; only the top one or two clusters."]
        (out / "hint_input.md").write_text("\n".join(md) + "\n")
        written.append(task); print(f"  {task:38s} clusters={len(g.get('consistent_failures', []))} → {out / 'hint_input.md'}")
    print(f"prepared {len(written)} hint inputs under {W / 'hints'}")


if __name__ == "__main__":
    main()
