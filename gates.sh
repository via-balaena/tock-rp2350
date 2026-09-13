#!/bin/bash
# Run every gate in this repository, and fail if any of them does.
#
# There are three suites and they do not know about each other: `check.py`
# covers the oracle page and the findings write-ups, `learning/tools/preflight.sh`
# covers the nine chapters and the book they assemble into, and `check-memory.py`
# (in the private claude-config repo) covers the memory directory. Running only the
# first is the habit, because it is the one the oracle build prints at the end
# of `./build.py`. On 2026-09-07 a chapter gained a link the book generator
# could not rewrite; the book stopped being written, preflight went red, and two
# more commits landed on top of it before anyone ran the other suite. This
# exists so that cannot happen quietly again.
#
#   ./gates.sh              everything
#   ./gates.sh --offline    skip the live GitHub fetches
#   ./gates.sh site         just the oracle
#   ./gates.sh learning     just the chapters
#   ./gates.sh memory       just the memory directory
#   ./gates.sh commits      just the tock commit messages
#
# Exit status is the number of suites that failed, so `&&` chains work.

set -uo pipefail
cd "$(dirname "$0")"

WHICH=${1:-all}
OFFLINE=""
[ "$WHICH" = "--offline" ] && { OFFLINE="--offline"; WHICH=all; }

FAILED=0
run() {  # run <name> <command...>
    printf "\n\033[1m=== %s ===\033[0m\n" "$1"; shift
    if "$@"; then
        return 0
    fi
    FAILED=$((FAILED + 1))
    printf "\033[1m^^ that suite FAILED\033[0m\n"
}

if [ "$WHICH" = all ] || [ "$WHICH" = site ]; then
    run "oracle page and findings — check.py" ./check.py $OFFLINE
fi

if [ "$WHICH" = all ] || [ "$WHICH" = learning ]; then
    # preflight's own summary line is the report; it exits non-zero on failure.
    run "chapters and the book — preflight.sh" bash learning/tools/preflight.sh
fi

# The memory directory is prose about a moving world, and it drifts the same way
# this page's hand-written notes do -- a 2026-09-10 sweep found nine claims that
# a pull request was approved after both approvals had been dismissed. Its
# checker lives in the private claude-config repo, because the memory directory
# itself is markdown-only by design. Skipped rather than failed when that repo
# is not on this machine: a gate that cannot run is not a gate that failed.
MEMORY_GATE="./check-memory.py"
if [ "$WHICH" = all ] || [ "$WHICH" = memory ]; then
    if [ -x "$MEMORY_GATE" ]; then
        run "memory — check-memory.py" "$MEMORY_GATE" $OFFLINE
    else
        printf "\n\033[1m=== memory — check-memory.py ===\033[0m\n"
        printf "  skip  %s is not here\n" "$MEMORY_GATE"
    fi
fi

# Commit messages on the tock branches. CONTRIBUTING.md:125-133 caps the
# subject at 50 columns and wraps everything else at 72, and that rule was
# broken four times in one session by someone who had it quoted in front of
# them -- which is the argument for a gauge rather than another note. The
# commit-msg hook gives the fast local answer, but a hook in .git/hooks is
# never cloned and never reviewed, so this is the copy that endures. It reads
# only UNPUSHED commits, which is the set still amendable. Skipped
# rather than failed when the tock checkout is not on this machine.
TOCK_REPO="${TOCK_TREE:-$HOME/forge/tock}"
COMMIT_GATE="learning/tools/commit-msg-check.sh"
if [ "$WHICH" = all ] || [ "$WHICH" = commits ]; then
    # -e not -d: in a linked worktree .git is a FILE, and -d silently skips.
    if [ -e "$TOCK_REPO/.git" ] && [ -x "$COMMIT_GATE" ]; then
        BR=$(git -C "$TOCK_REPO" branch --show-current 2>/dev/null)
        # Scope: commits that are not yet pushed, which is exactly the set
        # still amendable without a force-push. Pushed history is deliberately
        # NOT audited -- 188 commits on learning/series predate the rule and
        # nobody is going to rewrite them, and a gate that fails work that
        # cannot be fixed is a gate that gets switched off.
        run "commit messages — unpushed on $BR" sh -c \
            "cd '$TOCK_REPO' && '$PWD/$COMMIT_GATE' --range '@{upstream}..HEAD'"
    else
        printf "\n\033[1m=== commit messages ===\033[0m\n"
        printf "  skip  %s is not a checkout here\n" "$TOCK_REPO"
    fi
fi

printf "\n"
if [ "$FAILED" -eq 0 ]; then
    printf "\033[1mall gates passed\033[0m\n"
else
    printf "\033[1m%d suite(s) failed\033[0m — nothing here is a warning; fix them.\n" "$FAILED"
fi
exit "$FAILED"
