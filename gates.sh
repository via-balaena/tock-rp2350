#!/bin/bash
# Run every gate in this repository, and fail if any of them does.
#
# There are two suites and they do not know about each other: `check.py` covers
# the oracle page and the findings write-ups, `learning/tools/preflight.sh`
# covers the nine chapters and the book they assemble into. Running only the
# first is the habit, because it is the one the oracle build prints at the end
# of `./build.py`. On 2026-09-07 a chapter gained a link the book generator
# could not rewrite; the book stopped being written, preflight went red, and two
# more commits landed on top of it before anyone ran the other suite. This
# exists so that cannot happen quietly again.
#
#   ./gates.sh              everything
#   ./gates.sh --offline    skip check.py's live GitHub fetch
#   ./gates.sh site         just the oracle
#   ./gates.sh learning     just the chapters
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

printf "\n"
if [ "$FAILED" -eq 0 ]; then
    printf "\033[1mall gates passed\033[0m\n"
else
    printf "\033[1m%d suite(s) failed\033[0m — nothing here is a warning; fix them.\n" "$FAILED"
fi
exit "$FAILED"
