#!/usr/bin/env python3
"""
check_delivery.py — hygiene + structure check for a flat tasks delivery folder (skills and/or hints).

  python check_delivery.py <delivery_dir> [--expect-skills] [--expect-hints] [--fix]

Checks per task folder:
  - stray author/scratch files at the task top level or under environment/ and tests/ (not inside
    solution/oracle): FIX_NOTES*, NOTES*, TODO*, CHANGES_*, *.bak/.orig/.rej/.tmp, *~, .DS_Store,
    __pycache__, .pytest_cache, .idea, .vscode, empty files
  - required files: instruction.md, task.toml, environment/Dockerfile
  - with --expect-skills: environment/skills.md present; Dockerfile has `COPY skills.md`; instruction.md
    points at /opt/skills.md exactly once
  - with --expect-hints: instruction.md has exactly one `## Supplementary Instruction` section, placed last;
    without it: zero such sections
  - manifest.json (if present): every listed file exists with matching sha256/size; every top-level and
    environment/ file is listed
--fix deletes stray files/dirs, drops them from manifest.json and refreshes sha256/size of listed files.
Exit 1 if any finding remains.
"""
from __future__ import annotations
import argparse, hashlib, json, re, shutil, sys
from pathlib import Path

STRAY_FILE = re.compile(r"^(FIX_NOTES.*|NOTES?(_.*)?\.md|TODO.*|CHANGES_.*|.*\.(bak|orig|rej|tmp|swp)|.*~|\.DS_Store|Thumbs\.db)$", re.I)
STRAY_DIR = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode", ".venv", "venv"}
SCAN_DIRS = ["", "environment", "tests", "solution"]   # not solution/oracle (upstream repo content)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_task(t: Path, expect_skills: bool, expect_hints: bool, fix: bool) -> list[str]:
    f = []
    # stray files / dirs
    for rel in SCAN_DIRS:
        d = t / rel if rel else t
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_dir() and p.name in STRAY_DIR:
                f.append(f"stray dir {p.relative_to(t)}"); fix and shutil.rmtree(p)
            elif p.is_file() and (STRAY_FILE.match(p.name) or p.stat().st_size == 0):
                f.append(f"stray file {p.relative_to(t)}" + (" (empty)" if p.stat().st_size == 0 else "")); fix and p.unlink()
    for p in t.rglob(".DS_Store"):
        f.append(f"stray file {p.relative_to(t)}"); fix and p.unlink()
    # required
    for rel in ("instruction.md", "task.toml", "environment/Dockerfile"):
        if not (t / rel).exists():
            f.append(f"missing {rel}")
    ins = (t / "instruction.md").read_text(errors="replace") if (t / "instruction.md").exists() else ""
    dock = (t / "environment" / "Dockerfile").read_text(errors="replace") if (t / "environment" / "Dockerfile").exists() else ""
    if expect_skills:
        if not (t / "environment" / "skills.md").exists():
            f.append("missing environment/skills.md")
        if "COPY skills.md" not in dock:
            f.append("Dockerfile lacks `COPY skills.md`")
        n = ins.count("/opt/skills.md")
        if n != 1:
            f.append(f"instruction.md mentions /opt/skills.md {n} times (want 1)")
    n_si = len(re.findall(r"^## Supplementary Instruction", ins, re.M))
    if expect_hints:
        if n_si != 1:
            f.append(f"instruction.md has {n_si} Supplementary Instruction sections (want 1)")
        elif not ins.rstrip().split("## Supplementary Instruction")[-1] or re.search(r"\n## (?!Supplementary)", ins.split("## Supplementary Instruction", 1)[1]):
            f.append("Supplementary Instruction is not the last section")
    elif n_si:
        f.append(f"unexpected Supplementary Instruction section ({n_si}) in a skills-only delivery")
    # manifest consistency
    mp = t / "manifest.json"
    if mp.exists():
        m = json.loads(mp.read_text()); files = m.get("files", {})
        changed = False
        for rel in list(files):
            p = t / rel
            if not p.exists():
                f.append(f"manifest lists missing file {rel}")
                if fix: files.pop(rel); changed = True
            elif files[rel].get("sha256") != sha(p) or files[rel].get("size") != p.stat().st_size:
                f.append(f"manifest sha256/size stale for {rel}")
                if fix: files[rel].update(sha256=sha(p), size=p.stat().st_size); changed = True
        for rel_dir in ("", "environment"):
            d = t / rel_dir if rel_dir else t
            for p in d.iterdir():
                if p.is_file() and p.name != "manifest.json":
                    rel = str(p.relative_to(t))
                    if rel not in files:
                        f.append(f"manifest does not list {rel}")
                        if fix:
                            files[rel] = {"mode": "0o664", "sha256": sha(p), "size": p.stat().st_size}; changed = True
        if changed:
            m["files"] = dict(sorted(files.items())); mp.write_text(json.dumps(m, indent=1) + "\n")
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("delivery_dir"); ap.add_argument("--expect-skills", action="store_true"); ap.add_argument("--expect-hints", action="store_true"); ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    D = Path(a.delivery_dir).resolve()
    tasks = sorted(p for p in D.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    total_before = 0
    report = {}
    for t in tasks:
        f = check_task(t, a.expect_skills, a.expect_hints, a.fix)
        total_before += len(f)
        report[t.name] = f
        print(f"{t.name}: {'OK' if not f else str(len(f)) + ' finding(s)' + (' -> fixed where possible' if a.fix else '')}")
        for x in f:
            print(f"    - {x}")
    remaining = 0
    if a.fix:   # re-check after fixing
        for t in tasks:
            remaining += len(check_task(t, a.expect_skills, a.expect_hints, False))
        print(f"\n{len(tasks)} tasks; findings before fix: {total_before}; remaining after fix: {remaining}")
    else:
        remaining = total_before
        print(f"\n{len(tasks)} tasks; findings: {remaining}")
    (D / "DELIVERY_CHECK.json").write_text(json.dumps({"expect_skills": a.expect_skills, "expect_hints": a.expect_hints, "findings_before": report, "remaining": remaining}, indent=1))
    sys.exit(1 if remaining else 0)


if __name__ == "__main__":
    main()
