#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0 or the MIT License.
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright Jon Hillesheim 2026.
"""Refuse shell constructs that do something other than what they say.

sweep.py guards a search over a git tree. It cannot guard a shell loop, and
the shell is where this project's confident-wrong results actually come from:
three in one session on 2026-09-12, and the same word-splitting bug on
2026-09-10 before that.

What they share is not "shell is hard". It is that each one **runs, exits 0,
and prints a plausible answer**. A loud failure would have been fixed the
first time.

Only constructs that are silently wrong are refused, and only where they are
silently wrong: `grep -E '\\s'` is fine here because the local grep is a ugrep
shim that accepts it, while `git grep -E '\\s'` is not, because git's ERE reads
the backslash off and matches a literal `s`. A rule that flagged both would be
wrong half the time and would be turned off.

    shell-lint.py 'for b in $BRANCHES; do ...; done'
    echo "$CMD" | shell-lint.py -
    shell-lint.py --hook          # PreToolUse/Bash, reads the hook JSON

Exit 0 clean, 1 a silent trap was found, 2 the linter could not run.

--hook is the form that matters. Invoked by hand this is a tool I have to
remember, and the whole reason these bugs recur is that I did not. As a
PreToolUse hook it is a constraint: the command does not run. It always exits
0 and denies through the hook protocol instead, so a linter that crashes or
goes missing lets the shell through rather than wedging the session.
"""

import json
import re
import sys

# Each rule: (name, compiled pattern, what actually happens, the fix).
# Every one of these has produced a wrong answer in this project.
RULES = [
    (
        "unquoted variable in a `for` list",
        # `for x in $VAR` -- but not $( ), not ${=VAR}, not "$@"
        re.compile(r"\bfor\s+\w+\s+in\s+\$(?!\()(?!\{=)[A-Za-z_][A-Za-z0-9_]*"),
        "zsh does not word-split an unquoted variable, so the loop runs ONCE "
        "with the whole string as a single item, and prints a clean result.",
        'use $(echo $VAR) for portability, or ${=VAR} for zsh, or loop over a '
        "literal list.",
    ),
    (
        "PCRE class in a git grep ERE",
        re.compile(
            r"git\s+grep\b(?![^|;&]*\s-[a-zA-Z]*P\b)[^|;&]*"
            r"\s-[a-zA-Z]*E\b[^|;&]*\\[sdwSDW]"
        ),
        "git grep -E is POSIX ERE: the backslash is dropped and \\s matches a "
        "literal 's'. Measured: ^\\s*/// matched 16 lines where "
        "^[[:space:]]*/// matched 82.",
        "use [[:space:]] / [0-9] / [[:alnum:]_], or pass -P.",
    ),
    (
        "unbraced $VAR followed by a colon",
        # $P:path -- zsh reads :c, :e, :h, :t, :r as history modifiers
        # Measured on zsh 5.9, not taken from the manual: a c e h r s t u A
        # l q Q P mangle; k n x f F w W g G and a leading / do not. So
        # "$HOME:/usr/bin" and "$REV:kernel/..." are left alone, while
        # "$REV:capsules/..." and "$P:examples/..." are caught.
        re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*:[acehrstuAlqQP]"),
        "zsh treats a c e h r s t u A l q Q P after a colon as history modifiers, even inside double quotes, so "
        "the path is silently mangled, the output is empty and the exit status "
        "is 0.",
        'brace it: "${VAR}:path".',
    ),
    (
        "unquoted glob in a long option",
        re.compile(r"--(?:include|exclude)=(?![\"'])[^\s]*\*"),
        "the shell expands the glob before the tool sees it; with no match zsh "
        "aborts the command, and with a match the tool gets the wrong argument.",
        'quote it: --include="*.rs".',
    ),
    (
        "git grep given --include",
        re.compile(r"git\s+grep\b[^|;&]*--include"),
        "git grep takes pathspecs, not --include. It errors out, and a pipe "
        "then hides the status.",
        "use a pathspec after --, e.g. git grep -e PAT -- '*.rs'.",
    ),
]


def lint(cmd):
    """Return a list of (name, what, fix) for every silent trap in `cmd`."""
    out = []
    for name, pat, what, fix in RULES:
        if pat.search(cmd):
            out.append((name, what, fix))
    return out


def report(found):
    """The human-readable body, shared by both modes."""
    out = ["shell-lint: this command does not do what it says.", ""]
    for name, what, fix in found:
        out.append(f"  {name}")
        out.append(f"    {what}")
        out.append(f"    fix: {fix}")
        out.append("")
    out.append("  Each of these runs, exits 0, and prints a plausible answer.")
    return "\n".join(out)


def hook_mode():
    """PreToolUse/Bash. Deny a silently-wrong command before it runs.

    Fails open on every path that is not a confirmed trap: unreadable stdin,
    malformed JSON, a payload with no command. A guard that blocks work it
    cannot parse gets switched off, and then it guards nothing.
    """
    try:
        payload = json.load(sys.stdin)
        cmd = payload.get("tool_input", {}).get("command", "")
    except Exception:
        return 0
    if not isinstance(cmd, str) or not cmd.strip():
        return 0

    found = lint(cmd)
    if not found:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": report(found),
            }
        },
        sys.stdout,
    )
    return 0


def main(argv):
    if len(argv) == 2 and argv[1] == "--hook":
        return hook_mode()
    if len(argv) != 2:
        print("usage: shell-lint.py '<command>' | - | --hook", file=sys.stderr)
        return 2
    cmd = sys.stdin.read() if argv[1] == "-" else argv[1]
    if not cmd.strip():
        return 0

    found = lint(cmd)
    if not found:
        return 0
    print(report(found), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
