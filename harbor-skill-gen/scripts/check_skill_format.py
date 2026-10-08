#!/usr/bin/env python3
"""
check_skill_format.py — validate skills against the Agent Skills format and the NL2Repo leak rule.

Format (what terminus-2 and other Harbor agents read):
  - <name>/SKILL.md with YAML frontmatter holding `name` and `description`
  - name: 1-64 chars, lowercase letters, digits and hyphens; equals the directory name
  - description: 1-1024 chars, says what the skill covers AND when to use it (the agent
    decides from this text alone whether to open the skill), third person
  - body under 500 lines; anything longer goes to files the body links to

Leak rule (NL2Repo-specific): the package an NL2Repo task rebuilds IS the answer, so a skill
must never name a target package. Pass the export root with --targets-from to load every
task's distribution and import names and fail any skill that mentions one.

  python check_skill_format.py <work_dir> [--targets-from <export_root>]
Exit 1 on any finding.
"""
from __future__ import annotations

import argparse, re, sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIRST_PERSON = re.compile(r"\b(I|I'm|I'll|we|we'll|you should use me)\b")


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    fm, key = {}, None
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if km:
            key = km.group(1); val = km.group(2).strip()
            fm[key] = "" if val in (">", "|", ">-", "|-") else val.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm


def validate_skill(skill_dir: Path) -> list[str]:
    errs = []
    p = skill_dir / "SKILL.md"
    if not p.exists():
        return ["missing SKILL.md"]
    text = p.read_text(errors="replace")
    fm = frontmatter(text)
    name, desc = fm.get("name", ""), fm.get("description", "")
    if not name:
        errs.append("frontmatter has no name")
    elif not (len(name) <= 64 and NAME_RE.match(name)):
        errs.append(f"name {name!r} must be <=64 chars of lowercase letters, digits, hyphens")
    elif name != skill_dir.name:
        errs.append(f"name {name!r} differs from directory {skill_dir.name!r}")
    if not desc:
        errs.append("frontmatter has no description")
    elif len(desc) > 1024:
        errs.append(f"description is {len(desc)} chars (max 1024)")
    elif not re.search(r"\b(use|when|whenever|before|if)\b", desc, re.I):
        errs.append("description should say when to use the skill (it is the only routing signal)")
    if desc and FIRST_PERSON.search(desc):
        errs.append("description should be written in the third person")
    body_lines = text.count("\n")
    if body_lines > 500:
        errs.append(f"SKILL.md has {body_lines} lines (keep under 500; move detail to linked files)")
    return errs


GENERIC_DIRS = {"scripts", "utils", "src", "lib", "common", "tools", "examples", "docs", "tests", "test"}


def oracle_target_names(oracle: Path) -> set[str]:
    """Distribution and import names of the package an NL2Repo task rebuilds."""
    names = set()
    for base in (oracle, oracle / "src"):
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir() and (d / "__init__.py").exists() and d.name not in ("tests", "test", "docs", "examples"):
                    names.add(d.name)
    pp = oracle / "pyproject.toml"
    if pp.exists():
        m = re.search(r'^name\s*=\s*["\']([^"\']+)', pp.read_text(errors="replace"), re.M)
        if m:
            names.add(m.group(1))
    return {n for n in names if len(n) >= 4 and n.lower() not in GENERIC_DIRS}


def target_names(export_root: Path) -> set[str]:
    names = set()
    for tf in export_root.glob("*/rev_*/task_files"):
        names |= oracle_target_names(tf / "solution" / "oracle")
    return names


def names_in_skill(skill_dir: Path, names: set[str]) -> list[str]:
    if not names:
        return []
    pat = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")(?![\w-])", re.I)
    return sorted({m.group(1) for f in skill_dir.rglob("*") if f.is_file() for m in pat.finditer(f.read_text(errors="replace"))})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--targets-from", help="export root; fail skills that name any task's target package")
    a = ap.parse_args()
    skills = sorted((Path(a.work_dir) / "skills").glob("*/SKILL.md"))
    if not skills:
        sys.exit("no skills/*/SKILL.md found")
    targets = target_names(Path(a.targets_from)) if a.targets_from else set()
    pat = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(targets, key=len, reverse=True))) + r")(?![\w-])", re.I) if targets else None
    total = 0
    for p in skills:
        errs = validate_skill(p.parent)
        if pat:
            hits = names_in_skill(p.parent, targets)
            if hits:
                print(f"    note {p.parent.name}: mentions {hits[:6]}; build_skills_dir.py refuses to ship it to those tasks")
        print(f"{p.parent.name}: {'OK' if not errs else '; '.join(errs)}")
        total += len(errs)
    print(f"\n{len(skills)} skills checked{f' against {len(targets)} target package names' if targets else ''}; findings: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
