#!/usr/bin/env python3
"""
build_task_delivery.py — final step: tasks + skills ready to upload/run.

For every task that has a Stage-1 gap analysis (or every task in --delivery-dir with --all-tasks):
  1. copy its task files (rev_*/task_files, no runs) into <out_dir>/<task>/
  2. write <task>/environment/skills.md from the related skill CARD.md files
     (grouped by phase, shared finish checklist)  [uses assemble_task_skills.py]
  3. add `COPY skills.md /opt/skills.md` to environment/Dockerfile (after the spec COPY, or at the end)
  4. append a block to instruction.md telling the agent to read /opt/skills.md
  5. refresh manifest.json sha256/size for touched files (when the task ships one)
  6. write MANIFEST.json, TRACEABILITY.md|json (task -> skills -> evidence) and README.md

  python build_task_delivery.py <work_dir> --delivery-dir <export_root> --out <out_dir> [--all-tasks] [--skills-path /opt/skills.md]
"""
from __future__ import annotations

import argparse, hashlib, json, re, shutil, subprocess, sys
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


HERE = Path(__file__).resolve().parent

INSTRUCTION_BLOCK = """

Working guidance for this kind of task is also provided inside your environment:

    {skills_path}

Read it once before you start. It contains skill cards on reading the specification,
implementing it to the letter, verifying your work the way a maintainer test-suite would,
and the checks to run before you finish. Apply the cards that are relevant to this task.
Where the skills and the specification seem to disagree, the specification is authoritative.
"""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def find_task_files(export_root: Path, task: str) -> Path | None:
    t = export_root / task
    if not t.is_dir():
        return None
    revs = sorted(p for p in t.iterdir() if p.is_dir() and p.name.startswith("rev_"))
    for rev in revs or [t]:
        tf = rev / "task_files"
        if tf.is_dir():
            return tf
    return t if (t / "instruction.md").exists() else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir")
    ap.add_argument("--delivery-dir", required=True, help="export root: <task>/rev_*/task_files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--all-tasks", action="store_true", help="include every task in the export, not only those with a gap analysis")
    ap.add_argument("--skills-path", default="/opt/skills.md", help="where the Dockerfile puts the file inside the image")
    a = ap.parse_args()
    W, EXP, OUT = Path(a.work_dir).resolve(), Path(a.delivery_dir).resolve(), Path(a.out).resolve()
    syn = json.loads((W / "pattern_synthesis.json").read_text())
    analysed = sorted(p.stem for p in (W / "gap_analysis").glob("*.json"))
    tasks = sorted(p.name for p in EXP.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))) if a.all_tasks else analysed
    OUT.mkdir(parents=True, exist_ok=True)
    copied = []
    for task in tasks:
        tf = find_task_files(EXP, task)
        if not tf:
            print(f"  SKIP {task}: no task_files under {EXP}"); continue
        dst = OUT / task
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(tf, dst, ignore=task_ignore(tf))
        copied.append(task)
    print(f"copied task files for {len(copied)} tasks → {OUT}")

    # skills.md per task (assembler writes MANIFEST.json too)
    subprocess.run([sys.executable, str(HERE / "assemble_task_skills.py"), str(W), str(OUT)], check=True)

    # Dockerfile + instruction + manifest
    fname = Path(a.skills_path).name
    for task in copied:
        t = OUT / task
        df = t / "environment" / "Dockerfile"
        if df.exists():
            d = df.read_text()
            if fname not in d:
                line = f"COPY {fname} {a.skills_path}"
                if "COPY spec.md /opt/spec.md" in d:
                    d = d.replace("COPY spec.md /opt/spec.md", f"COPY spec.md /opt/spec.md\n{line}")
                else:
                    d = d.rstrip("\n") + f"\n{line}\n"
                df.write_text(d)
        else:
            print(f"  WARN {task}: no environment/Dockerfile; skills.md written but not copied into the image")
        ins = t / "instruction.md"
        if ins.exists() and a.skills_path not in ins.read_text():
            ins.write_text(ins.read_text().rstrip("\n") + "\n" + INSTRUCTION_BLOCK.format(skills_path=a.skills_path))
        mp = t / "manifest.json"
        if mp.exists():
            m = json.loads(mp.read_text()); mode = m.get("files", {}).get("environment/spec.md", {}).get("mode", "0o664")
            for rel in ("instruction.md", "environment/Dockerfile", f"environment/{fname}"):
                f = t / rel
                if f.exists():
                    m.setdefault("files", {})[rel] = {"mode": m["files"].get(rel, {}).get("mode", mode), "sha256": sha(f), "size": f.stat().st_size}
            m["files"] = dict(sorted(m["files"].items())); mp.write_text(json.dumps(m, indent=1) + "\n")

    # traceability: task -> skills -> evidence
    pats = {p["pattern_name"]: p for p in syn["patterns"]}
    manifest = json.loads((OUT / "MANIFEST.json").read_text())
    trace, md = [], ["# Traceability: task → skills → evidence", "", "Each skill card in a task's environment/skills.md traces to the Stage-1 gap analysis of that task and to the Stage-2 pattern it was clustered into.", ""]
    for row in manifest:
        task = row["task"]
        gpath = W / "gap_analysis" / f"{task}.json"
        g = json.loads(gpath.read_text()) if gpath.exists() else {}
        entry = {"task": task, "gap_analysis": str(gpath) if gpath.exists() else None, "task_summary": str(W / "tasks" / task / "task_summary.md"),
                 "n_runs": g.get("n_runs"), "rewards": g.get("rewards"), "skills": []}
        md += [f"## {task}", f"- runs: {g.get('n_runs')} | rewards: {g.get('rewards')}", f"- gap analysis: `{gpath}`", f"- cross-run summary: `{W / 'tasks' / task / 'task_summary.md'}`", "- skills in environment/skills.md:"]
        for sk in row["skills"]:
            p = pats.get(sk, {})
            ev = [e for e in p.get("representative_evidence", []) if e.lower().startswith(task.lower().split("-")[0])] or []
            cf = [c for c in g.get("consistent_failures", []) if any(k in (c.get("missing_knowledge", "") + c.get("what_agents_did_instead", "")).lower() for k in sk.replace("-", " ").split()[:1])]
            entry["skills"].append({"pattern": sk, "title": p.get("title"), "kind": p.get("kind"), "evidence_from_this_task": ev,
                                    "skill_file": str(W / "skills" / sk / "SKILL.md"), "card_file": str(W / "skills" / sk / "CARD.md")})
            md.append(f"  - **{sk}** ({p.get('kind')}): " + ("; ".join(ev) if ev else "see consistent_failures / process_gaps in the gap analysis"))
        md.append("")
        trace.append(entry)
    (OUT / "TRACEABILITY.json").write_text(json.dumps(trace, indent=1))
    (OUT / "TRACEABILITY.md").write_text("\n".join(md) + "\n")
    (OUT / "README.md").write_text(f"""# Tasks with injected skills

Built by harbor-skill-gen `build_task_delivery.py` from `{W}` and `{EXP}`.

- `<task>/` — the task's files only (no runs), copied from the export.
- `<task>/environment/skills.md` — this task's related skill cards (phase-ordered) + shared finish checklist.
- `<task>/environment/Dockerfile` — `COPY {fname} {a.skills_path}` added next to the spec copy.
- `<task>/instruction.md` — closing block telling the agent to read `{a.skills_path}`; the spec stays authoritative.
- `<task>/manifest.json` — sha256/size refreshed for the touched files (where the task ships a manifest).
- `MANIFEST.json` — task → skills. `TRACEABILITY.md|json` — task → skills → evidence → source files.
""")
    print(f"delivery complete: {len(copied)} tasks, traceability at {OUT / 'TRACEABILITY.md'}")


if __name__ == "__main__":
    main()
