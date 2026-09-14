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
#   ./gates.sh claims       just the unreferenced-claim report (advisory)
#   ./gates.sh drift        just how far main has drifted from upstream
#   ./gates.sh uart         the hil::uart conformance test on both qemu boards
#   ./gates.sh parity       just the rp2040/rp2350 paired-block check
#   ./gates.sh errnames     just the documented-ErrorCode-name check
#   ./gates.sh abortidle    just the idle-abort contract check
#   ./gates.sh i2clen       just the i2c transfer-length check
#   ./gates.sh bench        the conformance tests that need real hardware
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

# Unreferenced causal claims in the oracle's own prose -- a sentence that
# asserts a mechanism while carrying nothing anyone could re-check. That is
# what cost tock#5156 its approvals.
#
# This is a GATE rather than a report, but only because of the baseline.
# Raw precision is about half: design reasoning and mechanism claims have
# the same shape and no regex separates them. Filtering the claims already
# judged leaves only what is NEW, and judging one new claim is cheap:
#
#   fix it            give it a file:line, a command, a number, a test
#   or say so         write that it is not established
#   or accept it      learning/tools/claim-gauge.py --write-baseline <file>
#                     >> learning/tools/claim-baseline.txt
#
# The baseline is keyed to sentence content, not position, so it survives
# renumbering and a reworded sentence correctly comes back for judging.
CLAIM_SURFACE=/tmp/.claim-surface.md
claims_gate() {
    [ -x learning/tools/claim-gauge.py ] || {
        echo "  skip  learning/tools/claim-gauge.py is not executable here"; return 0; }
    python3 - > "$CLAIM_SURFACE" 2>/dev/null <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("b", "build.py")
b = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(b)
except SystemExit:
    pass
out = []
for key, entries in b.FACTS.items():
    out.append("# " + key)
    for _head, body in entries:
        out.append(body)
print("\n\n".join(out))
PY
    if [ ! -s "$CLAIM_SURFACE" ]; then
        echo "  could not extract the FACTS prose -- that is a fact about the"
        echo "  parse, not the claims, so it is a failure and not a pass."
        rm -f "$CLAIM_SURFACE"; return 1
    fi
    learning/tools/claim-gauge.py --baseline learning/tools/claim-baseline.txt \
        "$CLAIM_SURFACE"
    rc=$?
    rm -f "$CLAIM_SURFACE"
    return $rc
}
if [ "$WHICH" = all ] || [ "$WHICH" = claims ]; then
    run "claims — unreferenced causal in FACTS" claims_gate
fi

# How far the fork's trunk has drifted from upstream. Since 2026-09-13 there
# are no pull requests, so a rebase or merge of upstream into `main` is the
# ONLY channel their work reaches us by -- see memory: fork-not-upstream.
#
# Threshold, not zero: upstream lands about 42 commits a week (measured
# 2026-09-13 over 7, 14 and 30 days), so failing on any drift would cry wolf
# daily. It fails at 75, which is under two weeks and below the 82-commit
# drift that cost a full re-pin pass once already.
#
# A stale answer is worse than none, so this fetches. With --offline it says
# it cannot tell rather than reporting a number it did not check.
TOCK_REPO="${TOCK_TREE:-$HOME/forge/tock}"
drift_gate() {
    [ -e "$TOCK_REPO/.git" ] || { echo "  skip  $TOCK_REPO is not a checkout here"; return 0; }
    if [ -n "$OFFLINE" ]; then
        echo "  skip  --offline: cannot tell how far main has drifted without fetching"
        return 0
    fi
    git -C "$TOCK_REPO" fetch upstream --quiet 2>/dev/null || {
        echo "  could not fetch upstream, so the drift is unknown rather than zero"
        return 1
    }
    behind=$(git -C "$TOCK_REPO" rev-list --count main..upstream/master 2>/dev/null)
    ahead=$(git -C "$TOCK_REPO" rev-list --count upstream/master..main 2>/dev/null)
    printf "  main is %s ahead of upstream/master and %s behind\n" "${ahead:-?}" "${behind:-?}"
    if [ "${behind:-0}" -ge 75 ]; then
        echo "  Absorb upstream into main. There is no other channel for their work,"
        echo "  and past 75 this becomes a re-pin pass rather than a merge."
        return 1
    fi
    return 0
}
if [ "$WHICH" = all ] || [ "$WHICH" = drift ]; then
    run "upstream drift — main vs upstream/master" drift_gate
fi

# The hil::uart conformance test, run for real rather than read. An audit on
# 2026-09-13 found ELEVEN of eleven guarantees violated somewhere in the tree,
# and the fixes for them are only protected if something executes the clauses.
# qemu_rv32_virt boots in about two seconds and reports a verdict, so this is
# cheap enough to run on every pass.
#
# It cannot cover the clauses that need hardware -- the byte-matching ones run
# on the Pico. What it does cover is the virtualizer, which is where the
# word-transmit wedge lived, and qemu_virt_chip underneath it.
#
# The runner's own exit codes matter: 1 is a broken clause, 2 is a test that
# said nothing at all. The second is the one worth having, because a stalled
# conformance test and a passing one look identical from a distance.
TOCK_MAIN="${TOCK_MAIN_TREE:-$HOME/forge/tock-wt/distro}"
#
# TWO platforms since 2026-09-13, and they are not redundant: rv32 runs the
# test on a UartDevice from the console's mux, so it covers the VIRTUALIZER,
# while q35 hits x86_q35::serial::SerialPort directly -- the driver the audit
# found panicking on both word methods, guarded by nothing until now.
uart_gate() {
    runner="$TOCK_MAIN/tools/ci/uart-contract-qemu.sh"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    rc=0
    # One missing emulator must not hide the other platform, and must not
    # pass as though its clauses had run.
    if command -v qemu-system-riscv32 > /dev/null 2>&1; then
        "$runner" rv32 || rc=1
    else
        echo "  skip  qemu-system-riscv32 is not installed, so rv32 went unrun"
    fi
    if command -v qemu-system-i386 > /dev/null 2>&1; then
        "$runner" q35 || rc=1
    else
        echo "  skip  qemu-system-i386 is not installed, so q35 went unrun"
    fi
    return "$rc"
}
if [ "$WHICH" = all ] || [ "$WHICH" = uart ]; then
    run "hil::uart conformance — qemu, two architectures" uart_gate
fi

# chips/rp2040 and chips/rp2350 are separate files driving the same PL011. The
# overrun report was measured on an rp2350 and COPIED to the rp2040, where
# there is no board to run it on -- so that copy is the whole warrant for the
# rp2040 half, and it is a claim about two files rather than about hardware.
# Which means it can be checked. Without this it is a comment that keeps
# reading true after someone fixes one driver and not the other.
parity_gate() {
    runner="$TOCK_MAIN/tools/ci/check-rp2-uart-parity.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = parity ]; then
    run "rp2 uart parity — rp2040 vs rp2350" parity_gate
fi

# `hil::uart` documented `Err(ENOSUPPORT)`, which is not an ErrorCode variant,
# so it described a return no implementation could produce -- and because doc
# comments are not compiled, nothing noticed for two years. Quoting a HIL
# sentence into the driver that obeys it then carried the wrong name into 37
# more comments in a day. One wrong word is cheap; one wrong word everything
# downstream quotes is not.
errnames_gate() {
    runner="$TOCK_MAIN/tools/ci/check-hil-error-names.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = errnames ]; then
    run "documented error names — every Err(NAME) resolves" errnames_gate
fi

# `hil::uart` says an abort with nothing outstanding answers `Ok(())`, and
# that any `Err` promises a callback. A body that answers `Err` unconditionally
# breaks both at once: it refuses an idle abort, and the refusal promises a
# callback nothing will send, so the caller waits for its buffer for the life
# of the board. Twelve drivers did this, one of them in the same file whose
# transmit half was already guarded.
abortidle_gate() {
    runner="$TOCK_MAIN/tools/ci/check-uart-abort-idle.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = abortidle ]; then
    run "uart abort — an idle abort can answer Ok(())" abortidle_gate
fi

# `hil::i2c` documented no errors at all -- not one method of `I2CMaster`,
# `I2CSlave` or `I2CDevice` carried a doc comment -- so a length argument and
# the buffer it indexes were related by nothing. One driver of eleven checked.
# In most the excess indexes a slice and panics; in nrf52 and sam4l it is
# programmed into a DMA engine and runs off the end of the buffer.
i2clen_gate() {
    runner="$TOCK_MAIN/tools/ci/check-i2c-length-guard.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = i2clen ]; then
    run "i2c length — every transfer bounds-checks its length" i2clen_gate
fi

# The conformance tests that need hardware: nothing emulated exposes SPI or
# GPIO, and the pad-level uart clauses need a wire. NOT part of `all` -- it
# flashes two boards and takes about a minute, and a bench that is powered off
# should not fail a routine gate run. Ask for it: ./gates.sh bench
bench_gate() {
    runner="$TOCK_MAIN/tools/ci/bench-contracts.sh"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = bench ]; then
    run "hil conformance — Pico 2 W and STM32F3 Discovery" bench_gate
fi

printf "\n"
if [ "$FAILED" -eq 0 ]; then
    printf "\033[1mall gates passed\033[0m\n"
else
    printf "\033[1m%d suite(s) failed\033[0m — nothing here is a warning; fix them.\n" "$FAILED"
fi
exit "$FAILED"
