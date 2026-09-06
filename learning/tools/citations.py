#!/usr/bin/env python3

# Licensed under the Apache License, Version 2.0 or the MIT License.
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright Jon Hillesheim 2026.

"""Record what every citation in the series currently points at.

    learning/tools/citations.py            # verify, the way check.py does
    learning/tools/citations.py --write    # rewrite the lockfile

Each chapter cites the kernel tree by line number at a commit it names. The
gate has always checked that the line *exists*, and deliberately not what it
says -- so a citation could point at a closing brace, or at the wrong function
entirely, and pass. That is tolerable while the pin never moves. It is not
tolerable when it does: re-pinning to a newer tree silently re-aims all two
hundred of them, and nothing anywhere would say so.

So this writes down what each one opens and closes on, at the pin, into
`learning/citations.json`. The file is not the point; **the diff is**. Re-pin,
run this with `--write`, and `git diff` is a list of exactly which citations
changed what they aim at, which is the review a re-pin has never had.

It is not a substitute for reading them. A citation that has always been off by
one is recorded as off by one, and stays wrong until somebody looks. What it
guarantees is that a citation cannot *become* wrong without saying so.
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
LOCK = ROOT / "citations.json"
TOCK = os.environ.get("TOCK_TREE") or os.path.expanduser("~/forge/tock")


def load_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check", TOOLS / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blob(pin, path, cache):
    key = (pin, path)
    if key not in cache:
        run = subprocess.run(["git", "-C", TOCK, "show", "%s:%s" % (pin, path)],
                             capture_output=True, text=True)
        cache[key] = run.stdout.split("\n") if run.returncode == 0 else None
    return cache[key]


def survey(check):
    """{chapter: {"pin": sha, "cites": [...]}} for every chapter that cites."""
    cache, out = {}, {}
    for page in sorted(ROOT.glob("ch*/index.html")):
        html = page.read_text()
        pin, _ = check.sources_pin(html)
        cites = list(check.iter_citations(html))
        if not pin or not cites:
            continue
        recorded = []
        for path, start, end in cites:
            lines = blob(pin, path, cache)
            entry = {"path": path, "start": start}
            if end:
                entry["end"] = end
            if lines is None:
                entry["opens"] = None
            else:
                entry["opens"] = (lines[start - 1].strip()[:90]
                                  if start <= len(lines) else None)
                if end and end <= len(lines):
                    entry["closes"] = lines[end - 1].strip()[:90]
            recorded.append(entry)
        out[page.parent.name] = {"pin": pin, "cites": recorded}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="rewrite the lockfile instead of verifying it")
    args = parser.parse_args()

    check = load_check()
    if subprocess.run(["git", "-C", TOCK, "rev-parse", "--git-dir"],
                      capture_output=True).returncode != 0:
        print("no kernel tree at %s; set TOCK_TREE. Nothing checked." % TOCK)
        return 0

    now = survey(check)
    if args.write:
        LOCK.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n")
        total = sum(len(c["cites"]) for c in now.values())
        print("wrote %s — %d citations across %d chapters"
              % (LOCK.relative_to(ROOT.parent), total, len(now)))
        return 0

    if not LOCK.exists():
        print("no citations.json; run with --write")
        return 1
    was = json.loads(LOCK.read_text())
    moved = 0
    for chapter, current in sorted(now.items()):
        before = was.get(chapter)
        if before is None:
            print("%s: not in the lockfile" % chapter)
            moved += 1
            continue
        if before["pin"] != current["pin"]:
            print("%s: pinned at %s, lockfile says %s"
                  % (chapter, current["pin"], before["pin"]))
            moved += 1
        for old, new in zip(before["cites"], current["cites"]):
            if old != new:
                print("%s: %s:%s now opens on %r, was %r"
                      % (chapter, new["path"], new["start"],
                         new.get("opens"), old.get("opens")))
                moved += 1
    print("%d citation(s) changed" % moved if moved else "every citation still aims where it did")
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())
