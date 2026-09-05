#!/usr/bin/env python3
"""Check that the published page is still true, still current and still legible.

Seven checks. Each one exists because it has already caught something, or because
it guards a mistake that was actually made here:

  drift       index.html is not what build.py would produce from data.json,
              so either it was hand-edited or somebody forgot to rebuild.
  fresh       the cached data disagrees with GitHub right now. This is the one
              that matters: a merged pull request still shown as open is the
              page lying.
  annotated   a commit is on the page with no label or verification badge.
  intent      a local branch is in the queue with no recorded intent, so a
              reader cannot tell whether it is waiting to be proposed.
  refs        a "#1234" written by hand in the prose names a pull request or
              issue that does not exist. A typo here is invisible on the page.
  private     an address, MAC, serial path or home directory reached the HTML.
  contrast    a text-on-surface pair fell below 4.5:1. Two colours have already
              shipped below it, both found this way and neither by looking.

    ./check.py            # everything, including a live fetch
    ./check.py --offline  # skip the live fetch

Exit 0 clean, 1 problems found, 2 could not run.
"""

import argparse
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent

# Text colour and the surfaces it is drawn on. Semantic pairing cannot be
# inferred from CSS, so it is stated here and checked against the real values.
PAIRS = [
    ("ink", ["bg", "panel"]),
    ("ink-soft", ["bg", "panel"]),
    ("ink-faint", ["bg", "panel"]),
    ("accent", ["bg", "panel"]),
    ("merged-ink", ["merged-bg"]),
    ("review-ink", ["review-bg"]),
    ("approved-ink", ["approved-bg"]),
    ("draft-ink", ["draft-bg"]),
    ("closed-ink", ["closed-bg"]),
    ("unfiled-ink", ["unfiled-bg"]),
    ("ink", ["draft-bg"]),          # the branch chip on defect rows
    # Verification badges sit on whichever node fill the commit's state gives it.
    ("host", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("silicon", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("sections", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("build", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("none", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
]
MIN_RATIO = 4.5

PRIVATE = [
    (r"\b192\.168\.\d+\.\d+\b", "a private IP address"),
    (r"\b10\.\d+\.\d+\.\d+\b", "a private IP address"),
    (r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", "a MAC address"),
    (r"/dev/tty\w+", "a serial device path"),
    (r"/dev/serial\d", "a serial device path"),
    (r"/(?:home|Users)/\w+", "a home directory"),
    (r"\braspberrypi\b", "the bench hostname"),
]


def load_build():
    spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def luminance(hexcolor):
    h = hexcolor.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def palettes(css):
    """Return {theme: {var: hex}} for the light root and the dark override."""
    blocks = re.findall(r":root\{(.*?)\}", css, re.S)
    if len(blocks) < 2:
        return {}
    def parse(block):
        return dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{6})", block))
    light = parse(blocks[0])
    dark = dict(light)
    dark.update(parse(blocks[1]))
    return {"light": light, "dark": dark}


def check_contrast(build, problems):
    css_palettes = palettes(build.CSS)
    if not css_palettes:
        problems.append("contrast: could not parse the palette out of CSS")
        return
    for theme, colors in css_palettes.items():
        for ink, surfaces in PAIRS:
            if ink not in colors:
                problems.append(f"contrast: --{ink} is not defined")
                continue
            for surface in surfaces:
                if surface not in colors:
                    continue
                ratio = contrast(colors[ink], colors[surface])
                if ratio < MIN_RATIO:
                    problems.append(
                        f"contrast: {theme}, --{ink} on --{surface} is "
                        f"{ratio:.2f}:1, below {MIN_RATIO}"
                    )


def check_private(html, problems):
    for pattern, what in PRIVATE:
        for hit in set(re.findall(pattern, html)):
            problems.append(f"private: the page contains {what}: {hit!r}")


def check_refs(build, data, problems):
    known = {p["number"] for p in data["prs"]} | {i["number"] for i in data["issues"]}
    prose = [build.PROVOCATION["answer"], build.PROVOCATION["where"]]
    prose += [v.get("note", "") for v in build.WORK.values()]
    prose += [d[3] for d in build.DEFECTS] + [d[2] for d in build.DOWNSTREAM]
    prose += [n[1] for n in build.NOT_DONE] + [s[1] for s in build.SILICON]
    for text in prose:
        for num in re.findall(r"#(\d{4,5})", str(text)):
            if int(num) not in known:
                problems.append(
                    f"refs: prose mentions #{num}, which is not a pull request "
                    f"or issue in the fetched data"
                )


def check_annotated(build, data, problems):
    _, order, _ = build.build_graph(data)
    for head in order:
        if head not in build.WORK:
            problems.append(f"annotated: no label or badge for {head!r}")


def check_intent(build, data, problems):
    for repo, branches in data.get("local", {}).items():
        for branch, info in branches.items():
            key = f"{repo}:{branch}"
            if key not in build.INTENT:
                problems.append(
                    f"intent: {key} is {info['ahead']} commits ahead and has no "
                    f"entry in INTENT, so the queue cannot say what it is for"
                )


def check_drift(build, data, html, problems):
    if build.render(data) != html:
        problems.append(
            "drift: index.html differs from what build.py produces from "
            "data.json — it was hand-edited, or a rebuild is pending"
        )


def check_fresh(build, data, problems):
    live = build.fetch()
    was = {p["number"]: p for p in data["prs"]}
    now = {p["number"]: p for p in live["prs"]}
    for num in sorted(set(now) - set(was)):
        problems.append(f"fresh: #{num} is new since the page was built — "
                        f"{now[num]['title']!r}")
    for num in sorted(set(was) - set(now)):
        problems.append(f"fresh: #{num} is in the page but not on GitHub")
    for num in sorted(set(was) & set(now)):
        old_state = build.pr_state(was[num])[1]
        new_state = build.pr_state(now[num])[1]
        if old_state != new_state:
            problems.append(f"fresh: #{num} went from {old_state} to {new_state}")
        old_commits = [c["messageHeadline"] for c in was[num]["commits"]]
        new_commits = [c["messageHeadline"] for c in now[num]["commits"]]
        if old_commits != new_commits:
            problems.append(f"fresh: #{num}'s commits changed since the build")
    for num in sorted(set(was) & set(now)):
        if was[num].get("files") != now[num].get("files"):
            problems.append(f"fresh: #{num}'s file list changed, so the "
                            f"branch collisions may be wrong")
    live_issues = {i["number"] for i in live["issues"]}
    for num in sorted(live_issues - {i["number"] for i in data["issues"]}):
        problems.append(f"fresh: issue #{num} is new since the page was built")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="skip the live fetch")
    args = parser.parse_args()

    for name in ("build.py", "data.json", "index.html"):
        if not (ROOT / name).exists():
            sys.exit(f"error: {name} is missing; run ./build.py first")

    build = load_build()
    data = json.loads((ROOT / "data.json").read_text())
    html = (ROOT / "index.html").read_text()

    problems = []
    check_drift(build, data, html, problems)
    check_annotated(build, data, problems)
    check_intent(build, data, problems)
    check_refs(build, data, problems)
    check_private(html, problems)
    check_contrast(build, problems)
    if not args.offline:
        check_fresh(build, data, problems)

    ran = 6 if args.offline else 7
    if problems:
        print(f"{len(problems)} problem(s) across {ran} checks:\n")
        for p in problems:
            print(f"  {p}")
        print("\nMost of these are fixed by running ./build.py.")
        return 1
    clean = ("the page matches its data, every commit and branch is accounted "
             "for, every reference resolves, nothing private is in the HTML and "
             "nothing is unreadable")
    if args.offline:
        print(f"{ran} checks clean — {clean}. GitHub was NOT contacted, so "
              f"whether the data is current is unknown.")
    else:
        print(f"{ran} checks clean — {clean}, and the data still matches GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
