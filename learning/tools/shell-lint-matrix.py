#!/usr/bin/env python3
"""The shell-lint matrix, run from a file.

The harness cannot live in a Bash command any more: its test cases ARE the
trap patterns, so the PreToolUse hook blocks the command that would run it.
That is the documented limitation working as intended, not a bug.
"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location(
    "sl", "/Users/jonhillesheim/forge/tock-rp2350/learning/tools/shell-lint.py"
)
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)

CASES = [
    # (expect_catch, label, command)
    (True,  "for over $VAR",        'for b in $BRANCHES; do echo $b; done'),
    (True,  "git grep -E \\s",      "git grep -E '^\\s*///' -- '*.rs'"),
    (True,  "git grep -nE \\s",     "git grep -nE '^\\s*///' -- '*.rs'"),
    (True,  "git grep -lE \\b NEW", "git grep -lE '\\bunsafe\\b' -- '*.rs'"),
    (True,  "git grep -cE \\d",     "git grep -cE '\\d+' -- '*.rs'"),
    (True,  "$REV:capsules",        'git show $REV:capsules/extra/src/crc.rs'),
    (True,  "unquoted --include",   'grep -rn foo --include=*.rs .'),
    (True,  "git grep --include",   'git grep -n foo --include=*.rs'),

    (False, "git grep -lP \\b",     "git grep -lP '\\bunsafe\\b' -- '*.rs'"),
    (False, "git grep -nP \\s",     "git grep -nP '^\\s*///' -- '*.rs'"),
    (False, "$HOME:/usr/bin",       'PATH=$HOME:/usr/bin echo hi'),
    (False, "$REV:kernel",          'git show $REV:kernel/src/lib.rs'),
    (False, "braced ${REV}:",       'git show ${REV}:capsules/extra/src/crc.rs'),
    (False, "POSIX class",          "git grep -nE '^[[:space:]]*///' -- '*.rs'"),
    (False, "plain grep -E \\s",    "grep -rnE '^\\s*///' kernel/"),
    (False, "plain grep -E \\b",    "grep -rnE '\\bunsafe\\b' kernel/"),
    (False, "for over $( )",        'for b in $(git branch --list); do echo $b; done'),
    (False, "for over literal",     'for b in a b c; do echo $b; done'),
    (False, "quoted --include",     'grep -rn foo --include="*.rs" .'),
]

npass = nfail = 0
for expect_catch, label, cmd in CASES:
    hits = sl.lint(cmd)
    caught = bool(hits)
    ok = caught == expect_catch
    npass += ok
    nfail += not ok
    if not ok:
        want = "CATCH" if expect_catch else "PASS"
        print(f"  FAIL  want={want:5} {label}")
    else:
        print(f"  ok    {'CATCH' if expect_catch else 'PASS ':5} {label}")

print(f"\npass={npass} fail={nfail}")
sys.exit(1 if nfail else 0)
