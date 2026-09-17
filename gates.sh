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
#   ./gates.sh flash        the hil::flash conformance test on qemu pflash
#   ./gates.sh parity       just the rp2040/rp2350 paired-block check
#   ./gates.sh errnames     just the documented-ErrorCode-name check
#   ./gates.sh hilerrdocs   just the HIL error-documentation ratchet
#   ./gates.sh clippy       just the clippy subset (durable half of the hook)
#   ./gates.sh abortidle    just the idle-abort contract check
#   ./gates.sh i2c          just the i2c transfer-contract check
#   ./gates.sh safety       just the SAFETY:-comment attachment check
#   ./gates.sh irqroute     just the held-peripheral interrupt-routing check
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
    # NOT_MINE lets check_intent and check_facts tolerate a branch in a
    # repository this session does not write. Four other checks read the same
    # rows, and whether the exemption leaks into them is a property of check.py
    # that no run of check.py can show -- it is green either way. This breaks
    # each of the four on purpose, on a branch of theirs.
    run "the NOT_MINE exemption — test-not-mine.py" ./test-not-mine.py
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
# `main` lives in the primary checkout since 2026-09-14, not in a worktree --
# tock-wt/ is gone. Left overridable because the tree it names must be ON main,
# and a checkout parked on a feature branch would run the wrong kernel here.
TOCK_MAIN="${TOCK_MAIN_TREE:-$HOME/forge/tock}"
#
# TWO platforms since 2026-09-13, and they are not redundant: rv32 runs the
# test on a UartDevice from the console's mux, so it covers the VIRTUALIZER,
# while q35 hits x86_q35::serial::SerialPort directly -- the driver the audit
# found panicking on both word methods, guarded by nothing until now.
uart_gate() {
    runner="$TOCK_MAIN/tools/ci/contract-qemu.sh"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    rc=0
    # One missing emulator must not hide the other platform, and must not
    # pass as though its clauses had run.
    if command -v qemu-system-riscv32 > /dev/null 2>&1; then
        "$runner" rv32 uart || rc=1
    else
        echo "  skip  qemu-system-riscv32 is not installed, so rv32 went unrun"
    fi
    if command -v qemu-system-i386 > /dev/null 2>&1; then
        "$runner" q35 uart || rc=1
    else
        echo "  skip  qemu-system-i386 is not installed, so q35 went unrun"
    fi
    return "$rc"
}
if [ "$WHICH" = all ] || [ "$WHICH" = uart ]; then
    run "hil::uart conformance — qemu, two architectures" uart_gate
fi

# `hil::flash` has nine implementations and eight of them need silicon. The
# ninth is QEMU's pflash, and no board had ever instantiated it -- here or
# upstream -- because the kernel's MMIO PMP window on qemu_rv32_virt ends at
# 0x20000000, which is the first byte of the pflash bank. So the one
# implementation an emulator could run was the one nothing ran, and the audit
# of that HIL had to go to the bench. Wiring it is what makes this gateable.
flash_gate() {
    runner="$TOCK_MAIN/tools/ci/contract-qemu.sh"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    if command -v qemu-system-riscv32 > /dev/null 2>&1; then
        "$runner" rv32 flash
    else
        echo "  skip  qemu-system-riscv32 is not installed, so flash went unrun"
    fi
}
if [ "$WHICH" = all ] || [ "$WHICH" = flash ]; then
    run "hil::flash conformance — qemu pflash" flash_gate
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

# The complement of the check above: that one asks whether a documented error
# name is real, this one asks whether a fallible method documents any at all.
# AGENTS.md requires it and nothing enforced it, which is how `hil::i2c`
# reached twenty-one methods and eleven disagreeing drivers with no contract
# written down, and `hil::adc` eighteen methods whose drivers could not agree
# what `sample` returns when it is busy.
#
# A RATCHET rather than a standard: half the tree names no error today, so a
# gate demanding them all would be red on every run and off by Friday. It
# fails when a file documents FEWER than it used to, or gains a fallible
# method and documents none of them. `--worklist` prints what is left, largest
# gap first, which is where the next audit comes from.
hilerrdocs_gate() {
    runner="$TOCK_MAIN/tools/ci/check-hil-error-docs.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = hilerrdocs ]; then
    run "HIL error docs — no file names fewer than it did" hilerrdocs_gate
fi

# The durable half of the pre-push hook. A commit reached the fork on
# 2026-09-16 with three clippy errors in it: the commit-msg hook checks the
# message, nothing here ran clippy, and the person pushing had run it, printed
# the exit code beside two others and read past it. The hook refuses such a
# push; this catches it even where the hook is not installed, which is every
# fresh clone, since `.git/hooks` is never cloned.
#
# Cheap: `make clippy` with nothing changed is under a second.
clippy_gate() {
    [ -f "$TOCK_MAIN/Makefile" ] || { echo "  skip  no tock tree at $TOCK_MAIN"; return 0; }
    if make -C "$TOCK_MAIN" clippy >/dev/null 2>&1; then
        echo "  ok      make clippy is clean"
        return 0
    fi
    make -C "$TOCK_MAIN" clippy 2>&1 | grep -E "^error" -A 4 | head -20
    return 1
}
if [ "$WHICH" = all ] || [ "$WHICH" = clippy ]; then
    run "clippy — the enforced subset is clean" clippy_gate
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
# `I2CSlave` or `I2CDevice` carried a doc comment -- so eleven drivers had
# nothing to diverge from. Three rules of the contract are visible in the
# source: a length past its buffer is Size (one driver of eleven checked, and
# on nrf52 and sam4l the excess goes to a DMA engine), a transfer while one is
# outstanding is Busy (three drivers had no such check anywhere), and
# ArbitrationLost is a bus event an interrupt reports, not something a call can
# answer (eleven sites used it to mean busy).
i2c_gate() {
    runner="$TOCK_MAIN/tools/ci/check-i2c-transfer-contract.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = i2c ]; then
    run "i2c transfers — Size, Busy, and no ArbitrationLost" i2c_gate
fi

# AGENTS.md requires every `unsafe` to carry a comment saying why it is sound.
# The converse is not written anywhere and turns out to matter: psc3 and
# psoc62xa used the same form to excuse five `unwrap()`s each, which makes a
# panic look reviewed -- and because those two drivers are near-identical, it
# had already been copied once.
safety_gate() {
    runner="$TOCK_MAIN/tools/ci/check-safety-comments.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = safety ]; then
    run "SAFETY: comments — every one sits on unsafe code" safety_gate
fi

# `service_pending_interrupts` panics when `service_interrupt` returns false,
# and the poll path that feeds it reads ISPR rather than ISER -- so a line the
# NVIC has disabled still gets there the moment its peripheral asserts it.
# chips/rp2040 held a `uart1` whose driver sets UARTIMSC::TXIM while UART1_IRQ
# was routed nowhere; no board uses UART1, so nothing had ever hit it.
irqroute_gate() {
    runner="$TOCK_MAIN/tools/ci/check-rp2-interrupt-routing.py"
    [ -x "$runner" ] || { echo "  skip  no runner at $runner"; return 0; }
    "$runner"
}
if [ "$WHICH" = all ] || [ "$WHICH" = irqroute ]; then
    run "held peripherals — every interrupt line reaches a handler" irqroute_gate
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
