#!/usr/bin/env python3
"""
assemble_task_skills.py — write one compact environment/skills.md per task.

For each task folder in <tasks_dir>, selects the skills whose pattern lists the task in
`tasks_affected` (from <work_dir>/pattern_synthesis.json), renders their CARD.md (compact
version written in Stage 3) grouped by workflow phase (read -> implement -> verify -> finish),
and appends one shared finish checklist. Output: <tasks_dir>/<task>/environment/skills.md.

  python assemble_task_skills.py <work_dir> <tasks_dir> [--all-skills] [--out-name skills.md]
  --all-skills   ignore the task mapping and include every skill in each task
"""
import argparse, json, re, sys
from pathlib import Path

PHASES = [("read", "Before you start: read the spec"), ("implement", "While implementing"),
          ("verify", "While verifying"), ("finish", "Before you declare completion")]

PREAMBLE = """# Working guidance

Practical rules for building a Python package from a long specification that is graded by
tests you do not see. Read this file once before you start the spec, then come back to the
section for the phase you are in. Each card has a rule, a few do/don't items and "if you see X"
diagnostics. Nothing here replaces the specification; where the two seem to disagree, follow
the specification.
"""

FINISH = """## Shared finish checklist

Run after the LAST edit, in a fresh interpreter, and read the output tail before completing:

- [ ] `pip install -e .`; import every module via `pkgutil.walk_packages` from a neutral directory.
- [ ] `pyflakes` / `ruff --select F` clean; both values of every flag executed once.
- [ ] `python -m pytest -q tests` exits 0; every expected literal in it is traceable to a spec line.
- [ ] Every conditional spec clause has both branches tested, plus the empty / `None` input.
- [ ] Every added `if`, `isinstance`, `return`, `except` and extra kwarg cites a spec sentence, or is gone.
- [ ] Every third-party call matches `inspect.signature` of the installed library.
- [ ] Every user-visible string matches its spec span or noun; compared with `repr()`.
- [ ] Every entry point booted the documented way; no traceback on screen.
"""

def load_card(skills_dir: Path, name: str):
    p = skills_dir / name / "CARD.md"
    if not p.exists():
        return None
    txt = p.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", txt, re.S)
    fm = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M)) if m else {}
    return fm.get("phase", "implement"), fm.get("title", name), (m.group(2) if m else txt).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir"); ap.add_argument("tasks_dir")
    ap.add_argument("--all-skills", action="store_true"); ap.add_argument("--out-name", default="skills.md")
    a = ap.parse_args()
    W, T = Path(a.work_dir), Path(a.tasks_dir)
    syn = json.loads((W / "pattern_synthesis.json").read_text())
    pats = syn["patterns"]
    manifest = []
    for tdir in sorted(p for p in T.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        env = tdir / "environment"
        if not env.is_dir():
            print(f"skip {tdir.name}: no environment/"); continue
        chosen = [p for p in pats if a.all_skills or tdir.name in p["tasks_affected"]]
        cards = [(p["pattern_name"],) + c for p in chosen if (c := load_card(W / "skills", p["pattern_name"]))]
        missing = [p["pattern_name"] for p in chosen if not load_card(W / "skills", p["pattern_name"])]
        out = [PREAMBLE]
        n = 0
        for key, heading in PHASES:
            group = [c for c in cards if c[1] == key]
            if not group:
                continue
            out.append(f"\n# {heading}\n")
            for name, _, title, body in group:
                n += 1
                out.append(f"\n## {n}. {title}\n\n{body}\n")
        out.append("\n" + FINISH)
        text = "\n".join(out)
        (env / a.out_name).write_text(text)
        manifest.append({"task": tdir.name, "skills": [c[0] for c in cards], "missing_cards": missing, "lines": text.count("\n")})
        print(f"{tdir.name:38s} {len(cards)} skills  {text.count(chr(10))} lines" + (f"  MISSING CARD: {missing}" if missing else ""))
    (T / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))

if __name__ == "__main__":
    main()
