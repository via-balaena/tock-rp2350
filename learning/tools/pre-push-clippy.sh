#!/bin/sh
# Refuse a push that would put a clippy failure on the fork.
#
# WHY THIS EXISTS. On 2026-09-16 a commit went to the fork with three
# `clippy::doc_lazy_continuation` errors in `kernel/src/hil/can.rs`. Nothing
# caught it: the commit-msg hook checks the message, the gates suite did not
# run clippy, and the person pushing had run `make clippy`, printed
# `clippy=2` next to `allboards=0` and `fmt=0`, and read past it. A check
# whose result is printed rather than obeyed is not a check.
#
# WHY IT IS NEARLY FREE. `make clippy` with nothing changed is about 0.8
# seconds; after touching one file it is about 16. Anything already checked
# before committing is warm by the time it is pushed, so this costs under a
# second exactly when the work was done properly, and sixteen seconds exactly
# when it was not. That is the right way round.
#
# `git push --no-verify` skips it, which is the documented escape and the
# reason this does not need one of its own. A hook with no way past it gets
# turned off wholesale the first time it is wrong.
set -eu

TOCK="${TOCK_MAIN:-$HOME/forge/tock}"
[ -f "$TOCK/Makefile" ] || exit 0

if make -C "$TOCK" clippy >/dev/null 2>&1; then
    exit 0
fi

echo "pre-push: refusing -- make clippy fails, and a push puts it on the fork." >&2
echo "" >&2
make -C "$TOCK" clippy 2>&1 | grep -E "^error" -A 6 | head -30 >&2
echo "" >&2
echo "Fix it, or push with --no-verify if you mean to." >&2
exit 1
