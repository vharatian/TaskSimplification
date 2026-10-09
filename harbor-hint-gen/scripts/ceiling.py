#!/usr/bin/env python3
"""
ceiling.py — how far is each zero-pass task from the target pass count, and what should its hint cover?

A run passes only when every graded test passes. Near-miss tasks often fail on scattered,
run-specific slips rather than one shared bug, so "best reward 0.98" says little about whether
a hint can make the task pass. This script answers that from the historic runs:

  for each task, k = the smallest number of failing test families such that, if all of them were
  fixed, at least --passes historic runs would have passed completely. Computed exactly: the
  smallest union of failure sets over any --passes runs (no tie-breaking involved).

Small k (1-5): a light, calibrated hint can plausibly lift the task into the band.
Large k (10+): the failures are scattered; hints would have to give answers. Pick other tasks.

It also writes the hint targets: exactly those k families per task (plus the next few, which the
hint must NOT cover, so the task does not become too easy).

  python ceiling.py --delivery-dir <export_root> --model-filter GLM-5.3 [--passes 2] [--min-runs 8]
                    [--tasks t1 t2 ...] [--exclude-file known_issues.json] [--out hint_targets.json]

Reads <export_root>/<task>/rev_*/evaluations/<eval>/eval_files/verifier/tg_score.json
(failed_golden_ids, reward, integrity). Runs with integrity != ok (fail-closed, unparseable) are
skipped: they say nothing about which tests a working build fails.
"""
from __future__ import annotations

import argparse, collections, itertools, json, sys
from pathlib import Path


def family(nodeid: str) -> str:
    """Test family: the node id without its parameter suffix."""
    return nodeid.split("[", 1)[0]


def load_runs(task_dir: Path, model_filter: str | None) -> list[set[str]]:
    runs = []
    for f in sorted(task_dir.glob("rev_*/evaluations/*/eval_files/verifier/tg_score.json")):
        ev = f.parts[-4]
        if model_filter and model_filter.lower() not in ev.lower():
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("reward") is None or d.get("integrity") != "ok":
            continue
        runs.append({family(x) for x in d.get("failed_golden_ids") or []})
    return runs


def ceiling(runs: list[set[str]], passes: int) -> tuple[int | None, list[str], list[tuple[str, int]]]:
    """Exact minimum: the smallest union of failing families over any `passes` runs.

    Fixing exactly that union makes those runs pass, and no smaller set can make `passes` runs pass.
    Ties between equally small unions are broken by how common the families are across all runs
    (fixing commoner failures helps more runs), then alphabetically, so results are reproducible.
    """
    counts = collections.Counter(f for s in runs for f in s)
    if len(runs) < passes:
        return None, [], counts.most_common()
    best = None
    for combo in itertools.combinations(range(len(runs)), passes):
        union = set().union(*(runs[i] for i in combo))
        key = (len(union), -sum(counts[f] for f in union), sorted(union))
        if best is None or key < best[0]:
            best = (key, union)
    targets = sorted(best[1], key=lambda f: (-counts[f], f))
    rest = [(f, c) for f, c in sorted(counts.items(), key=lambda x: (-x[1], x[0])) if f not in best[1]]
    return len(targets), targets, rest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delivery-dir", required=True, help="export root: <task>/rev_*/evaluations/...")
    ap.add_argument("--model-filter", default=None, help="substring of the eval folder name, e.g. GLM-5.3")
    ap.add_argument("--passes", type=int, default=2, help="historic runs that must fully pass (default 2)")
    ap.add_argument("--min-runs", type=int, default=8, help="skip tasks with fewer graded runs")
    ap.add_argument("--tasks", nargs="*", help="only these tasks")
    ap.add_argument("--exclude-file", help="JSON list or {task: ...} of tasks to skip (known spec/env defects)")
    ap.add_argument("--next", type=int, default=3, help="also list this many families after the targets (not to hint)")
    ap.add_argument("--out", help="write hint targets JSON here")
    a = ap.parse_args()

    root = Path(a.delivery_dir)
    exclude = set()
    if a.exclude_file:
        data = json.loads(Path(a.exclude_file).read_text())
        exclude = set(data) if isinstance(data, (list, dict)) else set()
    rows, targets = [], {}
    for task_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        t = task_dir.name
        if (a.tasks and t not in a.tasks) or t in exclude:
            continue
        runs = load_runs(task_dir, a.model_filter)
        if len(runs) < a.min_runs:
            continue
        if any(not s for s in runs):
            continue  # already passes: not a zero-pass task
        k, target, rest = ceiling(runs, a.passes)
        best = sorted(len(s) for s in runs)[: a.passes]
        rows.append((k if k is not None else 10**6, t, len(runs), best))
        if k is not None:
            targets[t] = {
                "graded_runs": len(runs), "k": k,
                "target_families": [{"family": f, "failed_in": f"{sum(f in s for s in runs)}/{len(runs)}"} for f in target],
                "next_families_not_to_hint": [{"family": f, "failed_in": f"{c}/{len(runs)}"} for f, c in rest[: a.next]],
            }
    rows.sort()
    print(f"families to fix before >={a.passes} historic runs pass | task | graded runs | failing families in the best runs")
    for k, t, n, best in rows:
        print(f"{('-' if k >= 10**6 else k):>5}  {t:42s} {n:4d}  {best}")
    if a.out:
        Path(a.out).write_text(json.dumps(targets, indent=1))
        print(f"\nwrote hint targets for {len(targets)} tasks -> {a.out}")


if __name__ == "__main__":
    main()
