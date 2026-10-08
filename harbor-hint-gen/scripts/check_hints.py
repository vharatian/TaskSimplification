#!/usr/bin/env python3
"""
check_hints.py — automated solution-leak and form check for hints/<task>/hint.md.

Flags: code fences / assignments / def-import keywords; mention of tests, graders, verifier,
hidden suite, previous runs; backticked tokens, CamelCase/snake_case identifiers and numbers
that do not occur in the task's instruction.md or environment/spec.md; identifiers defined
in the oracle (def/class names, self.attrs) that are absent from the spec; string literals
(>=6 chars) from the verifier tests that are absent from the spec; length and heading.

  python check_hints.py <work_dir> [--tasks ...] [--allow tok1,tok2]
Exit 1 if any hint has findings.
"""
from __future__ import annotations
import argparse, ast, json, re, sys
from pathlib import Path

BANNED = re.compile(r"\b(test|tests|pytest|grader|graded|verifier|hidden suite|assert|previous run|earlier run|your last attempt|expected output)\b", re.I)
PAST = re.compile(r"\b(often|usual(ly)?|typical(ly)?|common(ly)?|tend to|most (runs|attempts|implementations)|again and again|repeatedly)\b", re.I)
GAMING = re.compile(r"named project|the real (package|project)|upstream|would actually (send|write|name)|from memory|maintainers would", re.I)
ASSIGN = re.compile(r"(?<![=!<>`\w])\b[A-Za-z_]\w*\s*=\s*[^=\s]")   # name = value outside backticks


def oracle_identifiers(oracle: Path) -> set:
    ids = set()
    for p in oracle.rglob("*.py"):
        if any(part in {".git", "tests", "test"} for part in p.parts):
            continue
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except Exception:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ids.add(n.name)
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                ids.add(n.attr)
    return {i for i in ids if len(i) >= 4 and not i.startswith("__")}


def test_literals(test_roots: list[Path]) -> set:
    lits = set()
    for root in test_roots:
        for p in root.rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(errors="replace"))
            except Exception:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and 6 <= len(n.value) <= 80 and "\n" not in n.value:
                    lits.add(n.value)
    return lits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir"); ap.add_argument("--tasks", nargs="*"); ap.add_argument("--allow", default="")
    a = ap.parse_args()
    W = Path(a.work_dir).resolve(); allow = {x.strip().lower() for x in a.allow.split(",") if x.strip()}
    hints = sorted((W / "hints").glob("*/hint.md"))
    if a.tasks:
        hints = [h for h in hints if h.parent.name in set(a.tasks)]
    if not hints:
        sys.exit("no hints/*/hint.md found")
    total = 0
    for h in hints:
        task = h.parent.name; text = h.read_text(); lines = text.strip().splitlines()
        findings = []
        # task dir from hint_input
        m = re.search(r"task dir: `([^`]+)`", (h.parent / "hint_input.md").read_text()) if (h.parent / "hint_input.md").exists() else None
        tdir = Path(m.group(1)) if m and m.group(1) != "None" else None
        public = ""
        if tdir:
            for rel in ("instruction.md", "environment/spec.md"):
                if (tdir / rel).exists():
                    public += (tdir / rel).read_text(errors="replace") + "\n"
        public_l = public.lower()
        if not lines or not lines[0].startswith("## Supplementary Instruction"):
            findings.append("does not start with '## Supplementary Instruction'")
        n = len([l for l in lines if l.strip()])
        if n < 8 or n > 30:
            findings.append(f"{n} non-empty lines (want 10-25)")
        if "```" in text:
            findings.append("contains a code fence")
        for i, l in enumerate(lines, 1):
            stripped = re.sub(r"`[^`]*`", "", l)
            if re.search(r"^\s*[-*]?\s*(def|import|from|return|class)\s+\w+\s*[(:=]", stripped) or ASSIGN.search(stripped):
                findings.append(f"L{i}: code-like token or '=' assignment")
            if BANNED.search(l):
                findings.append(f"L{i}: mentions tests/grader/runs: {BANNED.search(l).group(0)!r}")
            if PAST.search(l):
                findings.append(f"L{i}: alludes to past attempts: {PAST.search(l).group(0)!r}")
            if GAMING.search(l):
                findings.append(f"L{i}: memorisation appeal: {GAMING.search(l).group(0)!r}")
            if len(l) > 160:
                findings.append(f"L{i}: {len(l)} chars; wrap at ~120")
        if public:
            for tok in set(re.findall(r"`([^`]+)`", text)):
                if tok.lower() not in public_l and tok.lower() not in allow:
                    findings.append(f"backticked `{tok}` not found in instruction/spec")
            for tok in set(re.findall(r"\b[a-z]+_[a-z_]+\b|\b[A-Z][a-z]+[A-Z]\w+\b", text)):
                if tok.lower() not in public_l and tok.lower() not in allow:
                    findings.append(f"identifier '{tok}' not found in instruction/spec")
            for tok in set(re.findall(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b", text)):
                if tok.lower() not in public_l and tok.lower() not in allow and not re.fullmatch(r"(e\.g|i\.e|etc)", tok.lower()):
                    findings.append(f"dotted name '{tok}' not found in instruction/spec")
            for m in re.finditer(r"\b(equals?|gives?|returns?|yields?|counts?|totals?|is|be|exactly|must be|should be)\s+(\d+)\b", text, re.I):
                findings.append(f"stated value '{m.group(0)}' (possible expected value)")
            for num in set(re.findall(r"(?<![\w.])\d{2,}(?:\.\d+)?(?![\w.])", text)):
                if num not in public:
                    findings.append(f"number {num} not found in instruction/spec (possible expected value)")
            oracle = tdir / "solution" / "oracle"
            if oracle.is_dir():
                leaks = sorted(i for i in oracle_identifiers(oracle) if re.search(rf"\b{re.escape(i)}\b", text) and i.lower() not in public_l and i.lower() not in allow)
                if leaks:
                    findings.append(f"oracle-only identifiers: {leaks[:8]}")
            roots = [tdir / "tests" / "assets" / "scaffold", tdir / "tests"]
            lits = [s for s in test_literals([r for r in roots if r.is_dir()]) if s in text and s.lower() not in public_l and s.lower() not in allow]
            if lits:
                findings.append(f"verifier string literals absent from spec: {lits[:5]}")
        status = "OK" if not findings else f"{len(findings)} finding(s)"
        print(f"{task}: {status}")
        for f_ in findings:
            print(f"    - {f_}")
        total += len(findings)
        (h.parent / "hint_check.json").write_text(json.dumps({"task": task, "findings": findings}, indent=1))
    print(f"\n{len(hints)} hints checked; findings: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
