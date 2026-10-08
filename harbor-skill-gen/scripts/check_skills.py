#!/usr/bin/env python3
"""
check_skills.py — anti-hint check for generated skills.

Collects identifiers that belong to the analysed tasks (task names, repo names,
module paths, class/function/test names from failed golden tests, metadata) from
<work_dir>/index.json, tasks/*/task_summary.json and gap_analysis/*.json, then greps
every skills/**/SKILL.md for them. Any hit means the skill leaks task-specific
content and is a hint rather than a general skill.

  python check_skills.py <work_dir> [--min-len 5] [--allow word1,word2]
Exit code 1 when leaks are found.
"""
import argparse, json, re, sys
from pathlib import Path

GENERIC = {"tests", "test", "python", "pytest", "spec", "config", "configuration", "default", "defaults", "error", "errors",
           "exception", "exceptions", "utils", "utility", "database", "client", "session", "response", "request", "options",
           "settings", "setup", "install", "import", "module", "package", "init", "main", "cli", "core", "common", "base",
           "models", "model", "types", "schema", "parser", "parse", "format", "render", "template", "templates", "handler",
           "handlers", "manager", "decorators", "decorator", "logger", "logging", "auth", "api", "http", "json", "yaml",
           "string", "strings", "file", "files", "path", "paths", "list", "dict", "value", "values", "object", "objects",
           "simple", "basic", "nested", "empty", "invalid", "valid", "missing", "multiple", "single", "order", "sort",
           "search", "filter", "remove", "delete", "create", "update", "add", "get", "set", "load", "save", "read", "write",
           "none", "true", "false", "mock", "mocker", "fixture", "assert", "called", "with", "args", "kwargs", "self",
           "integration", "regressions", "contract", "unit", "describe", "example", "examples", "docs", "readme", "license",
           "verify", "verifier", "validate", "validation", "validations", "scaffold", "oracle", "workspace", "textual",
           "requests", "pydantic", "pandas", "jinja2", "rich", "boto3", "typing", "extensions", "tokenize", "yaml"}


def collect_identifiers(wd: Path) -> set:
    ids = set()
    def add(s):
        if not s or not isinstance(s, str):
            return
        for tok in re.split(r"[^A-Za-z0-9_]+", s):
            if len(tok) >= 4 and not tok.isdigit():
                ids.add(tok)
    idx = json.loads((wd / "index.json").read_text()) if (wd / "index.json").exists() else {}
    for r in idx.get("runs", []):
        add(r.get("task"))
    for t in idx.get("tasks", []):
        add(t.get("task"))
        for k in ("always_failed", "often_failed", "rare_failed"):
            v = t.get(k) or []
            for nid in (v if isinstance(v, list) else v.keys()):
                add(nid)
        for p in list((t.get("missing_files") or {}).keys()) + list((t.get("differing_files") or {}).keys()):
            add(p)
        for k, v in (t.get("task_metadata") or {}).items():
            if k in ("name", "source_repo"):
                add(str(v).replace("https://github.com/", ""))
    for f in (wd / "gap_analysis").glob("*.json"):
        g = json.loads(f.read_text())
        add(g.get("task"))
        for cf in g.get("consistent_failures", []):
            for nid in cf.get("tests", []):
                add(nid)
    # keep only identifier-shaped tokens: snake_case, CamelCase, dotted, or task-slug parts.
    # Plain English fragments (e.g. 'existing' from test_deletes_existing_key) are dropped.
    def looks_like_identifier(tok: str) -> bool:
        return ("_" in tok.strip("_") or re.search(r"[a-z][A-Z]", tok) is not None or re.search(r"\d", tok) is not None)
    slug_parts = set()
    for r in idx.get("runs", []):
        for part in re.split(r"[-_]", r.get("task", "")):
            if len(part) >= 5 and part.lower() not in GENERIC and not part.startswith("v"):
                slug_parts.add(part)
    ids = {i for i in ids if looks_like_identifier(i)} | slug_parts
    return {i for i in ids if i.lower() not in GENERIC and not re.fullmatch(r"(test_?\w{0,3}|\w{0,3}_test|test_\w+)", i.lower())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--min-len", type=int, default=5)
    ap.add_argument("--allow", default="", help="comma-separated identifiers to ignore")
    a = ap.parse_args()
    wd = Path(a.work_dir)
    allow = {x.strip().lower() for x in a.allow.split(",") if x.strip()}
    ids = {i for i in collect_identifiers(wd) if len(i) >= a.min_len and i.lower() not in allow}
    skills = sorted((wd / "skills").glob("*/SKILL.md")) + sorted((wd / "skills").glob("*/CARD.md"))
    if not skills:
        sys.exit("no skills/*/SKILL.md found")
    pat = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(sorted(map(re.escape, ids), key=len, reverse=True)) + r")(?![A-Za-z0-9_])", re.I)
    leaks = 0
    exploit = re.compile(r"upstream project|named open-source|re-?implements? a named|you remember|canonical (upstream )?wording|project's own (test|pytest)", re.I)
    for s in skills:
        hits = {}
        for n, line in enumerate(s.read_text().splitlines(), 1):
            if exploit.search(line):
                hits.setdefault("[benchmark-gaming phrasing]", []).append(n)
        for n, line in enumerate(s.read_text().splitlines(), 1):
            for m in pat.finditer(line):
                hits.setdefault(m.group(1), []).append(n)
        print(f"{s.parent.name}/{s.name}: {'OK' if not hits else str(len(hits)) + ' leaked identifier(s)'}")
        for k, lines in sorted(hits.items()):
            print(f"    {k}  lines {lines[:6]}")
            leaks += 1
    print(f"\n{len(ids)} task identifiers checked against {len(skills)} skills; leaks: {leaks}")
    sys.exit(1 if leaks else 0)


if __name__ == "__main__":
    main()
