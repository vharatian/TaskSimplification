#!/usr/bin/env python3
"""
apply_fixes.py — apply reviewed task-side fixes to built task folders.

Some tasks cannot be saved by a hint because the task itself is wrong: a golden test pins behaviour the spec
never states or contradicts (a spec defect), or golden ids fail for platform reasons on correct code. Those are
fixed in the task, not hinted. Each fix is a reviewed JSON file in the work dir:

  <work_dir>/specfix/<task>.json   {"edits": [{"file": "environment/spec.md", "old": "<unique text>", "new": "...",
                                               "defect": "...", "evidence": "test id + oracle line"}]}
  <work_dir>/gradefix/<task>.json  {"remove_golden_ids": [...], "reason": "...", "evidence": "..."}

  python apply_fixes.py <work_dir> <delivery_dir> task1 task2 ...

Prints one TASK:PATH per edited file; pass each to final_qc.py as --allow-change so the edit is reported.
Every "old" anchor must occur exactly once. Run check_delivery.py --fix afterwards to refresh manifest hashes.
"""
import json, sys
from pathlib import Path


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    W, B = Path(sys.argv[1]), Path(sys.argv[2])
    for t in sys.argv[3:]:
        sf = W / "specfix" / f"{t}.json"
        if sf.exists():
            for e in json.loads(sf.read_text())["edits"]:
                p = B / t / e["file"]; s = p.read_text()
                n = s.count(e["old"])
                if n != 1:
                    sys.exit(f"{t}: edit anchor occurs {n} times in {e['file']}: {e['old'][:60]!r}")
                p.write_text(s.replace(e["old"], e["new"]))
                print(f"{t}:{e['file']}")
        gf = W / "gradefix" / f"{t}.json"
        if gf.exists():
            g = json.loads(gf.read_text()); p = B / t / "tests/assets/golden_nodeids.json"
            ids = json.loads(p.read_text()); drop = set(g["remove_golden_ids"])
            if missing := drop - set(ids):
                sys.exit(f"{t}: {len(missing)} ids to remove are not golden, e.g. {sorted(missing)[:2]}")
            p.write_text(json.dumps([i for i in ids if i not in drop], indent=1) + "\n")
            print(f"{t}:tests/assets/golden_nodeids.json")


if __name__ == "__main__":
    main()
