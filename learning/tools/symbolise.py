#!/usr/bin/env python3

# Licensed under the Apache License, Version 2.0 or the MIT License.
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright Jon Hillesheim 2026.

"""Propose a symbol for every citation that currently names a line number.

    learning/tools/symbolise.py            # write the review report
    learning/tools/symbolise.py --tsv      # the same, machine-readable

The chapters cite the kernel by line number at a commit they name, and that
commit is a merge on one branch of one fork. Sixty of the sixty-one files they
cite are in plain upstream Tock, so a citation naming what it points at rather
than where it sits would resolve for any reader with the kernel checked out --
and would stop moving every time the tree does.

This does not edit anything. It reads each citation, walks up to the item that
contains it, and reports what that item is, so the replacement can be reviewed
as a list rather than as an editing pass over nine chapters of prose.

Three things it flags for a human, because it cannot settle them:

  CHECK     the bullet neither names nor quotes into the item found, which is how
            an off-by-one citation shows itself: `process_console.rs:95`
            derives to `enum WriterState` under a bullet that is about EscKey.
            A wrong line number says nothing; a wrong name is obvious.
  SPANS     the range crosses out of the item it starts in, so one name cannot
            stand for it.
  NONE      nothing above it declares anything -- imports, a file header, or a
            citation into Markdown.
"""

import argparse
import html as html_module
import importlib.util
import pathlib
import re
import subprocess
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
OUT = ROOT / "symbols-review.txt"

DECL = re.compile(
    r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+|const\s+|async\s+|default\s+|extern\s+\"[^\"]*\"\s+)*"
    r"(fn|struct|enum|impl|trait|type|static|const|macro_rules!)\s+([A-Za-z_][A-Za-z0-9_]*)")
STOP = set("the a an of to in and is it that this for with on be are as at by or its".split())


def load_check():
    spec = importlib.util.spec_from_file_location("check", TOOLS / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def words(text):
    return {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
            if w not in STOP}


# A `static`, `const` or `type` is a point declaration: it does not contain the
# lines after it. Walking up to the nearest declaration of any kind put
# `static _eappmem` over citations that are plainly inside `fn main()`, because
# the static happens to sit between them. Only these kinds enclose.
ENCLOSING_KINDS = ("fn", "struct", "enum", "impl", "trait", "macro_rules!")


def enclosing(lines, n):
    """The item that contains line n, walking up past point declarations."""
    for j in range(min(n, len(lines)) - 1, -1, -1):
        found = DECL.match(lines[j])
        if not found:
            continue
        indent, kind, name = found.groups()
        if kind not in ENCLOSING_KINDS and j + 1 != n:
            continue
        return name + ("()" if kind == "fn" else ""), kind, j + 1, len(indent)
    return None, None, None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tsv", action="store_true", help="tab separated")
    args = parser.parse_args()

    check = load_check()
    tock = check.TOCK
    if subprocess.run(["git", "-C", tock, "rev-parse", "--git-dir"],
                      capture_output=True).returncode != 0:
        sys.exit("no kernel tree at %s; set TOCK_TREE" % tock)

    cache = {}

    def source(pin, path):
        key = (pin, path)
        if key not in cache:
            shown = subprocess.run(["git", "-C", tock, "show", "%s:%s" % (pin, path)],
                                   capture_output=True, text=True)
            cache[key] = shown.stdout.split("\n") if shown.returncode == 0 else None
        return cache[key]

    rows = []
    for page in sorted(ROOT.glob("ch*/index.html")):
        html = page.read_text()
        pin, block = check.sources_pin(html)
        if not pin or not block:
            continue
        current = None
        for item in re.findall(r"<li>(.*?)</li>", block, re.S):
            prose = re.sub(r"\s+", " ", html_module.unescape(
                re.sub(r"<[^>]+>", " ", item))).strip()
            said = words(prose)
            for token in check.CITATION_TOKEN.finditer(item):
                if token.group(1):
                    current = token.group(1)
                    continue
                if current is None:
                    continue
                first = int(token.group(2))
                last = int(token.group(3)) if token.group(3) else None
                lines = source(pin, current)
                if not lines or first > len(lines):
                    continue
                name, kind, declared, _ = enclosing(lines, first)
                quoted = [q for q in check.SOURCE_QUOTE.findall(item)]
                inside = ""
                if declared:
                    stop = declared
                    while stop < len(lines) and not (
                            DECL.match(lines[stop]) and
                            len(DECL.match(lines[stop]).group(1)) <=
                            len(DECL.match(lines[declared - 1]).group(1))):
                        stop += 1
                    inside = check._quotable("\n".join(lines[declared - 1:stop]))
                if name is None:
                    verdict = "NONE"
                elif last and enclosing(lines, last)[2] != declared:
                    verdict = "SPANS"
                elif quoted and all(check._quotable(q) in inside for q in quoted):
                    verdict = "ok"          # the bullet's own quote is in this item
                elif name.rstrip("()").lower() in said:
                    verdict = "ok"          # the bullet names it
                else:
                    verdict = "CHECK"
                rows.append({
                    "chapter": page.parent.name, "path": current,
                    "cite": "%d%s" % (first, "-%d" % last if last else ""),
                    "kind": kind or "", "name": name or "",
                    "verdict": verdict, "prose": prose[:110],
                })

    if args.tsv:
        for r in rows:
            print("\t".join([r["chapter"], r["path"], r["cite"], r["verdict"],
                             r["kind"], r["name"], r["prose"]]))
        return 0

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    lines_out = [
        "Proposed symbol for every line-numbered citation in the series.",
        "Nothing is edited. Review the three flagged kinds; 'ok' means the",
        "bullet's own words already name the item the line sits in.",
        "",
        "  ok        %4d   the bullet already names it" % counts.get("ok", 0),
        "  CHECK     %4d   neither named nor quoted by the bullet -- skim" % counts.get("CHECK", 0),
        "  SPANS     %4d   the range leaves the item it starts in" % counts.get("SPANS", 0),
        "  NONE      %4d   nothing declared above it" % counts.get("NONE", 0),
        "",
    ]
    for want in ("CHECK", "SPANS", "NONE", "ok"):
        picked = [r for r in rows if r["verdict"] == want]
        if not picked:
            continue
        lines_out += ["", "=" * 78, "%s — %d" % (want, len(picked)), "=" * 78]
        chapter = None
        for r in picked:
            if r["chapter"] != chapter:
                chapter = r["chapter"]
                lines_out.append("\n-- %s" % chapter)
            lines_out.append("  %s:%s" % (r["path"], r["cite"]))
            lines_out.append("      proposed: %s %s" % (r["kind"], r["name"]) if r["name"]
                             else "      proposed: (nothing found)")
            lines_out.append("      bullet:   %s" % r["prose"])
    OUT.write_text("\n".join(lines_out) + "\n")
    print("\n".join(lines_out[:9]))
    print("full report: %s  (%d citations)" % (OUT.relative_to(ROOT.parent), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
