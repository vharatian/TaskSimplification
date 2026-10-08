#!/usr/bin/env python3
"""
extract_gaps.py — deterministic (no-LLM) extraction for Harbor / terminus-2 runs.

Reads Harbor task dirs + evaluation dirs (the Data-OS "task with runs" export
layout or any task/eval pair) and writes one self-contained *gap bundle* per
run. The bundles are the input that Claude Code reads in Stage 1 of the
harbor-skill-gen skill.

Supported input layouts
-----------------------
A) Data-OS export (default, --delivery-dir):
     <root>/<task>/rev_N__<id>/task_files/...
     <root>/<task>/rev_N__<id>/evaluations/eval_<id>__attempt_<k>__<agent>__<model>/eval_files/...
B) explicit pair(s):  --task-dir <task_files dir> --eval-dir <eval dir or its eval_files dir> [repeatable]

Per eval dir we read:
  result.json                  model, exception, timings, tokens
  verifier/reward.json         reward (fraction of golden tests passed)
  verifier/tg_score.json       failed/passed/skipped golden nodeids, integrity
  verifier/report.xml          per-test failure messages (junit)   [fallback: test-stdout.txt, ctrf.json]
  agent/trajectory.json        terminus-2 steps (bash_command keystrokes + observations)
  artifacts/workspace/ or artifacts/workspace.tar.gz   the agent's final tree

Per task dir we read:
  instruction.md, task.toml, solution/oracle/ (golden tree),
  tests/assets/scaffold/tests/ (verifier test sources), tests/assets/golden_nodeids.json

Output
------
  <out>/index.json, <out>/index.md              every run found + which were selected
  <out>/bundles/<task>__<trial>/
        bundle.md          Stage-1 input (instruction excerpt, failed tests, prioritized diffs, trajectory)
        bundle.json        structured fields
        failed_tests.md    all failed tests: verifier source + failure trace
        trajectory.md      per-step summary
        agent_commands.sh  every keystroke the agent sent, in order
        file_inventory.md  oracle vs agent per-file status
        diffs/*.diff       full unified diffs (oracle -> agent)
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", ".mypy_cache", ".ruff_cache", ".tox", ".eggs", "build", "dist"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dylib", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".whl", ".parquet", ".npy", ".npz", ".pkl", ".bin", ".ico", ".woff", ".woff2", ".ttf"}
NON_SCORED_EXCEPTIONS = {"APIError", "RateLimitError", "ApiUsageLimitError", "DaytonaBadGatewayError", "EnvironmentStartTimeoutError", "MidStreamFallbackError"}


# ─────────────────────────── small helpers ───────────────────────────

def read_text(p: Path, limit: int | None = None) -> str:
    try:
        t = p.read_text(errors="replace")
    except Exception:
        return ""
    return t if limit is None else t[:limit]


def load_json(p: Path):
    try:
        return json.loads(p.read_text(errors="replace"))
    except Exception:
        return None


def is_text_file(p: Path) -> bool:
    if p.suffix.lower() in SKIP_SUFFIXES:
        return False
    try:
        with open(p, "rb") as f:
            chunk = f.read(4096)
        return b"\0" not in chunk
    except Exception:
        return False


def walk_tree(root: Path) -> dict[str, Path]:
    """Relative path -> absolute path for text files, skipping junk dirs."""
    out = {}
    if not root or not root.is_dir():
        return out
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIR_NAMES and not d.endswith(".egg-info") and not d.endswith(".dist-info")]
        for fn in fns:
            p = Path(dp) / fn
            if p.is_symlink():
                continue
            rel = str(p.relative_to(root))
            if is_text_file(p):
                out[rel] = p
    return out


def toml_metadata(text: str) -> dict:
    """Tiny [metadata] / [agent] reader (no tomllib dependency)."""
    out, section = {}, None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^\[+([\w.\-]+)\]+$", s)
        if m:
            section = m.group(1)
            continue
        m = re.match(r"^([\w\-]+)\s*=\s*(.+)$", s)
        if m and section in ("metadata", "agent", "verifier", None):
            k, v = m.group(1), m.group(2).strip()
            try:
                v = json.loads(v.replace("'", '"')) if v.startswith(("[", '"', "'")) or v in ("true", "false") else v
            except Exception:
                pass
            out[f"{section}.{k}" if section else k] = v
    return out


def truncate(s: str, n: int, tail: bool = False) -> str:
    if len(s) <= n:
        return s
    return ("…" + s[-n:]) if tail else (s[:n] + f"\n…[truncated {len(s) - n} chars]")


# ─────────────────────────── discovery ───────────────────────────

def find_eval_files(eval_dir: Path) -> Path:
    return eval_dir / "eval_files" if (eval_dir / "eval_files").is_dir() else eval_dir


def discover_delivery(root: Path) -> list[tuple[str, Path, Path]]:
    """Yield (task_name, task_files_dir, eval_dir) for the Data-OS export layout."""
    pairs = []
    for task_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        revs = sorted(p for p in task_dir.iterdir() if p.is_dir() and p.name.startswith("rev_"))
        if not revs:  # maybe a flat task dir with evaluations/ next to task files
            if (task_dir / "evaluations").is_dir():
                revs = [task_dir]
            else:
                continue
        for rev in revs:
            tf = rev / "task_files" if (rev / "task_files").is_dir() else rev
            ev = rev / "evaluations"
            if not ev.is_dir():
                continue
            for e in sorted(p for p in ev.iterdir() if p.is_dir() and not p.name.startswith(".")):
                pairs.append((task_dir.name, tf, e))
    return pairs


# ─────────────────────────── parsing: task ───────────────────────────

def parse_task(task_dir: Path) -> dict:
    t = {"task_dir": str(task_dir)}
    t["instruction"] = read_text(task_dir / "instruction.md")
    t["task_toml"] = toml_metadata(read_text(task_dir / "task.toml"))
    oracle = task_dir / "solution" / "oracle"
    t["oracle_dir"] = oracle if oracle.is_dir() else None
    t["solve_sh"] = read_text(task_dir / "solution" / "solve.sh")
    # verifier test sources: scaffold/tests first, then tests/
    cands = [task_dir / "tests" / "assets" / "scaffold", task_dir / "tests"]
    t["test_roots"] = [c for c in cands if c.is_dir()]
    gn = load_json(task_dir / "tests" / "assets" / "golden_nodeids.json")
    t["golden_total"] = len(gn) if isinstance(gn, list) else None
    tc = load_json(task_dir / "tests" / "assets" / "test_commands.json")
    t["test_commands"] = tc if isinstance(tc, list) else []
    return t


def nodeid_to_file_and_func(nodeid: str) -> tuple[str, list[str], str]:
    """'tests.rules.test_anchors.AnchorsTestCase::test_disabled[param]' -> ('tests/rules/test_anchors.py', ['AnchorsTestCase'], 'test_disabled')"""
    mod_part, _, rest = nodeid.partition("::")
    func = rest.split("::")[-1]
    classes = rest.split("::")[:-1]
    func = re.sub(r"\[.*\]$", "", func)
    mod_parts = mod_part.split(".")
    # class may be glued to module in junit-style ids: tests.rules.test_anchors.AnchorsTestCase
    file_parts, extra_classes = mod_parts, []
    for i in range(len(mod_parts), 0, -1):
        if mod_parts[i - 1].startswith("test") or mod_parts[i - 1].endswith("_test") or mod_parts[i - 1] == "tests":
            file_parts, extra_classes = mod_parts[:i], mod_parts[i:]
            break
    if "/" in mod_part:  # already a path form tests/test_x.py
        return mod_part, classes, func
    return "/".join(file_parts) + ".py", extra_classes + classes, func


def find_test_source(test_roots: list[Path], nodeid: str) -> tuple[str, str]:
    """Return (relative test file, source of the test function incl. class header) or ('', '')."""
    rel, classes, func = nodeid_to_file_and_func(nodeid)
    for root in test_roots:
        p = root / rel
        if not p.exists():
            # try without leading 'tests/' if root already is tests/
            alt = root / rel.split("/", 1)[-1] if rel.startswith("tests/") else None
            if alt and alt.exists():
                p = alt
            else:
                continue
        src = read_text(p)
        try:
            tree = ast.parse(src)
        except Exception:
            return rel, ""
        lines = src.splitlines()

        def grab(node):
            start = getattr(node, "lineno", 1)
            for d in getattr(node, "decorator_list", []):
                start = min(start, d.lineno)
            end = getattr(node, "end_lineno", start)
            return "\n".join(lines[start - 1:end])

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
                return rel, grab(node)
        return rel, ""
    return rel, ""


def test_file_imports(test_roots: list[Path], rel: str) -> list[str]:
    """Modules imported by a test file (dotted), used to prioritise diffs."""
    for root in test_roots:
        p = root / rel
        if p.exists():
            try:
                tree = ast.parse(read_text(p))
            except Exception:
                return []
            mods = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods += [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.append(node.module)
                    mods += [f"{node.module}.{a.name}" for a in node.names]
            return mods
    return []


# ─────────────────────────── parsing: eval ───────────────────────────

def parse_junit(p: Path) -> dict[str, dict]:
    """nodeid -> {'status': failed|error|skipped|passed, 'message':..., 'text':...}"""
    out = {}
    if not p.exists():
        return out
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return out
    for tc in root.iter("testcase"):
        cls, name = tc.get("classname", ""), tc.get("name", "")
        nodeid = f"{cls}::{name}" if cls else name
        status, msg, text = "passed", "", ""
        for tag in ("failure", "error", "skipped"):
            el = tc.find(tag)
            if el is not None:
                status, msg, text = tag if tag != "failure" else "failed", el.get("message", "") or "", el.text or ""
                break
        out[nodeid] = {"status": status, "message": msg, "text": text}
    return out


def parse_stdout_failures(stdout: str) -> dict[str, str]:
    """Fallback: '____ test_name ____' blocks from pytest FAILURES section -> {func_name: block}."""
    out = {}
    m = re.search(r"={5,}\s*FAILURES\s*={5,}(.*?)(?:\n={5,}\s*(?:warnings summary|short test summary|ERRORS)|\Z)", stdout, re.S)
    if not m:
        return out
    blocks = re.split(r"\n_{5,}\s+(.+?)\s+_{5,}\n", "\n" + m.group(1))
    for j in range(1, len(blocks) - 1, 2):
        out[re.sub(r"\[.*\]$", "", blocks[j].split("::")[-1].strip())] = blocks[j + 1].strip()
    return out


def materialize_workspace(eval_files: Path, tmp_root: Path) -> Path | None:
    ws_dir = eval_files / "artifacts" / "workspace"
    if ws_dir.is_dir():
        return ws_dir
    tgz = eval_files / "artifacts" / "workspace.tar.gz"
    if tgz.exists():
        dest = tmp_root / "ws"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(tgz, "r:gz") as a:
                safe = [m for m in a.getmembers() if not (m.issym() or m.islnk()) and not m.name.startswith("/") and ".." not in Path(m.name).parts]
                a.extractall(dest, members=safe)
            return dest
        except Exception as e:
            print(f"    [warn] could not extract {tgz}: {e}")
    return None


def summarize_trajectory(traj: dict) -> tuple[str, str, dict]:
    """Return (trajectory.md, agent_commands.sh, stats)."""
    steps = traj.get("steps", [])
    md, sh = [], ["#!/bin/bash", "# Every keystroke batch the agent sent, in order (terminus-2 bash_command)."]
    n_cmds = 0
    err_steps = 0
    completed = False
    n_pytest = n_pyrun = n_reads = 0
    digest = []
    for st in steps:
        if st.get("source") != "agent":
            continue
        sid = st.get("step_id")
        msg = str(st.get("message") or "")
        analysis = re.search(r"Analysis:\s*(.+?)(?:\n|Plan:|$)", msg, re.S)
        plan = re.search(r"Plan:\s*(.+?)(?:\n\n|$)", msg, re.S)
        head = (analysis.group(1).strip() if analysis else msg.strip())[:300].replace("\n", " ")
        plan_s = (plan.group(1).strip()[:200].replace("\n", " ") if plan else "")
        cmds = []
        for tc in st.get("tool_calls", []) or []:
            fn = tc.get("function_name", "")
            args = tc.get("arguments", {}) or {}
            if fn == "mark_task_complete":
                completed = True
                cmds.append("[mark_task_complete]")
                continue
            ks = args.get("keystrokes") or args.get("command") or args.get("code") or ""
            if ks:
                n_cmds += 1
                if re.search(r"\bpytest\b|python[^\n]*-m\s+unittest", ks):
                    n_pytest += 1
                if re.search(r"python3?\s+(-c|-I|-\s|<<|[\w./]+\.py)|python3?\s*-\s*<<", ks):
                    n_pyrun += 1
                if re.search(r"\b(cat|sed -n|head|less|rg|grep)\b[^\n]*(spec|instruction|\.md)", ks):
                    n_reads += 1
                sh.append(f"\n# ───── step {sid} ─────")
                sh.append(ks.rstrip("\n"))
                first = ks.strip().splitlines()[0] if ks.strip() else ""
                nlines = ks.count("\n")
                cmds.append(f"`{first[:110]}`" + (f" (+{nlines} lines)" if nlines > 1 else ""))
        obs = st.get("observation")
        obs_text = ""
        if isinstance(obs, dict):
            obs_text = "\n".join(str(r.get("content", "")) for r in obs.get("results", []) if isinstance(r, dict))
        elif obs:
            obs_text = str(obs)
        err = bool(re.search(r"Traceback \(most recent call last\)|\bError\b|FAILED|command not found|No such file|SyntaxError|ModuleNotFoundError", obs_text))
        if err:
            err_steps += 1
        digest.append({"step": sid, "analysis": head[:160], "n_cmds": len(cmds), "error": err})
        md.append(f"### Step {sid}" + (" ⚠ error in output" if err else ""))
        md.append(f"- **Analysis:** {head}")
        if plan_s:
            md.append(f"- **Plan:** {plan_s}")
        if cmds:
            md.append("- **Commands:** " + "; ".join(cmds[:6]) + (f"; …+{len(cmds) - 6}" if len(cmds) > 6 else ""))
        if err:
            md.append("- **Output tail:**\n```\n" + truncate(obs_text.strip(), 600, tail=True) + "\n```")
        md.append("")
    stats = {"n_agent_steps": sum(1 for s in steps if s.get("source") == "agent"), "n_commands": n_cmds, "n_steps_with_errors": err_steps,
             "n_pytest_cmds": n_pytest, "n_python_runs": n_pyrun, "n_spec_reads": n_reads,
             "marked_complete": completed, "final_metrics": traj.get("final_metrics", {}), "digest": digest}
    return "\n".join(md), "\n".join(sh) + "\n", stats


def parse_eval(eval_dir: Path, tmp_root: Path) -> dict:
    ef = find_eval_files(eval_dir)
    e = {"eval_dir": str(eval_dir), "trial": eval_dir.name}
    m = re.match(r"eval_(\d+)__attempt_(\d+)__([^_]+(?:-[^_]+)*)__?(.*)$", eval_dir.name)
    e["agent"], e["model_dir"] = (m.group(3), m.group(4)) if m else ("", "")
    res = load_json(ef / "result.json") or {}
    e["model"] = ((res.get("config") or {}).get("agent") or {}).get("model_name") or (((res.get("agent_info") or {}).get("model_info") or {}).get("name")) or e["model_dir"]
    e["agent_name"] = (res.get("agent_info") or {}).get("name") or e["agent"]
    ex = res.get("exception_info") or {}
    e["exception"] = ex.get("exception_type")
    e["exception_message"] = (ex.get("exception_message") or "")[:300]
    e["agent_timed_out"] = e["exception"] == "AgentTimeoutError"
    ar = res.get("agent_result") or {}
    e["tokens"] = {k: ar.get(k) for k in ("n_input_tokens", "n_output_tokens", "n_cache_tokens", "cost_usd") if k in ar}
    ae = res.get("agent_execution") or {}
    e["agent_started"], e["agent_finished"] = ae.get("started_at"), ae.get("finished_at")
    e["source_trial"], e["source_task"] = res.get("trial_name"), res.get("task_name")
    rj = load_json(ef / "verifier" / "reward.json") or {}
    e["reward"] = rj.get("reward") if isinstance(rj, dict) else None
    if e["reward"] is None:
        e["reward"] = ((res.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    tg = load_json(ef / "verifier" / "tg_score.json") or {}
    e["integrity"] = tg.get("integrity")
    e["golden_total"], e["golden_passed"] = tg.get("golden_total"), tg.get("golden_passed")
    e["failed_ids"] = list(tg.get("failed_golden_ids") or [])
    e["skipped_ids"] = list(tg.get("skipped_golden_ids") or [])
    if not e["failed_ids"]:
        ctrf = load_json(ef / "verifier" / "ctrf.json") or {}
        tests = ((ctrf.get("results") or {}).get("tests")) or []
        e["failed_ids"] = [((t.get("extra") or {}).get("nodeid") if isinstance(t.get("extra"), dict) else None) or t.get("name") for t in tests if t.get("status") not in ("passed", "skipped")]
    e["junit"] = parse_junit(ef / "verifier" / "report.xml")
    e["stdout"] = read_text(ef / "verifier" / "test-stdout.txt")
    e["stdout_failures"] = parse_stdout_failures(e["stdout"])
    traj = load_json(ef / "agent" / "trajectory.json") or {}
    e["trajectory_md"], e["agent_commands_sh"], e["traj_stats"] = summarize_trajectory(traj) if traj else ("(no trajectory.json)", "", {})
    e["workspace_dir"] = materialize_workspace(ef, tmp_root)
    return e


# ─────────────────────────── diffing ───────────────────────────

def module_to_candidates(mod: str) -> list[str]:
    parts = mod.split(".")
    c = []
    for i in range(len(parts), 0, -1):
        base = "/".join(parts[:i])
        c += [base + ".py", base + "/__init__.py"]
    return c


def align_tree(a: dict[str, Path], o: dict[str, Path]) -> dict[str, Path]:
    """Agent tarballs often carry a top-level prefix (e.g. 'workspace/'). Strip the prefix
    (up to 2 levels) that maximises path overlap with the oracle tree."""
    if not a or not o:
        return a
    best, best_n = "", len(set(a) & set(o))
    tops = {r.split("/", 1)[0] for r in a if "/" in r}
    cands = [t + "/" for t in tops]
    cands += [t + "/" + r[len(t) + 1:].split("/", 1)[0] + "/" for t in tops for r in a if r.startswith(t + "/") and r.count("/") >= 2]
    for pre in sorted(set(cands)):
        stripped = {r[len(pre):]: p for r, p in a.items() if r.startswith(pre)}
        n = len(set(stripped) & set(o))
        if n > best_n:
            best, best_n = pre, n
    if best:
        return {r[len(best):]: p for r, p in a.items() if r.startswith(best)}
    # no overlap at all: fall back to descending a single top-level dir
    if best_n == 0 and len(tops) == 1 and not any("/" not in r for r in a):
        t = next(iter(tops)) + "/"
        return {r[len(t):]: p for r, p in a.items()}
    return a


def build_inventory_and_diffs(oracle: Path | None, agent_ws: Path | None, bundle_dir: Path, priority_files: set[str]) -> tuple[list[dict], str]:
    o = walk_tree(oracle) if oracle else {}
    a = walk_tree(agent_ws) if agent_ws else {}
    a = align_tree(a, o)
    # the grader purges agent tests/venvs, and the oracle ships upstream tests — ignore test files on both sides
    def is_test(rel: str) -> bool:
        return rel.startswith(("tests/", "test/")) or re.search(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|conftest\.py)$", rel) is not None
    rels = sorted((set(o) | set(a)) - {r for r in (set(o) | set(a)) if is_test(r)})
    inv, md_rows = [], []
    diffs_dir = bundle_dir / "diffs"
    for rel in rels:
        if rel in o and rel in a:
            ot, at = read_text(o[rel]), read_text(a[rel])
            status = "same" if ot == at else "differs"
        elif rel in o:
            status = "missing_in_agent"
        else:
            status = "agent_only"
        row = {"path": rel, "status": status, "priority": rel in priority_files}
        if status == "differs":
            diff = list(difflib.unified_diff(ot.splitlines(), at.splitlines(), f"oracle/{rel}", f"agent/{rel}", lineterm="", n=3))
            row["diff_lines"] = len(diff)
            diffs_dir.mkdir(exist_ok=True)
            (diffs_dir / (rel.replace("/", "__") + ".diff")).write_text("\n".join(diff) + "\n")
            row["diff_file"] = f"diffs/{rel.replace('/', '__')}.diff"
        elif status == "missing_in_agent":
            row["oracle_lines"] = len(read_text(o[rel]).splitlines())
        elif status == "agent_only":
            row["agent_lines"] = len(read_text(a[rel]).splitlines())
        inv.append(row)
    counts = {}
    for r in inv:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    md = [f"Oracle files: {len([r for r in rels if r in o])} | Agent files: {len([r for r in rels if r in a])} | " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), "", "| status | path | note |", "|---|---|---|"]
    for r in inv:
        if r["status"] == "same":
            continue
        note = r.get("diff_file") or (f"{r.get('oracle_lines')} oracle lines" if "oracle_lines" in r else f"{r.get('agent_lines')} agent lines")
        md.append(f"| {r['status']} | `{r['path']}`{' ★' if r['priority'] else ''} | {note} |")
    md.append(f"\n({counts.get('same', 0)} identical files omitted; ★ = referenced by a failed test)")
    return inv, "\n".join(md)


# ─────────────────────────── bundle assembly ───────────────────────────

def build_bundle(task_name: str, t: dict, e: dict, out_dir: Path, args) -> dict:
    bdir = out_dir / "bundles" / f"{task_name}__{e['trial']}"
    bdir.mkdir(parents=True, exist_ok=True)

    # failed tests: source + trace
    failed_md, failed_struct, priority = [], [], set()
    failed_ids = e["failed_ids"]
    for nid in failed_ids:
        rel, src = find_test_source(t["test_roots"], nid)
        j = e["junit"].get(nid) or {}
        trace = (j.get("text") or j.get("message") or "")
        if not trace:
            trace = e["stdout_failures"].get(nodeid_to_file_and_func(nid)[2], "")
        # files referenced by the traceback (agent workspace paths) → priority diffs
        for fm in re.finditer(r"(?:/tmp/graded-workspace/|/workspace/)?([\w./\-]+\.py):\d+", trace):
            p = fm.group(1)
            if not p.startswith(("/", "usr/", "opt/", "tmp/")) and not re.search(r"(^|/)test", p):
                priority.add(p)
        for mod in test_file_imports(t["test_roots"], rel):
            for cand in module_to_candidates(mod):
                if t["oracle_dir"] and (t["oracle_dir"] / cand).exists():
                    priority.add(cand)
        failed_struct.append({"nodeid": nid, "test_file": rel, "has_source": bool(src), "message": (j.get("message") or "")[:500]})
        failed_md.append(f"## `{nid}`\n**Verifier test** (`{rel}`):\n```python\n{src or '(source not found in scaffold)'}\n```\n**Failure:**\n```\n{truncate(trace.strip(), 3000, tail=True) or '(no failure text captured)'}\n```\n")
    (bdir / "failed_tests.md").write_text("# Failed golden tests\n\n" + ("\n".join(failed_md) if failed_md else "(none failed — run passed or was not scored)\n"))

    inv, inv_md = build_inventory_and_diffs(t["oracle_dir"], e["workspace_dir"], bdir, priority)
    (bdir / "file_inventory.md").write_text("# Oracle vs agent workspace\n\n" + inv_md + "\n")
    (bdir / "trajectory.md").write_text("# Agent trajectory\n\n" + json.dumps({k: v for k, v in e["traj_stats"].items() if k != "digest"}, indent=1) + "\n\n" + e["trajectory_md"])
    (bdir / "agent_commands.sh").write_text(e["agent_commands_sh"])

    # bundle.md — the Stage-1 input (bounded size)
    reward = e["reward"]
    hdr = [f"# Gap bundle: {task_name} / {e['trial']}", "",
           f"- **Agent / model:** {e['agent_name']} / {e['model']}",
           f"- **Reward:** {reward} ({e['golden_passed']}/{e['golden_total']} golden tests) | integrity: {e['integrity']}",
           f"- **Run status:** exception={e['exception'] or 'none'}; agent_timed_out={e['agent_timed_out']}; marked_complete={e['traj_stats'].get('marked_complete')}",
           f"- **Trajectory:** {e['traj_stats'].get('n_agent_steps')} agent steps, {e['traj_stats'].get('n_commands')} command batches, {e['traj_stats'].get('n_steps_with_errors')} steps with error output; tokens={e['tokens']}",
           f"- **Task metadata:** " + ", ".join(f"{k.split('.', 1)[1]}={v}" for k, v in t["task_toml"].items() if k.startswith("metadata.")),
           f"- **Paths:** task_dir=`{t['task_dir']}` eval_dir=`{e['eval_dir']}` bundle=`{bdir}`",
           "", "> Files in this bundle: failed_tests.md (all failures), file_inventory.md, diffs/ (full diffs), trajectory.md, agent_commands.sh.",
           "> The agent wrote the project from scratch; `agent/` in diffs is its final tree, `oracle/` is the golden reference. Oracle/agent tests are excluded (grader uses its own)."]
    if e["agent_timed_out"]:
        hdr.append("> ⚠ The agent hit the time limit; the workspace is whatever existed at timeout. Weigh 'ran out of time' vs 'wrong approach' explicitly.")
    parts = hdr + ["", "## Instruction (excerpt)", truncate(t["instruction"], args.instruction_chars), ""]
    parts += [f"## Failed golden tests ({len(failed_ids)} of {e['golden_total']})", ""]
    if failed_ids:
        groups = {}
        for nid in failed_ids:
            groups.setdefault(nodeid_to_file_and_func(nid)[0], []).append(nid)
        parts.append("Failures by test file: " + "; ".join(f"`{k}` ×{len(v)}" for k, v in sorted(groups.items())))
        parts.append("")
        parts.append(f"Detail for the first {min(len(failed_md), args.max_failed_tests)} (rest in failed_tests.md):\n")
        parts += failed_md[:args.max_failed_tests]
    else:
        parts.append("(no failed golden tests recorded)")
    parts += ["", "## Oracle vs agent workspace", inv_md, ""]
    # prioritized diffs inline
    shown, budget = 0, args.diff_lines_budget
    pri_rows = [r for r in inv if r["status"] != "same" and r["priority"]] + [r for r in inv if r["status"] != "same" and not r["priority"]]
    parts.append(f"## Prioritized diffs (oracle → agent; budget {budget} lines, full files in diffs/)")
    for r in pri_rows:
        if budget <= 0 or shown >= args.max_diff_files:
            break
        if r["status"] == "differs":
            text = (bdir / r["diff_file"]).read_text()
            lines = text.splitlines()
            take = min(len(lines), budget, args.max_lines_per_diff)
            parts.append(f"### `{r['path']}` ({r['diff_lines']} diff lines{', ★ referenced by failed test' if r['priority'] else ''})\n```diff\n" + "\n".join(lines[:take]) + ("\n…" if take < len(lines) else "") + "\n```")
            budget -= take
            shown += 1
        elif r["status"] == "missing_in_agent" and t["oracle_dir"]:
            src = read_text(t["oracle_dir"] / r["path"])
            take_lines = src.splitlines()[:min(args.max_lines_per_diff, budget)]
            parts.append(f"### `{r['path']}` — MISSING in agent tree (oracle has {r.get('oracle_lines')} lines{', ★' if r['priority'] else ''})\n```\n" + "\n".join(take_lines) + ("\n…" if len(take_lines) < r.get("oracle_lines", 0) else "") + "\n```")
            budget -= len(take_lines)
            shown += 1
    parts += ["", "## Trajectory summary (first/last steps; full in trajectory.md)"]
    tm = e["trajectory_md"].split("\n### ")
    if len(tm) > args.max_traj_steps + 1:
        head_n = args.max_traj_steps // 2
        tm = tm[:1 + head_n] + [f"… {len(tm) - 1 - args.max_traj_steps} steps omitted …"] + tm[-(args.max_traj_steps - head_n):]
    parts.append("\n### ".join(tm))
    (bdir / "bundle.md").write_text("\n".join(parts) + "\n")

    struct = {"task": task_name, "trial": e["trial"], "agent": e["agent_name"], "model": e["model"], "reward": reward,
              "golden_total": e["golden_total"], "golden_passed": e["golden_passed"], "integrity": e["integrity"],
              "exception": e["exception"], "agent_timed_out": e["agent_timed_out"], "trajectory_stats": e["traj_stats"],
              "failed_tests": failed_struct, "priority_files": sorted(priority), "inventory": inv,
              "task_metadata": {k.split(".", 1)[1]: v for k, v in t["task_toml"].items() if k.startswith("metadata.")},
              "task_dir": t["task_dir"], "eval_dir": e["eval_dir"], "bundle_dir": str(bdir),
              "has_workspace": e["workspace_dir"] is not None, "has_oracle": t["oracle_dir"] is not None}
    (bdir / "bundle.json").write_text(json.dumps(struct, indent=1, default=str))
    return struct


# ─────────────────────────── per-task cross-run summary ───────────────────────────

def error_signature(trace: str) -> str:
    """Normalise a failure trace to its exception line so repeats across runs cluster."""
    lines = trace.strip().splitlines()
    e_lines = [re.sub(r"^E\s+", "", l).strip() for l in lines if re.match(r"^E\s", l)]
    # the exception type line is the most specific; prefer it, else the first assertion line
    cands = [l for l in e_lines if re.match(r"^[\w.]+(Error|Exception|Failed|Warning)\b", l)] or [l for l in e_lines if l and "Use -v" not in l] \
        or [l.strip() for l in lines if re.match(r"^[\w.]+(Error|Exception)\b", l.strip())]
    if cands:
        sig = re.sub(r"0x[0-9a-f]+", "0x…", cands[-1] if cands[-1].startswith(("AssertionError",)) is False else cands[0])
        sig = re.sub(r"(?<![\w.])\d+(\.\d+)?(?![\w.])", "N", sig)
        return sig[:160]
    first = trace.strip().splitlines()[0] if trace.strip() else ""
    return first[:160]


def write_task_summary(task_name: str, t: dict, runs: list[tuple[dict, dict]], out: Path, args) -> dict:
    """runs = [(parsed_eval, bundle_struct)] for every bundled run of this task."""
    tdir = out / "tasks" / task_name
    tdir.mkdir(parents=True, exist_ok=True)
    N = len(runs)
    # failed-test frequency
    freq: dict[str, int] = {}
    traces: dict[str, list[str]] = {}
    for e, _ in runs:
        for nid in e["failed_ids"]:
            freq[nid] = freq.get(nid, 0) + 1
            j = e["junit"].get(nid) or {}
            tr = j.get("text") or j.get("message") or e["stdout_failures"].get(nodeid_to_file_and_func(nid)[2], "")
            if tr:
                traces.setdefault(nid, []).append(tr)
    always = sorted(n for n, k in freq.items() if k == N)
    often = sorted((n for n, k in freq.items() if N > k >= max(2, (N + 1) // 2)), key=lambda n: -freq[n])
    rare = sorted(n for n, k in freq.items() if k < max(2, (N + 1) // 2))
    # error signatures across runs
    sig_count: dict[str, set] = {}
    for nid, trs in traces.items():
        for tr in trs:
            sig_count.setdefault(error_signature(tr), set()).add(nid)
    sigs = sorted(sig_count.items(), key=lambda kv: -len(kv[1]))
    # file-level commonality
    miss: dict[str, int] = {}
    diff: dict[str, int] = {}
    for _, b in runs:
        for r in b["inventory"]:
            if r["status"] == "missing_in_agent":
                miss[r["path"]] = miss.get(r["path"], 0) + 1
            elif r["status"] == "differs":
                diff[r["path"]] = diff.get(r["path"], 0) + 1
    # ── markdown ──
    md = [f"# Task summary: {task_name}  ({N} runs)", "",
          "- **Task metadata:** " + ", ".join(f"{k}={v}" for k, v in runs[0][1]["task_metadata"].items()),
          f"- **Golden tests:** {runs[0][1]['golden_total']} | task_dir=`{t['task_dir']}`",
          f"- **Run bundles:** " + ", ".join(f"`{b['bundle_dir']}`" for _, b in runs), "",
          "## Runs", "", "| trial | model | reward | passed | exception | timed out | complete | steps | cmds | err steps | pytest cmds | py runs | spec reads | ws |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e, b in runs:
        ts = e["traj_stats"]
        md.append(f"| {e['trial']} | {e['model']} | {e['reward']} | {e['golden_passed']}/{e['golden_total']} | {e['exception'] or ''} | {e['agent_timed_out']} | {ts.get('marked_complete')} | {ts.get('n_agent_steps')} | {ts.get('n_commands')} | {ts.get('n_steps_with_errors')} | {ts.get('n_pytest_cmds')} | {ts.get('n_python_runs')} | {ts.get('n_spec_reads')} | {'yes' if e['workspace_dir'] else 'NO'} |")
    md += ["", f"## Golden tests that failed in EVERY run ({len(always)})", ""]
    if always:
        groups: dict[str, list] = {}
        for nid in always:
            groups.setdefault(nodeid_to_file_and_func(nid)[0], []).append(nid)
        md.append("By test file: " + "; ".join(f"`{k}` ×{len(v)}" for k, v in sorted(groups.items())) + "\n")
        for nid in always[:args.max_always_tests]:
            rel, src = find_test_source(t["test_roots"], nid)
            trs = traces.get(nid, [])
            sigs_here: dict[str, int] = {}
            for tr in trs:
                sg = error_signature(tr)
                sigs_here[sg] = sigs_here.get(sg, 0) + 1
            rep = max(trs, key=lambda x: sigs_here[error_signature(x)]) if trs else ""
            md.append(f"### `{nid}`")
            md.append("Error signatures across runs: " + "; ".join(f"`{k}` ×{v}" for k, v in sorted(sigs_here.items(), key=lambda kv: -kv[1])[:4]))
            md.append(f"**Verifier test** (`{rel}`):\n```python\n{src or '(source not found)'}\n```")
            md.append("**Representative failure:**\n```\n" + truncate(rep.strip(), 1800, tail=True) + "\n```\n")
        if len(always) > args.max_always_tests:
            md.append(f"… {len(always) - args.max_always_tests} more always-failing tests (see each bundle's failed_tests.md)\n")
    else:
        md.append("(none — failures are not consistent across runs; look at the 'often' list)\n")
    md += [f"## Failed in most runs but not all ({len(often)})", ""]
    md += [f"- `{nid}` — {freq[nid]}/{N} runs" for nid in often[:40]] or ["(none)"]
    md += ["", f"## Failed only occasionally ({len(rare)})", "", (", ".join(f"`{n}`({freq[n]})" for n in rare[:40]) or "(none)"), ""]
    md += ["## Error signatures (exception line, normalised) ranked by #distinct tests", ""]
    md += [f"- `{sg}` — {len(ids)} tests" for sg, ids in sigs[:15]] or ["(none)"]
    md += ["", "## Files vs oracle across runs", "",
           "Missing in agent tree (runs missing it / N): " + (", ".join(f"`{p}` {k}/{N}" for p, k in sorted(miss.items(), key=lambda kv: -kv[1])[:25]) or "(none)"),
           "", "Present but different from oracle (runs / N): " + (", ".join(f"`{p}` {k}/{N}" for p, k in sorted(diff.items(), key=lambda kv: -kv[1])[:25]) or "(none)"), ""]
    md += ["## Per-run trajectory digests", ""]
    for e, b in runs:
        ts = e["traj_stats"]
        dg = ts.get("digest", [])
        md.append(f"### {e['trial']} — reward {e['reward']}, {'TIMED OUT' if e['agent_timed_out'] else ('marked complete' if ts.get('marked_complete') else 'ended without completing')}")
        if dg:
            k = args.digest_steps
            show = dg if len(dg) <= 2 * k else dg[:k] + [{"step": "…", "analysis": f"{len(dg) - 2 * k} steps omitted", "n_cmds": "", "error": False}] + dg[-k:]
            md += [f"- step {d['step']}{' ⚠' if d['error'] else ''}: {d['analysis']}" for d in show]
        err_dg = [d for d in dg if d["error"]]
        if err_dg:
            md.append(f"- error steps: {[d['step'] for d in err_dg][:20]}")
        md.append("")
    md += ["## Instruction (excerpt)", "", truncate(t["instruction"], args.summary_instruction_chars), ""]
    (tdir / "task_summary.md").write_text("\n".join(md) + "\n")
    struct = {"task": task_name, "n_runs": N, "runs": [{"trial": e["trial"], "reward": e["reward"], "exception": e["exception"], "timed_out": e["agent_timed_out"],
                                                       "marked_complete": e["traj_stats"].get("marked_complete"), "bundle_dir": b["bundle_dir"]} for e, b in runs],
              "always_failed": always, "often_failed": {n: freq[n] for n in often}, "rare_failed": {n: freq[n] for n in rare},
              "error_signatures": [{"signature": sg, "n_tests": len(ids)} for sg, ids in sigs[:30]],
              "missing_files": miss, "differing_files": diff, "task_metadata": runs[0][1]["task_metadata"], "summary_path": str(tdir / "task_summary.md")}
    (tdir / "task_summary.json").write_text(json.dumps(struct, indent=1, default=str))
    return struct


# ─────────────────────────── main ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("inputs")
    src.add_argument("--delivery-dir", help="Data-OS export root: <task>/rev_*/{task_files,evaluations}")
    src.add_argument("--task-dir", action="append", default=[], help="explicit task_files dir (pair with --eval-dir, repeatable)")
    src.add_argument("--eval-dir", action="append", default=[], help="explicit eval dir (or its eval_files/), same order as --task-dir")
    ap.add_argument("--output-dir", "-o", required=True)
    sel = ap.add_argument_group("run selection")
    sel.add_argument("--tasks", nargs="*", default=None, help="only these task folder names")
    sel.add_argument("--model-filter", default=None, help="substring the model name must contain (e.g. GLM-5.3)")
    sel.add_argument("--include-passed", action="store_true", help="also bundle runs with reward == 1.0")
    sel.add_argument("--exclude-timeouts", action="store_true", help="skip runs that hit AgentTimeoutError")
    sel.add_argument("--expect-runs", type=int, default=8, help="expected scored runs per task (pass@N); tasks with fewer, or with any passing run, are listed under WARNINGS in index.md")
    sel.add_argument("--max-runs-per-task", type=int, default=8, help="cap when --pick is best/worst")
    sel.add_argument("--pick", choices=["best", "worst", "all"], default="all", help="which scored failing runs to bundle per task (default all: the cross-run task summary needs every attempt)")
    siz = ap.add_argument_group("bundle size caps")
    siz.add_argument("--instruction-chars", type=int, default=12000)
    siz.add_argument("--max-failed-tests", type=int, default=8)
    siz.add_argument("--diff-lines-budget", type=int, default=900)
    siz.add_argument("--max-lines-per-diff", type=int, default=300)
    siz.add_argument("--max-diff-files", type=int, default=8)
    siz.add_argument("--max-traj-steps", type=int, default=16)
    siz.add_argument("--max-always-tests", type=int, default=12, help="always-failing tests detailed in task_summary.md")
    siz.add_argument("--digest-steps", type=int, default=6, help="head/tail steps per run in the task summary digests")
    siz.add_argument("--summary-instruction-chars", type=int, default=8000)
    args = ap.parse_args()

    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pairs: list[tuple[str, Path, Path]] = []
    if args.delivery_dir:
        pairs += discover_delivery(Path(args.delivery_dir).resolve())
    if args.task_dir:
        if len(args.task_dir) != len(args.eval_dir):
            sys.exit("--task-dir and --eval-dir must be given the same number of times")
        for td, ed in zip(args.task_dir, args.eval_dir):
            pairs.append((Path(td).resolve().parent.name if Path(td).name == "task_files" else Path(td).name, Path(td).resolve(), Path(ed).resolve()))
    if not pairs:
        sys.exit("no runs found — check --delivery-dir / --task-dir + --eval-dir")
    if args.tasks:
        pairs = [p for p in pairs if p[0] in set(args.tasks)]
    print(f"discovered {len(pairs)} runs across {len({p[0] for p in pairs})} tasks")

    tmp_root = Path(tempfile.mkdtemp(prefix="harbor_gaps_"))
    index, task_cache = [], {}
    by_task: dict[str, list] = {}
    try:
        for task_name, tdir, edir in pairs:
            if str(tdir) not in task_cache:
                task_cache[str(tdir)] = parse_task(tdir)
            e = parse_eval(edir, tmp_root / re.sub(r"\W", "_", edir.name))
            row = {"task": task_name, "trial": edir.name, "model": e["model"], "agent": e["agent_name"], "reward": e["reward"],
                   "exception": e["exception"], "integrity": e["integrity"], "n_failed": len(e["failed_ids"]),
                   "has_workspace": e["workspace_dir"] is not None, "selected": False, "bundle": None}
            scored = e["reward"] is not None and e["exception"] not in NON_SCORED_EXCEPTIONS
            ok = scored and (args.include_passed or (e["reward"] is not None and e["reward"] < 1.0))
            if args.model_filter and args.model_filter.lower() not in str(e["model"]).lower():
                ok = False
            if args.exclude_timeouts and e["agent_timed_out"]:
                ok = False
            if ok:
                by_task.setdefault(task_name, []).append((e, tdir, row))
            index.append(row)
        # choose runs per task and build bundles
        n_b = 0
        task_summaries = []
        for task_name, cands in by_task.items():
            if args.pick != "all":
                cands.sort(key=lambda c: (c[0]["reward"] if c[0]["reward"] is not None else -1), reverse=(args.pick == "best"))
                cands = cands[:args.max_runs_per_task]
            built = []
            for e, tdir, row in cands:
                print(f"  bundling {task_name} / {e['trial']}  reward={e['reward']} failed={len(e['failed_ids'])} ws={'yes' if e['workspace_dir'] else 'NO'}")
                s = build_bundle(task_name, task_cache[str(tdir)], e, out, args)
                row["selected"], row["bundle"] = True, s["bundle_dir"]
                built.append((e, s))
                n_b += 1
            if built:
                ts = write_task_summary(task_name, task_cache[str(cands[0][1])], built, out, args)
                task_summaries.append(ts)
                print(f"  task summary {task_name}: {len(built)} runs, {len(ts['always_failed'])} tests failed in every run → {ts['summary_path']}")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    # pass@N gate: every task should have exactly --expect-runs scored, non-passing runs
    warnings = []
    for task in sorted({r["task"] for r in index}):
        rows = [r for r in index if r["task"] == task]
        if args.model_filter:
            rows = [r for r in rows if args.model_filter.lower() in str(r["model"]).lower()]
        scored = [r for r in rows if r["reward"] is not None and r["exception"] not in NON_SCORED_EXCEPTIONS]
        passing = [r for r in scored if r["reward"] is not None and r["reward"] >= 1.0]
        bundled = [r for r in rows if r["selected"]]
        if len(scored) < args.expect_runs:
            warnings.append(f"{task}: only {len(scored)} scored runs (expected {args.expect_runs}); {len(rows) - len(scored)} unscored (API/rate-limit/no reward)")
        if passing:
            warnings.append(f"{task}: {len(passing)} run(s) PASSED (reward 1.0) -> pass@{len(scored)} is not 0; excluded from bundles unless --include-passed")
        if not bundled:
            warnings.append(f"{task}: no bundles written")
        elif len(bundled) > args.expect_runs:
            warnings.append(f"{task}: {len(bundled)} runs bundled (> {args.expect_runs}); more attempts than expected, check for duplicate batches")
    (out / "index.json").write_text(json.dumps({"runs": index, "tasks": task_summaries, "warnings": warnings, "expect_runs": args.expect_runs}, indent=1, default=str))
    sel_rows = [r for r in index if r["selected"]]
    md = ["# Harbor gap extraction index", "", f"Runs discovered: {len(index)} | tasks: {len({r['task'] for r in index})} | bundles written: {len(sel_rows)} | task summaries: {len(task_summaries)}", ""]
    md += [f"## WARNINGS ({len(warnings)}) — resolve with the user before Stage 1", ""] + ([f"- {w}" for w in warnings] or [f"- none: every task has {args.expect_runs} scored, non-passing runs"]) + [""]
    md += [
          "## Task summaries (Stage-1 inputs)", "", "| task | runs | always-failed tests | top error signature | summary |", "|---|---|---|---|---|"]
    md += [f"| {t['task']} | {t['n_runs']} | {len(t['always_failed'])} | `{(t['error_signatures'][0]['signature'] if t['error_signatures'] else '')[:80]}` | `{t['summary_path']}` |" for t in task_summaries]
    md += ["",
          "## Selected bundles", "", "| task | trial | model | reward | failed | exception | bundle |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['task']} | {r['trial']} | {r['model']} | {r['reward']} | {r['n_failed']} | {r['exception'] or ''} | `{r['bundle']}` |" for r in sel_rows]
    md += ["", "## All runs (per task)", ""]
    for task in sorted({r["task"] for r in index}):
        rows = [r for r in index if r["task"] == task]
        sc = [r for r in rows if r["reward"] is not None]
        md.append(f"- **{task}**: {len(rows)} runs, {len(sc)} scored, rewards={sorted({round(r['reward'], 3) for r in sc}, reverse=True)[:8]}, exceptions={ {r['exception'] for r in rows if r['exception']} or '{}'}")
    (out / "index.md").write_text("\n".join(md) + "\n")
    print(f"\nwrote {len(sel_rows)} bundles → {out}/bundles ; index at {out}/index.md")
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}) — see index.md; confirm with the user before Stage 1:")
        for w in warnings: print("  - " + w)


if __name__ == "__main__":
    main()
