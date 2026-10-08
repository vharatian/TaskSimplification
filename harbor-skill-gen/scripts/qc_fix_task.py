#!/usr/bin/env python3
"""
qc_fix_task.py — apply the task-quality fixes that platform rubric reviews flagged, to built task folders.

Per task (in place, under <delivery_dir>/<task>/):
  - task.toml: root `version` -> `schema_version`; [metadata] category, descriptive tags,
    expert/junior time estimates (estimated from spec size; edit if you know better), optional
    difficulty; [verifier] timeout_sec capped (the golden suites run in seconds to minutes)
  - solution/oracle: remove upstream repository files that nothing builds, solves or grades with
    (CI config, editor/lint/release config, docs, compose files, duplicate tests when the scaffold
    ships the graded tests). Each removal is checked: the path must not be importable package code
    and must not be referenced by the scaffold's packaging.
  - manifest.json is NOT touched here; run check_delivery.py --fix afterwards.

  python qc_fix_task.py <delivery_dir> [--tasks t1 t2] [--difficulty hard] [--verifier-timeout 1200]
Always re-run the oracle afterwards; this script only removes files the grader never reads.
"""
from __future__ import annotations

import argparse, re, shutil
from pathlib import Path

ORACLE_CRUFT = [".github", ".gitlab-ci.yml", ".gitignore", ".gitattributes", ".pre-commit-config.yaml",
                ".readthedocs.yml", ".readthedocs.yaml", ".dockerignore", ".editorconfig", "CODE_OF_CONDUCT.md",
                "CONTRIBUTING.md", "codecov.yml", ".codecov.yml", "compose.yml", "docker-compose.yml",
                "docker-compose.yaml", "Dockerfile", "entrypoint.sh", "docs", "examples", "volumes",
                "poetry.lock", "uv.lock", "pdm.lock", "Pipfile.lock", "noxfile.py", "tox.ini", "Makefile",
                ".coveragerc", "mkdocs.yml", ".vscode", ".idea"]
LIB_TAGS = {"django": "django", "fastapi": "fastapi", "psycopg2-binary": "postgresql", "psycopg2": "postgresql",
            "asyncpg": "postgresql", "msgspec": "msgspec", "pydantic": "pydantic", "requests": "http",
            "httpx": "http", "niquests": "http", "aiohttp": "asyncio", "websockets": "websockets",
            "lxml": "xml", "defusedxml": "xml", "pyhocon": "hocon", "bibtexparser": "bibtex",
            "ruamel.yaml": "yaml", "pyyaml": "yaml", "click": "cli", "typer": "cli", "textual": "tui"}


def deps(tf: Path) -> list[str]:
    p = tf / "environment" / "lock.txt"
    if not p.exists():
        return []
    return [m.group(1).lower() for l in p.read_text(errors="replace").splitlines()
            if (m := re.match(r"^([A-Za-z0-9._-]+)==", l.strip()))]


def fix_toml(tf: Path, difficulty: str | None, vt: int):
    p = tf / "task.toml"; s = p.read_text()
    s = re.sub(r'^version = ("[^"]*")', r"schema_version = \1", s, count=1, flags=re.M)
    s = re.sub(r"(\[verifier\][^\[]*?timeout_sec\s*=\s*)(\d+)", lambda m: m.group(1) + str(min(int(m.group(2)), vt)), s, count=1, flags=re.S)
    meta = re.search(r"^\[metadata\][^\n]*\n", s, re.M)
    if not meta:
        p.write_text(s); return
    start = meta.end(); nxt = re.search(r"^\[", s[start:], re.M); end = start + nxt.start() if nxt else len(s)
    body = s[start:end]
    old_tags = re.search(r"^tags\s*=\s*\[([^\]]*)\]", body, re.M)
    keep = [t.strip().strip('"') for t in old_tags.group(1).split(",")] if old_tags else []
    pyver = [t for t in keep if re.fullmatch(r"python3\.\d+", t)]
    lib = sorted({LIB_TAGS[d] for d in deps(tf) if d in LIB_TAGS})
    tags = ["python", "nl2repo", "library-reimplementation"] + lib + pyver
    spec_kb = (tf / "environment" / "spec.md").stat().st_size // 1024 if (tf / "environment" / "spec.md").exists() else 60
    expert = max(180, min(720, round(spec_kb * 2 / 30) * 30))
    lines = {"category": '"software_engineering"', "tags": "[" + ", ".join(f'"{t}"' for t in dict.fromkeys(tags)) + "]",
             "expert_time_estimate_min": f"{float(expert)}", "junior_time_estimate_min": f"{float(expert * 3)}"}
    if difficulty:
        lines["difficulty"] = f'"{difficulty}"'
    for k, v in lines.items():
        if re.search(rf"^{k}\s*=", body, re.M):
            body = re.sub(rf"^{k}\s*=.*$", f"{k} = {v}", body, count=1, flags=re.M)
        else:
            body = re.sub(r"(\n*)$", f"\n{k} = {v}\\1", body, count=1) if body.strip() else f"{k} = {v}\n"
    p.write_text(s[:start] + body + s[end:])


def clean_oracle(tf: Path) -> list[str]:
    oracle = tf / "solution" / "oracle"; scaffold = tf / "tests" / "assets" / "scaffold"
    if not oracle.is_dir():
        return []
    referenced = ""
    for f in ("pyproject.toml", "setup.cfg", "setup.py", "MANIFEST.in"):
        if (scaffold / f).exists():
            referenced += (scaffold / f).read_text(errors="replace")
    removed = []
    names = list(ORACLE_CRUFT) + (["tests"] if (scaffold / "tests").is_dir() else [])
    for n in names:
        p = oracle / n
        if not p.exists():
            continue
        if p.is_dir() and (p / "__init__.py").exists() and n not in ("tests",):
            continue  # importable package code: keep
        # a packaging reference (e.g. a data-file include) keeps it; lint excludes and URLs do not count
        if re.search(rf'(include|data[-_]files|package[-_]data|packages)\s*=?[^\n]*["\']{re.escape(n)}[/"\']', referenced):
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        removed.append(n)
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("delivery_dir"); ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    ap.add_argument("--verifier-timeout", type=int, default=1200)
    a = ap.parse_args()
    D = Path(a.delivery_dir)
    for tf in sorted(p for p in D.iterdir() if (p / "task.toml").exists()):
        if a.tasks and tf.name not in a.tasks:
            continue
        fix_toml(tf, a.difficulty, a.verifier_timeout)
        print(f"{tf.name:40s} oracle removed: {', '.join(clean_oracle(tf)) or '-'}")


if __name__ == "__main__":
    main()
