#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0 or the MIT License.
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright Jon Hillesheim 2026.
"""Run a search that cannot report a clean zero unless it proved it could see.

Every false conclusion this project has drawn from a search had the same shape:
a sweep returned nothing, and nothing is indistinguishable from success. The
causes vary and none of them announce themselves -- a pattern in the wrong
dialect, a path that does not exist at the revision, a shell that ate part of
the argument, a tool that silently excludes what you were looking for.

So this refuses to say "clean". It says one of three things:

    FOUND    the pattern matched, here is where
    CLEAN    the pattern did not match AND the search was shown to work
    BROKEN   the search could not be shown to work, so it says nothing at all
             about the artifact

BROKEN is the entire point. It is a separate exit status from both of the
others precisely so that a broken run can never be read as a passing one.

    sweep.py --pattern 'Sam4L' --rev upstream/master --path kernel/src/hil/
    sweep.py --pattern 'PA\\[' --path chips/sam4l/ --control 'pub enum Pin'
    sweep.py --pattern 'FIXME' --expect zero --control 'fn '

Exit: 0 FOUND or CLEAN as expected, 1 the expectation was not met, 2 BROKEN.
"""

import argparse
import shutil
import subprocess
import sys

EXIT_OK, EXIT_UNEXPECTED, EXIT_BROKEN = 0, 1, 2

# Measured on git grep 2.54, not assumed. Under -E these are NOT character
# classes: the backslash is dropped and they match the bare letter, so the
# search runs, returns a plausible number, and answers a different question.
#   ^\s*///     matched 16 lines   (zero-or-more literal 's', then ///)
#   ^[[:space:]]*///  matched 82   (what was actually meant)
#   \d          matched 57 lines   (literal 'd')
#   [0-9]       matched 24
# A wrong number is worse than a zero, so these are refused outright.
ERE_TRAPS = {
    r"\s": "[[:space:]]",
    r"\d": "[0-9]",
    r"\w": "[[:alnum:]_]",
    r"\S": "[^[:space:]]",
    r"\D": "[^0-9]",
    r"\W": "[^[:alnum:]_]",
}


def run(argv):
    """Run a command and return (rc, stdout). Never pipes; status stays intact."""
    p = subprocess.run(argv, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def lint_pattern(pattern, dialect):
    """Refuse constructs that silently change meaning in the chosen dialect."""
    if dialect != "ere":
        return []
    found = []
    for trap, fix in ERE_TRAPS.items():
        if trap in pattern:
            found.append(
                f"{trap} is not a character class under -E; it matches the "
                f"bare letter '{trap[1]}'. Use {fix}, or pass --regex perl."
            )
    return found


def corpus_size(rev, paths):
    """How many files the search can actually see.

    This is the automatic control, and it is the one that needs no thought from
    the caller. A path that does not exist at this revision, a mistyped
    directory, a glob the shell expanded before git saw it -- all of them land
    here as a corpus of zero, which is BROKEN rather than clean.
    """
    if rev:
        rc, out, _ = run(["git", "ls-tree", "-r", "--name-only", rev, "--", *paths])
    else:
        rc, out, _ = run(["git", "ls-files", "--", *paths])
    if rc != 0:
        return None
    return len([line for line in out.splitlines() if line.strip()])


def search(pattern, rev, paths, dialect, fixed):
    """git grep, with the status read directly and never through a pipe."""
    flag = {"ere": "-E", "perl": "-P", "basic": "-G"}[dialect]
    argv = ["git", "grep", "-n"]
    argv.append("-F" if fixed else flag)
    argv += ["-e", pattern]
    if rev:
        argv.append(rev)
    argv += ["--", *paths]
    rc, out, err = run(argv)
    # git grep: 0 = matched, 1 = no match, >1 = it failed. Only the third is
    # ambiguous, and it must never be read as "no match".
    if rc > 1:
        return None, err.strip()
    lines = [line for line in out.splitlines() if line.strip()]
    return lines, None


def main():
    ap = argparse.ArgumentParser(
        description="A search that reports BROKEN instead of a clean zero it cannot justify."
    )
    ap.add_argument("--pattern", required=True, help="what to look for")
    ap.add_argument(
        "--control",
        help="a pattern that MUST match in the same corpus, with the same tool "
        "and flags. Proves the search works. Strongly recommended whenever a "
        "zero would be believed.",
    )
    ap.add_argument("--rev", help="search a git revision instead of the working tree")
    ap.add_argument("--path", action="append", default=[], help="repeatable pathspec")
    ap.add_argument(
        "--regex", choices=["ere", "perl", "basic"], default="ere", dest="dialect"
    )
    ap.add_argument("--fixed", action="store_true", help="literal string, no regex")
    ap.add_argument(
        "--expect",
        choices=["zero", "hits", "any"],
        default="any",
        help="'zero' exits 1 if anything matched; 'hits' exits 1 if nothing did",
    )
    ap.add_argument("--show", type=int, default=10, help="matches to print (0 for all)")
    args = ap.parse_args()

    paths = args.path or ["."]

    # --- guard 0: the tool itself -------------------------------------------
    if shutil.which("git") is None:
        print("BROKEN  git is not on PATH", file=sys.stderr)
        return EXIT_BROKEN

    # --- guard 1: the pattern says what you think it says --------------------
    problems = lint_pattern(args.pattern, args.dialect if not args.fixed else "fixed")
    if args.control:
        problems += lint_pattern(
            args.control, args.dialect if not args.fixed else "fixed"
        )
    if problems:
        print("BROKEN  the pattern would answer a different question:", file=sys.stderr)
        for p in problems:
            print(f"        {p}", file=sys.stderr)
        return EXIT_BROKEN

    # --- guard 2: the revision resolves --------------------------------------
    if args.rev:
        rc, _, _ = run(["git", "rev-parse", "--verify", "--quiet", args.rev + "^{tree}"])
        if rc != 0:
            print(f"BROKEN  revision does not resolve: {args.rev}", file=sys.stderr)
            return EXIT_BROKEN

    # --- guard 3: the search can see something -------------------------------
    n_files = corpus_size(args.rev, paths)
    if n_files is None:
        print(f"BROKEN  could not list files under {paths}", file=sys.stderr)
        return EXIT_BROKEN
    if n_files == 0:
        print(
            f"BROKEN  the corpus is empty -- 0 files under {paths}"
            + (f" at {args.rev}" if args.rev else ""),
            file=sys.stderr,
        )
        print(
            "        a zero here would be a fact about the path, not the code.",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    # --- the measurement -----------------------------------------------------
    hits, err = search(args.pattern, args.rev, paths, args.dialect, args.fixed)
    if hits is None:
        print(f"BROKEN  git grep failed: {err}", file=sys.stderr)
        return EXIT_BROKEN

    # --- guard 4: the explicit control ---------------------------------------
    control_n = None
    if args.control:
        ctl, err = search(args.control, args.rev, paths, args.dialect, args.fixed)
        if ctl is None:
            print(f"BROKEN  the control failed to run: {err}", file=sys.stderr)
            return EXIT_BROKEN
        control_n = len(ctl)
        if control_n == 0:
            print(
                "BROKEN  the control matched nothing, so the search was never "
                "shown to work.",
                file=sys.stderr,
            )
            print(f"        control: {args.control!r}", file=sys.stderr)
            print(
                "        Nothing is claimed about the pattern. Fix the control "
                "first.",
                file=sys.stderr,
            )
            return EXIT_BROKEN
    elif not hits:
        # A zero with no explicit control rests on the corpus check alone, which
        # cannot see a pattern that is well-formed and simply wrong. Say so.
        print(
            "note: no --control given, so this zero rests only on the corpus "
            f"being non-empty ({n_files} files). It does not prove the pattern "
            "can match anything.",
            file=sys.stderr,
        )

    scope = f"{n_files} files" + (f" at {args.rev}" if args.rev else "")
    ctl_note = f", control {control_n} hit(s)" if control_n is not None else ""

    if hits:
        print(f"FOUND   {len(hits)} match(es) in {scope}{ctl_note}")
        shown = hits if args.show == 0 else hits[: args.show]
        for line in shown:
            print(f"  {line}")
        if len(hits) > len(shown):
            print(f"  ... and {len(hits) - len(shown)} more")
        return EXIT_UNEXPECTED if args.expect == "zero" else EXIT_OK

    print(f"CLEAN   0 matches in {scope}{ctl_note}")
    return EXIT_UNEXPECTED if args.expect == "hits" else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
