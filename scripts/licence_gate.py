#!/usr/bin/env python3
"""Licence gate. Fails on copyleft, source-available or commercial-only licences.

Usage:
  licence_gate.py python <pip-licenses-json>
  licence_gate.py npm    <license-checker-json>

Policy (CLAUDE.md): permissive only (MIT, Apache-2.0, BSD, ISC, OGL, public domain).
Implemented as a denylist plus a reviewed exceptions file (licences/exceptions.json).
An unknown licence also fails. Every exception names the package, the licence and why.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DENY = re.compile(
    r"(\bA?L?GPL|GNU (Affero |Lesser )?General Public|\bSSPL|Server Side Public|\bBUSL|\bBSL-1|Business Source"
    r"|Commons Clause|\bMPL|Mozilla Public|\bCC-BY-[0-9]|\bOFL|SIL Open Font|\bCC-BY-NC|\bPolyForm|Elastic License|\bproprietary|\bcommercial|\bUNLICENSED\b|\bSEE LICEN[CS]E IN)",
    re.I,
)
UNKNOWN = re.compile(r"^(unknown|none|)$", re.I)


def load_exceptions():
    p = ROOT / "licences" / "exceptions.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return {(e["ecosystem"], e["package"].lower()) for e in data["exceptions"]}


def python_rows(path):
    for r in json.loads(pathlib.Path(path).read_text(encoding="utf-8")):
        yield r["Name"], r["Version"], r["License"]


def npm_rows(path):
    for key, v in json.loads(pathlib.Path(path).read_text(encoding="utf-8")).items():
        name, _, ver = key.rpartition("@")
        lic = v.get("licenses", "UNKNOWN")
        if isinstance(lic, list):
            lic = " OR ".join(lic)
        yield name, ver, lic


def main():
    eco, path = sys.argv[1], sys.argv[2]
    exceptions = load_exceptions()
    rows = python_rows(path) if eco == "python" else npm_rows(path)
    bad, excepted, n = [], [], 0
    for name, ver, lic in rows:
        n += 1
        lic = str(lic)
        if name.startswith("landfall") or name.startswith("@landfall"):
            continue
        # "A OR B" expressions pass if any alternative passes; "A AND B" needs all to pass.
        alts = [a for a in re.split(r"\s+OR\s+|\|", lic.strip("() ")) if a.strip()] or [lic]
        ok = any(not DENY.search(a) and not UNKNOWN.match(a.strip()) for a in alts)
        if ok:
            continue
        if (eco, name.lower()) in exceptions:
            excepted.append((name, ver, lic))
        else:
            bad.append((name, ver, lic))
    for name, ver, lic in excepted:
        print(f"  exception  {name} {ver}  [{lic}]")
    for name, ver, lic in bad:
        print(f"  FAIL       {name} {ver}  [{lic}]")
    print(f"{eco}: {n} packages scanned, {len(excepted)} excepted, {len(bad)} failing")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
