#!/usr/bin/env python3
"""
final_qc.py — prove a finished delivery changed only what it was meant to change.

Compares every task in <delivery_dir> (flat task folders) with the same task in the original
export and fails if anything outside the intended edits differs:

  allowed to change : task.toml, manifest.json, environment/Dockerfile, ATTRIBUTION.md,
                      instruction.md (only by ONE appended "## Supplementary Instruction" section)
  allowed to add    : environment/skills/<name>/...
  allowed to remove : solution/oracle/* (repository cruft), author notes (FIX_NOTES*, NOTES*, TODO*)
  must be identical : environment/spec.md, tests/test.sh, tests/assets/{grade.sh,score.py,
                      golden_nodeids.json,test_commands.json}, the whole test scaffold, solution/solve.sh

Also checks: 1-3 skills that pass the Agent Skills format gate and do not name the task's own
target package; Dockerfile copies the skills; task.toml sets skills_dir; manifest hashes match.
With --harbor-python, also loads each task.toml through Harbor's own TaskConfig model.

  python final_qc.py <delivery_dir> --export <export_root> [--harbor-python <python with harbor>]
Exit 1 if any task has a finding.
"""
from __future__ import annotations

import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "harbor-skill-gen" / "scripts"))
from check_skill_format import validate_skill, oracle_target_names, names_in_skill  # noqa: E402

ALLOWED_CHANGED = {"task.toml", "manifest.json", "environment/Dockerfile", "ATTRIBUTION.md", "instruction.md"}
MUST_MATCH = ("environment/spec.md", "tests/test.sh", "tests/assets/grade.sh", "tests/assets/score.py",
              "tests/assets/golden_nodeids.json", "tests/assets/test_commands.json", "solution/solve.sh")
SI = "## Supplementary Instruction"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree(root: Path) -> dict[str, Path]:
    return {str(p.relative_to(root)): p for p in root.rglob("*") if p.is_file() and p.name != ".DS_Store"}


def original(export: Path, task: str) -> Path | None:
    hits = sorted(export.glob(f"{task}/rev_*/task_files"))
    return hits[0] if hits else None


def check(new: Path, orig: Path, harbor_python: str | None) -> list[str]:
    f = []
    N, O = tree(new), tree(orig)
    changed = sorted(k for k in N if k in O and sha(N[k]) != sha(O[k]))
    added = sorted(k for k in N if k not in O)
    removed = sorted(k for k in O if k not in N)
    if bad := [k for k in changed if k not in ALLOWED_CHANGED]:
        f.append(f"unexpected changes {bad[:4]}")
    if bad := [k for k in added if not k.startswith("environment/skills/")]:
        f.append(f"unexpected new files {bad[:4]}")
    if bad := [k for k in removed if not (k.startswith("solution/oracle/") or re.match(r"(FIX_NOTES|NOTES|TODO)", k))]:
        f.append(f"unexpected removals {bad[:4]}")
    for k in MUST_MATCH:
        if k in O and (k not in N or sha(N[k]) != sha(O[k])):
            f.append(f"{k} differs from the original")
    scaffold = "tests/assets/scaffold/"
    if any(k.startswith(scaffold) and k in N and sha(N[k]) != sha(O[k]) for k in O) or any(k.startswith(scaffold) for k in removed):
        f.append("test scaffold changed")
    oi, ni = (orig / "instruction.md").read_text(), (new / "instruction.md").read_text()
    base = oi.rstrip("\n")
    rest = ni[len(base):] if ni.startswith(base) else None
    if ni != oi and (rest is None or not rest.lstrip("\n").startswith(SI) or rest.count(SI) != 1):
        f.append("instruction.md changed beyond one appended Supplementary Instruction")
    skills = sorted(p.parent for p in (new / "environment" / "skills").glob("*/SKILL.md"))
    if skills:
        if len(skills) > 3:
            f.append(f"{len(skills)} skills (keep 2-3)")
        own = oracle_target_names(orig / "solution" / "oracle")
        for s in skills:
            if errs := validate_skill(s):
                f.append(f"{s.name}: {'; '.join(errs)}")
            if leak := names_in_skill(s, own):
                f.append(f"{s.name} names this task's target package {leak}")
        if "COPY skills/" not in (new / "environment" / "Dockerfile").read_text():
            f.append("Dockerfile does not copy skills/")
        if not re.search(r"^skills_dir\s*=", (new / "task.toml").read_text(), re.M):
            f.append("task.toml has no [environment] skills_dir")
    mp = new / "manifest.json"
    if mp.exists():
        files = json.loads(mp.read_text()).get("files", {})
        if stale := [k for k, v in files.items() if k not in N or v.get("sha256") != sha(N[k])]:
            f.append(f"manifest stale {stale[:3]}")
    if harbor_python:
        code = ("import sys; from harbor.models.task.config import TaskConfig; "
                "TaskConfig.model_validate_toml(open(sys.argv[1]).read())")
        if subprocess.run([harbor_python, "-c", code, str(new / "task.toml")], capture_output=True).returncode:
            f.append("Harbor cannot load task.toml")
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("delivery_dir")
    ap.add_argument("--export", required=True, help="original export root: <task>/rev_*/task_files")
    ap.add_argument("--harbor-python", help="python interpreter that has harbor installed (optional)")
    a = ap.parse_args()
    D, E = Path(a.delivery_dir), Path(a.export)
    total = 0
    for new in sorted(p for p in D.iterdir() if (p / "task.toml").exists()):
        orig = original(E, new.name)
        findings = ["original task not found in export"] if orig is None else check(new, orig, a.harbor_python)
        total += len(findings)
        print(f"{new.name:40s} {'OK' if not findings else '; '.join(findings)}")
    print(f"\nfindings: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
