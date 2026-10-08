#!/usr/bin/env python3
"""
build_skills_dir.py — deliver skills the way Harbor's agents natively consume them.

Instead of one combined environment/skills.md, each task gets a directory of separate
Agent Skills (<name>/SKILL.md with `name` + `description` frontmatter). The task's
task.toml sets [environment] skills_dir, the Dockerfile copies the directory there, and
terminus-2 lists every skill by name and description in its prompt; the agent opens a
SKILL.md only when it judges it relevant (progressive disclosure). No instruction.md edit
is needed.

Which skills a task receives comes from <work_dir>/selection.json:
    {"<task>": ["skill-a", "skill-b"], ...}
written by the Stage-4 selection step (prompts/stage4_skill_selection.md). Keep it to 2-3
skills per task: injecting the whole library dilutes the useful ones.

  python build_skills_dir.py <work_dir> --tasks-src <export_root_or_flat_dir> --out <out_dir>
        [--skills-path /opt/skills] [--selection selection.json] [--all-skills]
"""
from __future__ import annotations

import argparse, hashlib, json, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_skill_format import validate_skill, oracle_target_names, names_in_skill  # noqa: E402

IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "FIX_NOTES*", "NOTES*.md", "TODO*", "CHANGES_*",
                                "*.bak", "*.orig", "*.rej", "*.tmp", "*~", ".pytest_cache", ".idea", ".vscode")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def find_task_files(src: Path, task: str) -> Path | None:
    t = src / task
    if not t.is_dir():
        return None
    for rev in sorted(p for p in t.iterdir() if p.is_dir() and p.name.startswith("rev_")):
        if (rev / "task_files").is_dir():
            return rev / "task_files"
    return t if (t / "task.toml").exists() else None


def set_skills_dir(toml_text: str, skills_path: str) -> str:
    """Add or replace skills_dir inside the [environment] table."""
    m = re.search(r"^\[environment\][^\n]*\n", toml_text, re.M)
    if not m:
        return toml_text.rstrip("\n") + f'\n\n[environment]\nskills_dir = "{skills_path}"\n'
    start = m.end()
    nxt = re.search(r"^\[", toml_text[start:], re.M)
    end = start + nxt.start() if nxt else len(toml_text)
    body = toml_text[start:end]
    if re.search(r"^skills_dir\s*=", body, re.M):
        body = re.sub(r'^skills_dir\s*=.*$', f'skills_dir = "{skills_path}"', body, flags=re.M)
    else:
        body = f'skills_dir = "{skills_path}"\n' + body
    return toml_text[:start] + body + toml_text[end:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir")
    ap.add_argument("--tasks-src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--skills-path", default="/opt/skills")
    ap.add_argument("--selection", default=None, help="default: <work_dir>/selection.json")
    ap.add_argument("--all-skills", action="store_true", help="ignore selection; give every skill to every task (ablation arm)")
    a = ap.parse_args()
    W, SRC, OUT = Path(a.work_dir).resolve(), Path(a.tasks_src).resolve(), Path(a.out).resolve()
    library = {p.parent.name: p.parent for p in sorted((W / "skills").glob("*/SKILL.md"))}
    if not library:
        sys.exit(f"no skills under {W / 'skills'}")
    bad = {n: errs for n, d in library.items() if (errs := validate_skill(d))}
    if bad:
        for n, errs in bad.items():
            print(f"  INVALID {n}: " + "; ".join(errs))
        sys.exit("fix the skill format errors above (check_skill_format.py) before building")
    sel_path = Path(a.selection) if a.selection else W / "selection.json"
    selection = json.loads(sel_path.read_text()) if sel_path.exists() else {}
    if not selection and not a.all_skills:
        sys.exit(f"no selection file at {sel_path}; run the Stage-4 selection step or pass --all-skills")
    tasks = sorted(k for k in selection if not k.startswith("_")) if selection and not a.all_skills else sorted(p.stem for p in (W / "gap_analysis").glob("*.json"))
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for task in tasks:
        chosen = sorted(library) if a.all_skills else selection.get(task, [])
        unknown = [s for s in chosen if s not in library]
        if unknown:
            sys.exit(f"{task}: selection names unknown skills {unknown}")
        tf = find_task_files(SRC, task)
        if not tf:
            print(f"  SKIP {task}: not found under {SRC}"); continue
        own = oracle_target_names(tf / "solution" / "oracle")
        leaking = {n: hits for n in chosen if (hits := names_in_skill(library[n], own))}
        if leaking:
            sys.exit(f"{task}: selected skills name this task's own target package {leaking}; drop or rewrite them")
        dst = OUT / task
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(tf, dst, ignore=IGNORE)
        env = dst / "environment"
        sk = env / "skills"
        if sk.exists():
            shutil.rmtree(sk)
        for name in chosen:
            shutil.copytree(library[name], sk / name, ignore=IGNORE)
        df = env / "Dockerfile"
        d = df.read_text()
        line = f"COPY skills/ {a.skills_path.rstrip('/')}/"
        if line not in d:
            anchor = "COPY spec.md /opt/spec.md"
            d = d.replace(anchor, f"{anchor}\n{line}") if anchor in d else d.rstrip("\n") + f"\n{line}\n"
            df.write_text(d)
        toml = dst / "task.toml"
        toml.write_text(set_skills_dir(toml.read_text(), a.skills_path))
        mp = dst / "manifest.json"
        if mp.exists():
            m = json.loads(mp.read_text()); files = m.setdefault("files", {})
            for p in [df, toml] + sorted(q for q in sk.rglob("*") if q.is_file()):
                rel = str(p.relative_to(dst))
                files[rel] = {"mode": files.get(rel, {}).get("mode", "0o664"), "sha256": sha(p), "size": p.stat().st_size}
            m["files"] = dict(sorted(files.items())); mp.write_text(json.dumps(m, indent=1) + "\n")
        manifest.append({"task": task, "skills": chosen})
        print(f"  {task:40s} {len(chosen)} skills: {', '.join(chosen)}")
    (OUT.parent / f"{OUT.name}.skills_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"built {len(manifest)} tasks -> {OUT}  (record: {OUT.name}.skills_manifest.json, kept outside the delivery)")


if __name__ == "__main__":
    main()
