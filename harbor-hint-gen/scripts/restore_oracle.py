#!/usr/bin/env python3
"""
restore_oracle.py — put back oracle files that the Data-OS export dropped.

The export omits every path containing a /vendor/ directory from task_files, so some reference solutions arrive
incomplete (vendored schemas, vendored libraries) and the oracle no longer scores 1.0 locally. The platform's own
oracle runs still hold the complete tree in artifacts/(logs/artifacts/)workspace.tar.gz; this copies the missing
/vendor/ files from there into <delivery_dir>/<task>/solution/oracle/.

  python restore_oracle.py --export-zip <export.zip> <delivery_dir> task1 task2 ...

Prints "<task>: restored N oracle files". For tasks with N > 0, pass <task>:solution/oracle/ to final_qc.py as
--allow-change, then run check_delivery.py --fix and re-run the oracle.
"""
import argparse, io, re, tarfile, zipfile
from pathlib import Path

SKIP = re.compile(r"(__pycache__|\.egg-info|\.pyc$|(^|/)build/|\.pytest_cache|(^|/)dist/)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-zip", required=True); ap.add_argument("delivery_dir"); ap.add_argument("tasks", nargs="+")
    a = ap.parse_args()
    z = zipfile.ZipFile(a.export_zip); names = z.namelist(); D = Path(a.delivery_dir)
    for t in a.tasks:
        tar = next((n for n in names if re.match(rf"[^/]+/{re.escape(t)}/.*__oracle/eval_files/artifacts/(logs/artifacts/)?workspace\.tar\.gz$", n)), None)
        if not tar:
            print(f"{t}: no oracle run workspace in export"); continue
        oracle = D / t / "solution" / "oracle"; tf = tarfile.open(fileobj=io.BytesIO(z.read(tar))); n = 0
        for m in tf.getmembers():
            rel = m.name[2:] if m.name.startswith("./") else m.name
            if not m.isfile() or SKIP.search(rel) or "/vendor/" not in "/" + rel:
                continue
            dst = oracle / rel
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True); dst.write_bytes(tf.extractfile(m).read()); n += 1
        print(f"{t}: restored {n} oracle files")


if __name__ == "__main__":
    main()
