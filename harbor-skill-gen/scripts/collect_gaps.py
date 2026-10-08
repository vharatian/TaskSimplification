#!/usr/bin/env python3
"""
collect_gaps.py — compact digest of Stage-1 gap analyses for Stage 2 / Stage 3.

  python collect_gaps.py <work_dir>                     # digest of all gap_analysis/*.json -> stdout
  python collect_gaps.py <work_dir> --pattern <name>    # only tasks listed in pattern_synthesis.json for that pattern
  python collect_gaps.py <work_dir> --out digest.md     # write instead of print
"""
import argparse, json, sys
from pathlib import Path


def digest_one(g: dict) -> str:
    out = [f"## {g.get('task')}  (runs={g.get('n_runs')}, rewards={g.get('rewards')}, timed_out={g.get('runs_timed_out')})"]
    for cf in g.get("consistent_failures", []):
        out.append(f"- **[{cf.get('severity')}] {cf.get('failed_in_runs')}** `{cf.get('error_signature', '')[:100]}`")
        out.append(f"  - requires: {cf.get('what_the_test_requires')}")
        out.append(f"  - agents did: {cf.get('what_agents_did_instead')}")
        out.append(f"  - in instruction: {cf.get('requirement_in_instruction')} | missing knowledge: {cf.get('missing_knowledge')}")
    if g.get("process_gaps"):
        out.append("- process gaps: " + "; ".join(f"{p.get('gap')} ({p.get('seen_in_runs')})" for p in g["process_gaps"]))
    if g.get("missing_skills"):
        out.append("- missing skills: " + "; ".join(f"[{s.get('domain')}] {s.get('skill')} ({s.get('generality')})" for s in g["missing_skills"]))
    out.append(f"- lesson: {g.get('generalizable_lesson')}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--pattern", help="pattern_name from pattern_synthesis.json; restrict to its tasks_affected")
    ap.add_argument("--out")
    ap.add_argument("--compact", action="store_true", help="missing skills + lesson only (for >15 tasks)")
    ap.add_argument("--tasks", nargs="*", help="restrict to these tasks (batching for large sets)")
    a = ap.parse_args()
    wd = Path(a.work_dir)
    files = sorted((wd / "gap_analysis").glob("*.json"))
    if not files:
        sys.exit(f"no gap_analysis/*.json under {wd}")
    gaps = []
    for f in files:
        try:
            gaps.append(json.loads(f.read_text()))
        except Exception as e:
            print(f"[warn] {f.name}: {e}", file=sys.stderr)
    if a.tasks:
        gaps = [g for g in gaps if g.get("task") in set(a.tasks)]
    if a.compact:
        def digest_compact(g):
            out = [f"## {g.get('task')}  (runs={g.get('n_runs')}, rewards={g.get('rewards')})"]
            out += [f"- [{s.get('domain')}] {s.get('skill')} ({s.get('generality')})" for s in g.get("missing_skills", [])]
            out.append(f"- lesson: {g.get('generalizable_lesson')}")
            return "\n".join(out)
    fmt = digest_compact if a.compact else digest_one
    if a.pattern:
        ps = json.loads((wd / "pattern_synthesis.json").read_text())
        pat = next((p for p in ps.get("patterns", []) if p.get("pattern_name") == a.pattern), None)
        if not pat:
            sys.exit(f"pattern {a.pattern} not found")
        keep = set(pat.get("tasks_affected", []))
        gaps = [g for g in gaps if g.get("task") in keep]
        head = [f"# Pattern: {pat.get('title')} ({a.pattern})", pat.get("description", ""), f"Recommendation: {pat.get('skill_recommendation', '')}", ""]
    else:
        head = [f"# Gap digest — {len(gaps)} tasks", ""]
    # domain tally
    tally = {}
    for g in gaps:
        for s in g.get("missing_skills", []):
            tally[s.get("domain", "?")] = tally.get(s.get("domain", "?"), 0) + 1
    head.append("Missing-skill domains (count across tasks): " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])))
    head.append("")
    text = "\n".join(head + [fmt(g) + "\n" for g in gaps])
    if a.out:
        Path(a.out).write_text(text)
        print(f"wrote {a.out} ({len(text)} chars)")
    else:
        print(text)


if __name__ == "__main__":
    main()
