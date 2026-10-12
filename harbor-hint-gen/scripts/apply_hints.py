#!/usr/bin/env python3
"""
apply_hints.py — put each hint into its task's instruction.md and emit a flat delivery folder.

  python apply_hints.py <work_dir> --tasks-src <dir> --out <out_dir> [--in-place]

<tasks_src> may be an export root (<task>/rev_*/task_files) or a flat folder of task dirs
(e.g. a tasks-with-skills delivery). Only tasks that have hints/<task>/hint.md are copied.
The hint replaces any existing '## Supplementary Instruction' section at the end of
instruction.md, otherwise it is appended. manifest.json sha256/size refreshed when present.
Writes <out_dir>/MANIFEST.json and README.md.
"""
from __future__ import annotations
import argparse, hashlib, json, re, shutil
from pathlib import Path
def task_ignore(root):
    """copytree ignore: drop author notes and editor cruft, but never touch anything the task ships as data.

    Under tests/ and environment/ only caches are skipped: scaffold fixtures can legitimately be named *.tmp, *.bak, *~."""
    root = Path(root).resolve()
    everywhere = shutil.ignore_patterns(".DS_Store", "__pycache__", ".pytest_cache")
    cruft = shutil.ignore_patterns(".DS_Store", "__pycache__", "FIX_NOTES*", "NOTES*.md", "NOTES.md", "TODO*", "CHANGES_*",
                                   "*.bak", "*.orig", "*.rej", "*.tmp", "*~", ".pytest_cache", ".idea", ".vscode")

    def ignore(d, names):
        rel = Path(d).resolve().relative_to(root).parts if Path(d).resolve() != root else ()
        return (everywhere if rel and rel[0] in ("tests", "environment") else cruft)(d, names)
    return ignore


SI_RE = re.compile(r"\n+## Supplementary Instruction\b.*\Z", re.S)


def find_task_files(src: Path, task: str) -> Path | None:
    t = src / task
    if not t.is_dir():
        return None
    revs = sorted(p for p in t.iterdir() if p.is_dir() and p.name.startswith("rev_"))
    for rev in revs:
        if (rev / "task_files").is_dir():
            return rev / "task_files"
    return t if (t / "instruction.md").exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir"); ap.add_argument("--tasks-src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--in-place", action="store_true", help="modify tasks under --tasks-src instead of copying (flat folders only)")
    a = ap.parse_args()
    W, SRC, OUT = Path(a.work_dir).resolve(), Path(a.tasks_src).resolve(), Path(a.out).resolve()
    hints = sorted((W / "hints").glob("*/hint.md"))
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for h in hints:
        task = h.parent.name; tf = find_task_files(SRC, task)
        if not tf:
            print(f"  SKIP {task}: no task files under {SRC}"); continue
        dst = tf if a.in_place else OUT / task
        if not a.in_place:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(tf, dst, ignore=task_ignore(tf))
        ins = dst / "instruction.md"; s = ins.read_text()
        hint = h.read_text().strip()
        replaced = bool(SI_RE.search(s))
        s = SI_RE.sub("", s).rstrip("\n") + "\n\n" + hint + "\n"
        ins.write_text(s)
        mp = dst / "manifest.json"
        if mp.exists():
            m = json.loads(mp.read_text()); f = ins
            m.setdefault("files", {})["instruction.md"] = {"mode": m["files"].get("instruction.md", {}).get("mode", "0o664"), "sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "size": f.stat().st_size}
            mp.write_text(json.dumps(m, indent=1) + "\n")
        review = h.parent / "hint_review.json"; check = h.parent / "hint_check.json"
        manifest.append({"task": task, "hint_lines": len([l for l in hint.splitlines() if l.strip()]), "replaced_existing_si": replaced,
                         "review": json.loads(review.read_text()).get("verdict") if review.exists() else None,
                         "check_findings": len(json.loads(check.read_text()).get("findings", [])) if check.exists() else None,
                         "hint_file": str(h), "instruction": str(ins)})
        print(f"  {task:38s} hint {manifest[-1]['hint_lines']} lines {'(replaced previous SI)' if replaced else '(appended)'} → {ins}")
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    (OUT / "README.md").write_text(f"""# Tasks with hints (Supplementary Instructions)

Built by harbor-hint-gen `apply_hints.py` from `{W}` and `{SRC}`.
Each `<task>/instruction.md` ends with a `## Supplementary Instruction` section (gentle hint: spec pointers,
concepts, what to verify; no code, values or identifiers absent from the spec). Hints, their inputs, review
verdicts and leak-check results are under `{W / 'hints'}`. MANIFEST.json maps task → hint.
""")
    print(f"applied {len(manifest)} hints → {OUT}")


if __name__ == "__main__":
    main()
