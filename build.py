#!/usr/bin/env python3
"""Build index.html — a dependency graph of the Tock/RP2350 work.

The page exists to answer two questions a reviewer asked out loud: which
commits belong to which pull request, when one branch is a stack that GitHub
cannot express; and what the testing strategy is. Both are answered by the
graph rather than by prose.

Everything structural is derived, not asserted. Nodes are the distinct commits
across every pull request. Edges come from commit order inside each branch.
"These two branches collide" comes from comparing file lists. Only the short
labels, the verification badges and the prose are hand-written, and they live
in WORK below.

    ./build.py            # fetch, then write data.json and index.html
    ./build.py --offline  # rebuild from the cached data.json, no network

Requires the `gh` CLI, authenticated.
"""

import argparse
import html
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).parent
REPO = "tock/tock"
AUTHOR = "bigmark222"

# Local clones the queue is read from. Missing ones are skipped, so the build
# still works on a machine that only has some of them — the survey is cached
# into data.json and --offline renders from that.
LOCAL = {
    "tock": (pathlib.Path.home() / "forge/tock", "upstream/master"),
    "libtock-rs": (pathlib.Path.home() / "forge/libtock-rs", "upstream/master"),
    "book": (pathlib.Path.home() / "forge/book", "origin/master"),
}

# --------------------------------------------------------------------------
# Prose and hand annotation. Everything else is derived.
# --------------------------------------------------------------------------

SITE = {
    "title": "Tock on the RP2350",
    "tagline": "A dependency graph of one contributor's work on the Raspberry Pi Pico 2 and Pico 2 W.",
}

PROVOCATION = {
    "quote": (
        "I'm thoroughly confused. I guess the tests were added to the chip crate "
        "in one PR, used in a different PR for testing, but reverted from the "
        "second PR's main.rs changes before the second PR was merged. [...] It "
        "doesn't seem like there is a clear testing/bring up strategy for the "
        "rp2x PIO."
    ),
    "who": "bradjc",
    "where": "#5126",
    "url": "https://github.com/tock/tock/pull/5126",
    "answer": """
That was fair, and this page is the answer to it. The work is a stack: one long
chain of commits where each depends on the one before, and the early links are
also open as small reviewable pull requests of their own. GitHub cannot express
a stack when the branches live in a fork, so the same commit appears in two
places and reads as the same work submitted twice.

Below is that stack, drawn. Click a pull request to light up exactly the commits
it carries. Every node also shows how it is checked, which is the other half of
the question: a pure code move is proved by the binary coming out with identical
sections, logic is covered by a host test that fails without the change, and
anything touching hardware is run on a board.
""",
}

# The rule this whole pipeline runs on. Stated publicly because a maintainer
# cannot tell a finite queue from a firehose by looking at it.
POLICY = """
The fork moves at whatever speed the work goes; upstream gets a trickle. Nothing
is proposed until it is finished, demonstrated and small enough to review in one
sitting, and only a few are in flight at a time — the constraint upstream is
review throughput, not how fast patches can be written. Everything below exists
as working code on the fork. The column it sits in is a decision about when to
ask someone to read it, not about whether it is done.
"""

# What each local branch is for. Keyed "repo:branch".
#   upstream — intended for tock, in the queue
#   never    — a bench or teaching branch that will never be proposed
INTENT = {
    "tock:rp2-pio-prep": ("upstream", "PIO cleanups.", None),
    "tock:rp2-make-program-fix": ("upstream", "Fixes #4770: `make program` cannot flash an application on any RP2 board, because splicing one in gives the (NOLOAD) `.stack` segment file content for SRAM and both UF2 converters refuse the result. One `objcopy -R .stack` per rule, five rules, four boards.", "**Open as #5156**, ready for review, rebased onto master as `d5b5f7cbc`. The first attempt, #5154, was closed the same day it was opened -- for a placeholder description, not for the change -- and could not be reopened afterwards because the branch had been force-pushed. Its evidence is the reporter's own RP2040 run plus a `program-openocd` A/B on RP2350 silicon. Four Makefiles, twenty-one added lines, no Rust. Touches `boards/raspberry_pi_pico_2/Makefile`, which #5141 also edits -- different regions of the file, so it merges cleanly either order."),
    "tock:rp2-local-board": ("upstream", "Replaces the ELF splice on all four RP2 boards with a flash image built by `tockloader local-board`: the kernel binary at the base of flash, applications installed from `.tab` archives, and the flat image handed to picotool, openocd or probe-rs. elf2uf2-rs leaves the tree. Two commits, eight files, +180 -73.", "Written and pushed as `d8493d154`, **not proposed**. This is the successor bradjc asked for on #5156 and the answer given there. It supersedes that PR's `objcopy -R .stack` on the boards it touches, and is based on `e2ec78ff5` rather than on that branch, so either can merge first. Touches the same two README lines as #5158. The Pico 2 half ran on silicon; **no RP2040 was ever booted** -- there is no such board here and mainline QEMU has no machine for it."),
    "tock:rp2-doc-fixes": ("upstream", "Three places the documentation disagrees with the code: two RP2 board READMEs name a `make` target that does not exist, the ADC syscall document never states the left-justification the HIL guarantees, and the GPIO capsule's pull encoding is rotated by one from the enum it translates into. Four files, +16 -3.", "**Open as #5158**, head `6319b0ca4`. lschuermann approved it within the hour and that approval was then **dismissed by the force-push** that dropped a commit -- a review is made against a head, and moving the head discards it. Two commits now, not three: he objected to the GPIO comment and was right — `FloatingState` has no `#[repr()]`, integer-to-enum `as` does not compile (E0605), and `unsafe` is banned in capsules outright, so the hazard that comment described was unreachable. Dropped rather than defended. The ADC commit was also amended before opening: it said the HIL promises left-justification three times, and it is seven, across all three of its traits."),
    "tock:rp2-pad-controls": ("upstream", "Shared pad enums and the RP2350 pad controls.", None),
    "tock:pico2w-typed": ("upstream", "The Pico 2 W board and the radio.", None),
    "tock:rp2-pio-tests": ("upstream", "Five PIO fixes and the driver's first host tests. Four defects demonstrated by tests that fail on unmodified upstream; one of them panics the kernel.", "**Was #5150, closed 2026-09-07** -- for a PR body written by AI under a checkbox promising it would not be, which is the one part of that close not worth contesting. **STILL REOPENABLE, and fragile: force-pushing this branch would end that permanently**, as it did to #5154. Reopen first, rebase after. Needs a description in Jon's own words; the existing one is 5,714 characters against a house median near 1,200."),
    "tock:boards-fix-ram-layout": ("upstream", "Merged.", None),
    "tock:boards-remove-dead-ram-layout": ("upstream", "Closed in favour of fixing the addresses.", None),
    "tock:stepper-capsule": ("upstream", "A stepper motor capsule: four phase pins driven from the capsule's own alarm, with the owning process's liveness checked before every step.", "Undecided whether it goes upstream at all. A new syscall driver means a new driver number and new API surface, which is a materially different ask from a bug fix — it must not become a fourth thing waiting behind the three descriptions."),
    "tock:rp2-adc": ("upstream", "Moves the SAR ADC driver into the shared rp2xxx crate, adds the RP2350's, and wires it up on the Pico 2 so driver 0x00005 answers. Three commits, the same shape as #5112, which merged.", "Ready. Unblocks the whole analogue tier of the breadboard kit — joystick, potentiometer, light sensor, thermistor — none of which needs new wiring."),
    "tock:rp2350-gpio-irq": ("upstream", "Routes IO_IRQ_BANK0 on the RP2350, which is defined and referenced nowhere else, so enabling a GPIO interrupt panics the kernel.", "Ready, and four lines. Independent of everything else in the queue."),
    "tock:rp2-uart-abort-fix": ("upstream", "The fix for all three UART defects: the abort ordering in the three chip drivers, and the two buffer-ownership bugs in the mux. Three commits, each building standalone, no size change on any board.", "Verified by A/B under QEMU on the pinned hifive1 kernel — Err(BUSY) without it, the read left outstanding with it, and 16 bytes typed completing it Ok. Waiting only on a pull request description."),
    "tock:rp2350-spi-bench": ("never", "A bench harness that drives the SPI loopback.", None),
    "tock:pico2w-radio-bench": ("never", "Every commit titled NOT FOR UPSTREAM: it starts the radio from the board so a scan can be driven without an app.", None),
    "tock:bench/stepper-pico2w": ("never", "The Pico 2 W branch, the stepper capsule and a board wiring for GPIO 18-21, merged so the motor can actually be driven. A vehicle, not a contribution: the capsule is cut from master and the board only exists on #5141, so there is nowhere upstream the two currently meet.", None),
    "tock:bench/reclaim-leak-demo": ("never", "Reproduces the GPIO reclaim leak on a board.", None),
    "tock:bench/uart-fix-at-pinned-rev": ("never", "The UART abort fix applied at the revision libtock-rs pins, which is where the A/B behind rp2-uart-abort-fix was actually run \u2014 the reproduction application does not load on a master kernel. Kept so the measurement can be repeated rather than only cited.", None),
    "tock:learning/series": ("never", "The merged tree the course cites. The nine chapters moved to the site repository and are published at /read/; what is left here is the kernel work they were written against, kept because every chapter pins one commit on it and no other tree resolves those citations \u2014 upstream resolves 7 of the 14, #5140 six, #5141 seven, and the bench kernel, which contains all of it, also seven, because each later branch shifts the same file further along.", "Not a queue item. Retires itself when the chapters stop citing line numbers, or when #5140 and #5141 land and the citations are re-pinned to upstream."),
    "tock:master": ("never", "Tracking branch.", None),
    "libtock-rs:stepper": ("upstream", "The userspace half of the stepper: `libtock_stepper` and an example that turns a revolution each way.", "Paired with tock:stepper-capsule and gated on the same undecided question. Neither half is useful without the other."),
    "libtock-rs:unittest-fakes": ("upstream", "Two fixes to the test fakes: model alarm expiration so cancellation can be asserted, and model an outstanding receive in the console fake.", "The first thing proposed anywhere in libtock-rs, and deliberately the smallest — it is independently useful, hard to argue with, and the async series cannot go until it does."),
    "libtock-rs:platform-pico2": ("upstream", "The Raspberry Pi Pico 2 build platform row, plus a build error that named neither the platform nor the file to edit.", "Ready. Split out from pico2-platform so that it carries nothing depending on an unmerged board."),
    "libtock-rs:pico2-platform": ("upstream", "The original three commits, now superseded: what is ready went to platform-pico2, and what is left is the Pico 2 W row.", "Waits for its board. The W platform row names raspberry_pi_pico_2_w, which is #5141 and not upstream, so this cannot go until that lands."),
    "libtock-rs:async/alarm": ("upstream", "Futures over the alarm and console drivers, a single-task executor, select, and fakes that model cancellation. Meant to become two pull requests, but it is not two branches yet: the two unittest commits sit inside this one and have to be lifted out first.", "Hard order, not a preference. The async tests call fake::Alarm::new_deferred and fake::Console::new_deferred in three places, and those constructors are exactly what the unittest commits add — so either the unittest fixes land first and the async work builds on them, or the async pull request carries both commits itself. It cannot go first and cannot go alone. The branch still carries both commits inside it, and which way that resolves depends on how unittest-fakes is received: rebase to drop the duplicates if it merges, ship as-is if it does not. Deliberately not decided in advance, because guessing means doing the work twice."),
    "libtock-rs:hw/pico2w-async": ("never", "The two branches above merged together, as a vehicle for running on hardware — and, for now, the only home of `examples/console_read_busy.rs`, the QEMU reproduction of the UART defect.", "The branch itself is not for upstream, but the reproduction on it is meant to be run by other people, so it needs a home that is. Where it goes depends on whether it travels with a defect report or stands alone as a libtock-rs example."),
    "libtock-rs:bench/reclaim-leak": ("never", "The two apps that demonstrate the reclaim leak.", None),
    "libtock-rs:kit-examples": ("never", "Loopback and pin-walk apps written to exercise the bench.", None),
    "libtock-rs:master": ("never", "Tracking branch.", None),
    "book:pico2-getting-started": ("upstream", "A getting-started page for the Pico 2. The book has no Pico coverage at all.", "Written and green; waiting on its pull request description."),
    "book:master": ("never", "Tracking branch.", None),
}

# How a unit of work is verified. This vocabulary is the testing strategy.
VERIFY = {
    "host": ("host test", "A test in the tree that fails if the change is reverted."),
    "silicon": ("on silicon", "Run on a real board and observed, not inferred."),
    "sections": ("identical sections", "A pure move: the linked binary comes out with the same text, data and bss, so the change provably alters no behaviour."),
    "build": ("build only", "Checked by the thing building or linking, and nothing further."),
    "none": ("unchecked", "No automated check reaches this."),
}

# Keyed by exact commit headline. Anything fetched but absent here still
# renders, unannotated: new work must appear on the page rather than vanish
# because this table was not updated.
WORK = {
    "boards: declare all 520 kB of SRAM on Pico 2": {
        "short": "Declare all 520 kB of SRAM",
        "verify": "build",
        "note": "The board declared a fraction of the RAM the chip has.",
    },
    "boards: remove dead boot-from-RAM layout": {
        "short": "Remove the boot-from-RAM layout",
        "verify": "none",
        "note": "Closed. A maintainer pointed out that the Pico can boot from RAM and the addresses should be fixed instead, which became #5109.",
    },
    "boards: give the boot-from-RAM layout addresses that link": {
        "short": "Fix the boot-from-RAM addresses",
        "verify": "silicon",
        "note": "The layout was in the tree and could not have linked.",
    },
    "chips: rp2040: move the PL022 SPI driver into a shared rp2xxx crate": {
        "short": "Move PL022 SPI into a shared crate",
        "verify": "sections",
        "note": "Creates rp2xxx, the crate both chips share. Everything downstream lives there.",
    },
    "chips: rp2350: add SPI driver": {
        "short": "Add SPI to the RP2350",
        "verify": "silicon",
        "note": "A loopback app writes and reads back a 32-byte pattern, varied so a stuck line cannot pass it.",
    },
    "Update chips/rp2xxx/README.md": {
        "short": "rp2xxx README",
        "verify": "none",
    },
    "chips: rp2040: pio: retire the examples module": {
        "short": "Retire the PIO examples module",
        "verify": "none",
        "note": "Dead API in a driver constrains every later change while proving nothing.",
    },
    "chips: rp2xxx: share the GPIO pad control enums": {
        "short": "Share the GPIO pad enums",
        "verify": "sections",
    },
    "chips: rp2350: gpio: add the pad controls the RP2040 has": {
        "short": "Add RP2350 pad controls",
        "verify": "silicon",
        "note": "Drive strength, slew rate and Schmitt trigger. This code has run on silicon in the radio bring-up, though a completed scan does not prove the analog bit positions; the datasheet does.",
    },
    "chips: rp2040: move the PIO driver into the shared rp2xxx crate": {
        "short": "Move the PIO driver into rp2xxx",
        "verify": "sections",
    },
    "chips: rp2350: add PIO": {
        "short": "Add PIO to the RP2350",
        "verify": "silicon",
        "note": "The one chip-specific constant no unit test can reach, the interrupt block's offset, was checked by reading the registers over the debug port.",
    },
    "chips: rp2350: add DMA": {
        "short": "Add DMA to the RP2350",
        "verify": "host",
        "note": "The five control-register shifts that differ between the chips have tests on both sides, each confirmed to fail when given the other chip's value.",
    },
    "chips: rp2040: move the PIO gSPI driver into the shared rp2xxx crate": {
        "short": "Move the gSPI driver into rp2xxx",
        "verify": "sections",
    },
    "boards: pico 2: resolve openocd config path": {
        "short": "Fix the openocd config path",
        "verify": "build",
        "note": "Only broken when a sibling board includes the Makefile, which is exactly how a derived board reuses it.",
    },
    "boards: pico 2: split into library and binary": {
        "short": "Split Pico 2 into library and binary",
        "verify": "sections",
        "note": "Section sizes identical; the stripped binary is not, and cannot be, because compiling into a library changes where the optimiser starts.",
    },
    "boards: add Raspberry Pi Pico 2 W": {
        "short": "Add the Pico 2 W board",
        "verify": "silicon",
        "note": "The Pico 2's LED pin is the radio's chip select here, so a stock Pico 2 kernel asserts it at boot and holds it. Measured on both boards, alternating, so it is not residue.",
    },
    "chips: rp2350: hold the DMA and PIO0 in the default peripherals": {
        "short": "Hold DMA and PIO0 in peripherals",
        "verify": "silicon",
    },
    "boards: raspberry_pi_pico_2_w: bring up the CYW43439": {
        "short": "Bring up the CYW43439 radio",
        "verify": "silicon",
        "note": "Reads its MAC from the radio's OTP and completes a scan, which means 231 kB of firmware went up over a PIO state machine and a DMA channel on a chip that had neither.",
    },
    "chips: rp2040: fix the PIO RX FIFO join, which never happened": {
        "short": "Fix the RX FIFO join",
        "verify": "host",
        "note": "Joining two four-word FIFOs into one eight-word FIFO silently did nothing.",
    },
    "chips: rp2040: stop add_program panicking on half of its own range": {
        "short": "Stop add_program panicking",
        "verify": "host",
        "note": "Loading into the upper half of instruction memory panicked the kernel instead of returning an error.",
    },
    "chips: rp2040: test the PIO arithmetic that has no other check": {
        "short": "Test the PIO arithmetic",
        "verify": "host",
    },
    "chips: rp2040: service every PIO interrupt line, not one of four": {
        "short": "Service every PIO interrupt line",
        "verify": "host",
        "note": "Three of the four state machines could raise an interrupt that nothing handled.",
    },
    "chips: rp2040: an irq flag belongs to the block, not a state machine": {
        "short": "Scope the irq flag to the block",
        "verify": "host",
    },
    "boards: rp2: name a make target that exists in the README": {
        "short": "Name a make target that exists",
        "verify": "build",
        "note": "Two RP2 READMEs told a reader to flash an application with `make flash-app`, which neither board has -- make itself says so. It is `program` on both, and each README already said that in its other flashing section.",
    },
    "doc: syscalls: adc: say that samples are left-justified": {
        "short": "Say ADC samples are left-justified",
        "verify": "none",
        "note": "The HIL promises left-justification seven times across its three traits; the syscall document an application author reads never said it, which invites scaling the value by the wrong constant. Nothing automated reaches a sentence in a document.",
    },
    "rp2: strip .stack from the ELF that make program flashes": {
        "short": "Strip .stack from the flashed ELF",
        "verify": "silicon",
        "note": "Fixes #4770. PR #5154 was closed for want of a written description. The change itself is confirmed on hardware twice over: the reporter ran it on an RP2040, and program-openocd was A/B'd on an RP2350.",
    },
}

# The facts a pull request description would rest on, per unsent branch.
# Written by hand and verified; the commit list, diffstat and base underneath
# them are derived. Kept here so that the person writing the description and a
# reviewer who goes looking are reading the same evidence.
FACTS = {
    "tock:rp2-make-program-fix": [
        ("What it fixes", "`make program` fails on every RP2 board with `ELF contains memory contents for uninitialized memory at 20000000`, reported as #4770 in April and never answered. Rewriting `.apps` makes objcopy lay the program headers out again, and the `(NOLOAD)` `.stack` segment comes back with a non-zero `p_filesz` where the linked kernel had 0. Both UF2 converters are right to refuse it."),
        ("Why nothing caught it", "The *section* stays `NOBITS` throughout — only the segment is wrong. Anything reading the section table sees a correct file, and UF2 converters go by segments. There is also no CI path that builds a kernel with an app spliced in."),
        ("Evidence, before and after, on four boards", "Not the objcopy steps in isolation: each board's real `make` target run with a 4,096-byte stand-in `.tbf`, with the change and with it stashed. Without it all four fail and leave no usable UF2 — picotool leaves a zero-byte one. With it all four exit 0 and the application is in the image, 16 blocks at 0x10040000, decoded from the UF2 block headers rather than inferred from an exit status. That distinction is load-bearing: llvm-objcopy updates the section and leaves the program header alone, producing a UF2 that converts cleanly and contains no application."),
        ("Why this spelling", "Six candidates measured. `alloc,contents` and `alloc,load,contents` behave exactly as `LOAD,ALLOC` does, so no wording of the first objcopy avoids it; `--set-section-flags .stack=noload` is worse, leaving the segment with its virtual address moved and its physical address behind. `-R .stack` is the only one that works, and it costs nothing — the section reserves stack and carries no bytes, and it is dropped only from `<platform>-app.elf`, not from the kernel ELF."),
        ("What is not covered", "The two rules that end in openocd and probe-rs rather than a converter. Both build the same broken file today and both are fixed by the same line, but whether those tools reject it or write 5,376 bytes into the stack region has not been checked — that needs a board. Nothing here is tested on hardware; the claim is about the files."),
        ("Written up", "The full measurement, including the six-candidate matrix and the script that produced it, is at /findings/4770/ on this site."),
    ],
    "tock:rp2-local-board": [
        ("Why it retires #4770 instead of patching it", "The defect needs an ELF to happen to: giving `.apps` file content makes objcopy lay the program headers out again, and the `(NOLOAD)` `.stack` segment comes back claiming file content for SRAM. This route never opens an ELF -- the only objcopy in the chain is the kernel's own ELF-to-binary step, which the build already performs. #5156 removes the symptom; this removes the conditions."),
        ("On silicon", "`make program-openocd APP=...tab` was run unmodified against a Pico 2 W over a Debug Probe, with openocd executing on the machine holding the probe. It programs, verifies and resets, and the kernel's own process console lists the application as a live process -- `PID 0 blink, 177 syscalls, Yielded`. `make program` produces 1,029 blocks in family 0xe48bff59 whose payload, reassembled from the block headers, is byte-identical to the image that booted."),
        ("The stale slot, and the one byte that closes it", "The kernel's loader stops at the first invalid TBF header rather than scanning on -- checked by placing a valid application one sector further along and watching it never appear. So only the slot immediately after the last application can resurrect an old one. tockloader writes a zero byte there; splicing writes nothing. Two images differing by that byte alone were flashed over an identical board state: without it the kernel loaded an application that was not in the image it was given. That is a defect in the route in the tree, not a caveat about this one."),
        ("The converter swap, measured", "elf2uf2-rs reads only ELF, so it cannot convert a flash image; wrapping the image back into one produces a file with no program headers, refused with `Unrecognized ABI 97`. picotool takes the binary directly. From the same `raspberry_pi_pico.elf` both emit 400 blocks in family 0xe48bff56 across the same 102,400 addresses with **zero byte disagreements**, so `make flash` is unchanged in everything but the command. Converting the image, picotool writes a further 159,744 bytes, every one of them zero, filling unused flash before the application address."),
        ("What it costs", "The application UF2 grows from 208,896 to 528,896 bytes on the RP2040 boards; the kernel-only UF2 is unchanged at 204,800. `APP` becomes a `.tab` archive rather than a bare `.tbf`, because that is what tockloader installs -- a user-visible change to both READMEs. tockloader becomes a requirement, and `local-board set` records one board at a time in tockloader's own configuration; the Makefiles set it on every build so the rule cannot inherit another board's addresses."),
        ("What was not run", "No RP2040 was booted -- there is no such board here and no emulator for one. What was checked on those three is that each real make target completes, that the image begins with that board's own kernel binary byte for byte, and that the UF2 carries the image verbatim with a valid TBF header at the application address, using applications built for cortex-m0. `program-probe` moves to `probe-rs download --binary-format bin`; the flags are real but the invocation was never run, because the machine holding the probe has no probe-rs."),
        ("Written up", "The full measurement, including the silicon transcripts and the one-byte A/B, is at /findings/5156/ on this site."),
    ],
    "tock:rp2-doc-fixes": [
        ("The README one, and it fails for a reader today", "`raspberry_pi_pico_2` and `pico_explorer_base` both tell you to flash an application with `APP=\"...\" make flash-app`. Neither board has that target: `make: *** No rule to make target `flash-app'.  Stop.` It is `program` on both. `flash-app` is in neither Makefile nor `boards/Makefile.common`, and `git log -S` finds it in neither at any point, so this is not a rename that left the documentation behind \u2014 it arrived with the board. Each README already says `make program` in its *second* \"Flashing app\" section, under the SWD route, so the two halves of one document disagreed and only the first one failed."),
        ("The ADC one, and who it costs", "`kernel/src/hil/adc.rs` promises three times \u2014 on `sample`, `sample_continuous` and `sample_highspeed` \u2014 that \"All ADC samples will be the raw ADC value left-justified in the u16\". `doc/syscalls/00005_adc.md`, which is the document an application author actually reads, never mentions it; it says only that the number of bits per sample is chip specific. That invites reading the callback value as a right-aligned n-bit number and scaling it by the wrong constant."),
        ("The GPIO one is not a doc error", "`doc/syscalls/00004_gpio.md` is correct and matches the code. The mismatch is between two source files: the syscall encodes the resistor as 0 pull-none, 1 pull-up, 2 pull-down, while `kernel::hil::gpio::FloatingState` declares `PullUp`, `PullDown`, `PullNone` \u2014 rotated by one, with nothing in either file saying so. The match that translates them reads like boilerplate a cast would tidy away; it would compile, and userspace asking for a pull-up would get pull-none on an input pin, which is exactly where that difference decides what the pin reads. Comment only, no behaviour change."),
        ("What it is checked against", "Both broken `make` targets were run, not read: `flash-app` fails with `No rule to make target` on both boards. `make prepush` is green on a fresh worktree off `73af792ec` \u2014 542 lines of real build output rather than a cached no-op \u2014 and `cargo doc -p capsules-core` builds with no warnings, so the new intra-doc link resolves."),
        ("One interaction worth disclosing", "The corrected README command is `make program`, and on plain master that fails with #4770: `ERROR: ELF contains memory contents for uninitialized memory at 0x20000000`, rc 253. Run and confirmed. This change is still strictly an improvement \u2014 it names a target that exists \u2014 but a reader only gets an application onto the board once `rp2-make-program-fix` lands as well, so the two should reference each other."),
    ],
    "tock:rp2350-gpio-irq": [
        ("What it fixes", "`IO_IRQ_BANK0` is defined in the RP2350's `interrupts.rs` and referenced nowhere else in the crate, so `service_interrupt` returns false for it and the chip panics with \"unhandled interrupt 21\". The handler it should reach, `RPPins::handle_interrupt`, already exists; the RP2040 routes the same interrupt to the same place in the same three lines."),
        ("Why it is worth reading first", "An application can bring the kernel down with a legal syscall. The upstream `raspberry_pi_pico_2` board exposes the GPIO driver to userspace, so any process calling command 7 — enable interrupts — on any pin panics the board. That is a well-behaved process taking the system down rather than a misbehaving one being contained."),
        ("Evidence, before and after", "Reproduced and fixed on hardware, on the upstream `raspberry_pi_pico_2` rather than a derived board, with two buttons on GPIO 14 and 15. The same application on the same pins panics before the change and works after it — printing every press and release, with the kernel still answering the process console throughout. The panic names the syscall that caused it: driver 4, subdriver 7, arg0 14. And the application reads both resting levels successfully through that same driver first, so it cannot be dismissed as a malformed request."),
    ],
    "tock:rp2-adc": [
        ("What it adds", "The RP2350 has no ADC driver at all — nor I2C nor PWM; the port is thinner than the RP2040's across the board. This moves the SAR ADC into the crate the two chips share and adds the RP2350's half: base address, channel set, and the interrupt routing."),
        ("Why the shape is safe", "It is the shape that already merged. #5112 moved the PL022 SPI into `rp2xxx` and added the RP2350's the same way, in the same crate, with the same argument. No new driver number, no new API surface, no question about whether the feature is wanted."),
        ("What actually differs between the chips", "Register offsets are identical. The base moves to 0x400a0000, CS.AINSEL is four bits rather than three and CS.RROBIN nine rather than five, and the channel count depends on the package — QFN-60 bonds four inputs with the temperature sensor on channel 4, QFN-80 bonds eight with it on channel 8. The channel set is a trait the chip crate implements, so the package question is answered where it belongs."),
        ("Two things changed rather than moved", "The driver used to decide the temperature sensor's channel with `if *channel as u32 == 4`, a literal that is right for the RP2040 and a QFN-60 RP2350 and wrong for a QFN-80 one. And a field written on every sample and never read anywhere has gone."),
        ("Sizes", "Not identical, and could not be: moving code across a crate boundary changes the partition the optimiser starts from. .text on the three RP2040 boards that build it goes 95392 to 95244, 98616 to 98696, and 91664 to 91588. Behaviour unchanged — same registers, same write order, same interrupt handling."),
        ("The board half, and why it is in the same branch", "A chip driver with no consumer invites the question of what it is for, so the third commit wires it on the upstream `raspberry_pi_pico_2`: mux, four channels, syscall driver. GPIO26-28 reach the header as ADC0-ADC2 and GPIO29 measures VSYS through a divider. Those four leave the GPIO syscall list, commented out exactly as `nano_rp2040_connect` already does it, because a pin cannot usefully be both — an application driving GPIO26 as an output while another samples channel 0 is a short through the pad driver, and neither driver can see the other to refuse."),
        ("A pad trap the chip driver cannot fix", "Out of reset an RP2350 pad has its isolation latch set and its pull-down enabled. The pull-down is the one that bites: across an analogue source it is the lower leg of a divider, so readings stay plausible while never reaching either rail — the failure that gets diagnosed as a bad sensor. The pad belongs to GPIO, not to the converter, so the board configures it: `set_function(NULL)` clears the isolation latch, `PullNone` removes the pull, `deactivate_pads` switches the digital input buffer off. The same three steps `adc_gpio_init` takes in the C SDK. `nano_rp2040_connect` does none of them today."),
        ("Read on silicon, and the pad sequence is measured rather than argued", "A joystick on a Pico 2 W reads 0 to 65408 on one axis and 0 to 65520 on the other, out of 65535 — both rails, both axes. That is the check that matters for the pad configuration, because an analogue pad left with its reset pull-down is the lower leg of a divider and yields a plausible range that never reaches either rail. “The pads are configured” and “the range reaches the rails” are different claims and only the second is checkable. Left-justification is confirmed in the same run: every raw reading is a multiple of sixteen."),
        ("What that covers, and what it does not", "The chip driver, the ADC FIFO interrupt routing and the three-step pad sequence are exercised on silicon. The `raspberry_pi_pico_2` board file in this branch is not — the measurement is on a Pico 2 W, whose board file is #5141 and not upstream, and there is no plain Pico 2 here to run it on. The two boards share the chip half and differ only in which channels they expose. Builds, fmt and clippy clean, and .text on raspberry_pi_pico_2 goes 65092 to 66708 by `size -A`, so the driver is demonstrably in the binary rather than optimised out."),
    ],
    "tock:rp2-uart-abort-fix": [
        ("What it fixes", "Three defects in one path. An aborted UART receive completes by calling the client back before the driver returns to Idle, so the mux's restart from inside that callback is refused and the mux ends every client's receive. Separately, a failed `start_receive` handed the caller the mux's buffer instead of its own, and the teardown dropped the buffer of any device that was not in the Receiving state."),
        ("Who is affected", "Eleven boards pair a process console with the userspace console capsule on one mux, over the three chip drivers that share the block character for character: rp2040, rp2350 and sifive. On those boards an application's first console read is accepted and then killed, and the process console stops receiving at the same moment."),
        ("How it was demonstrated", "Twice. On a Pico 2 W with an instrumented kernel, and under QEMU on hifive1 with no hardware at all. The QEMU reproduction is `examples/console_read_busy.rs` in libtock-rs and runs against the tock revision libtock-rs already pins."),
        ("How the fix was verified", "A/B on one kernel revision with one unmodified application. Without the patch: `read -> 0 bytes, Err(BUSY)` immediately. With it: the read stays outstanding. With it, and sixteen bytes typed: `read -> 16 bytes, Ok(())`. The third case is the one that matters, because it shows the behaviour restored rather than the error suppressed. The process console kept receiving throughout."),
        ("Cost", "None. Verified section by section rather than from the summary line: `.text` unchanged at 65100 on hifive1, 95388 on raspberry_pi_pico and 91660 on nano_rp2040_connect, with `.storage` unchanged on all three. `cargo fmt --check` and clippy clean. Each of the three commits builds standalone."),
        ("Caveat: the transmit path", "The same ordering bug exists on the transmit side of all three drivers and is fixed in the same commit, by symmetry and by the same mechanism — the mux restarts transmits from inside the callback too. It is argued, not demonstrated; there is no failing case for it."),
        ("Caveat: where it was verified", "The A/B ran at the revision libtock-rs pins, not at current master, because the reproduction application does not load on a master kernel. The patch applies cleanly at both; only the sifive and mux halves exist at the older revision, since chips/rp2350 postdates it."),
    ],
    "tock:stepper-capsule": [
        ("What it is", "A syscall driver for a four-phase unipolar stepper, of the kind a 28BYJ-48 with a ULN2003 board presents. An application asks for a number of steps at an interval; the capsule advances the phase sequence from its own alarm. Driver number 0x00011, `capsules/extra`, with documentation in `doc/syscalls`."),
        ("Why it is a capsule rather than an application", "Nothing releases a GPIO pin when the process that set it dies, and the GPIO driver is documented as exporting \"hardware-like\" control, so it correctly has no ownership to unwind. A motor driven straight through it keeps a coil energised for the life of the board if its process faults mid-step. That policy is device knowledge, so it belongs where it can be enforced. Because a stepper already needs an alarm to step, the liveness check costs nothing extra — the owner's grant is entered before every step, and a process that is gone means de-energise and stop, worst case one step interval."),
        ("Novelty a reviewer will notice", "No other capsule in the tree pairs an alarm callback with a liveness check. adc.rs's twenty-two checks are all on peripheral callbacks or command entry. This is an extension of that idiom to a timer, not an instance of it, and should be introduced as such."),
        ("What review changed", "Four things, all found from the calling side. A stop delivered no upcall, so a caller could never learn how far a stopped movement got — and for an open-loop motor that count is the position. A non-owner stop silently succeeded, which is the wrong answer for the one command whose purpose is making something stop; it now returns RESERVE, for the hung-owner case rather than the dead-owner one the liveness check already covers. A doc comment still denied the upcall behaviour after the code had changed. And a stop now returns the count as well as upcalling it."),
        ("Why a stop reports the count twice", "Because the two reach different callers and only one is guaranteed to exist. The upcall is the run's completion and has to stay, or an asynchronous caller waiting on it never wakes. But whoever calls stop need not hold that subscription, and an asynchronous one may have dropped the machinery the upcall arrives through: the natural spelling of \"one revolution, or until a button\" is a select, and a select drops its loser — taking the subscription, and the position, with it. The synchronous return makes the position reachable without depending on how the caller arranged its waiting. It is an ABI change: a libtock-rs client reading `to_result::<(), ErrorCode>()` now gets BADRVAL, because the kernel answers SuccessU32. Made now, while the driver number is provisional and neither half has been proposed, which is what makes it free."),
        ("It turns a real motor", "A 28BYJ-48 on a ULN2003 board, wired to GPIO 18-21, spins. First attempt, no retries. The whole path is exercised: an application asks for a movement, the capsule owns the windings and runs the sequence off its own alarm, and the shaft turns."),
        ("Verified on silicon", "The safety property is demonstrated rather than argued. Reading the GPIO output register over the debug port shows windings energised mid-run, then `terminate` on the process console, then all four clear — with the kernel still answering afterwards, so that \"stopped\" is not \"dead kernel\". Two separate runs caught two different rows of the half-step table energised, `[false,false,true,true]` and `[false,false,false,true]`, which are adjacent entries: a scrambled table would have to be wrong in a way that lands on two consecutive correct rows."),
        ("The idle state is observed too", "At rest, before anything steps: the output-enable register has bits 18 to 21 set and the output register has them clear — the windings are configured as outputs and driven low. That is the capsule's constructor doing it, which was added so a board that forgot to configure the pins would not fail silently, and it is now evidenced rather than assumed. The radio's power and chip-select pins appear in the same read with their expected values, which is the control against a read that returns zeros."),
        ("Driven low, not released", "After the owner is terminated the output-enable bits stay set while the output bits go clear, and stay clear ten seconds later. The windings are actively held low rather than let float, which is the distinction that matters: a floating pin says nothing about what the driver board sees on its inputs. This is de-energisation, not the absence of a claim."),
        ("A caveat for anyone reproducing this", "Do not test it by turning the shaft. A 28BYJ-48 has a 64:1 gearbox and its output shaft will not back-drive by hand whether the windings are energised or not, so resistance does not distinguish the two states and reads as a failure when everything is working. Temperature does distinguish them, and a motor that has been stepping and then stopped is cold to the touch within seconds."),
        ("What is still inference", "That the coils go cold **within one step interval**. The measurement landed a second or two after the kill, because bringing up the debugger takes that long. The bound follows from the liveness check being the first thing in the alarm handler, before the phase advances, but it has not been timed."),
    ],
    "libtock-rs:stepper": [
        ("What it is", "`libtock_stepper` — exists, step_forward, step_reverse, stop — wired into the umbrella crate, plus an example turning one revolution each way. The interval is a newtype in microseconds so a caller cannot silently pass milliseconds."),
        ("Gate", "Full gate green, seven tests under both cargo test and miri. The fake lives in the crate's own tests rather than in libtock_unittest, since there is no upstream capsule to model yet."),
        ("A limitation worth knowing", "From the blocking API the owner cannot reach `stop`: `step_forward` blocks in a yield loop for the whole run, so the only process allowed to stop the motor is inside a call that will not return until it finishes. Stop is reachable from an upcall handler or from the async version. That is an argument for the async stepper rather than a defect in either half."),
        ("Verified on silicon", "Drove the capsule on a Pico 2 W: 4096 steps forward, 4096 reverse, first flash, turning a real 28BYJ-48."),
    ],
    "libtock-rs:unittest-fakes": [
        ("What it fixes", "Two gaps in libtock-rs's test fakes. `fake::Alarm` did not model expiration, so a test could not assert that cancelling an armed alarm actually stopped it; `fake::Console` did not model an outstanding receive. Command 3 was genuinely unimplemented in both, which is a fidelity bug in the fakes independent of anything built on them."),
        ("Why it is first", "The smallest and least arguable thing in the queue, and it blocks the async series: those tests call `fake::Alarm::new_deferred` and `fake::Console::new_deferred` in three places, and these commits are what add those constructors."),
        ("Gate", "Full gate green at f85f019: examples built for thumbv7em and riscv32imc, the workspace test run, fmt, three clippy passes including riscv32imac, and workspace-wide miri under strict provenance. 101 cargo tests and 90 under miri in libtock_unittest alone."),
        ("Provenance", "Extracted from the async branch rather than cherry-picked: the originals also touched the async crate's own tests, and those stayed behind. Four files, all under `unittest/`, nothing outside it. Builds and tests standalone on master — 95 unit tests and 2 doc tests pass."),
        ("How the fakes were validated, in three parts", "The alarm fake models command 3 clearing the deadline, which is what was measured on a Pico 2 W: an armed five-second sleep dropped, then a 500 ms sleep timing 500261 ticks — discriminating a working stop from both a leaked upcall, which would return instantly, and a timer left armed, which would take five million. The console fake answering success to an abort either way matches the capsule source and an instrumented kernel trace. The console fake's model of a receive that stays outstanding is unvalidated, and stays that way until the UART defect is fixed, because no environment currently holds a console read open."),
    ],
    "libtock-rs:platform-pico2": [
        ("What it adds", "A build platform row for the Raspberry Pi Pico 2, and a build error that previously named neither the platform nor the file to edit — registering a platform takes three files that do not know about each other, and missing the third failed with \"Failed to determine ELF's architecture\"."),
        ("Where the addresses came from", "Read off a linked kernel with nm rather than off the linker script, because the application region is what the kernel leaves rather than what the board reserves. Re-checked against a kernel built from current master: _sapps 0x10040000, _eapps 0x10080000, _eappmem 0x20082000, so the row's flash 0x10040000 + 256K and RAM 0x20020000 + 392K both land exactly. Applications built through this row load, run and print on real hardware."),
        ("Gate", "Full gate green at ce33db6, the same suite: cross-target example builds, workspace tests, fmt, clippy including riscv32imac, and miri under strict provenance."),
        ("Why the Pico 2 W row is not here", "It names a board that is not upstream. Only boards/raspberry_pi_pico_2 exists at master; the W board is #5141 and still open. That row waits for its board rather than asking a reviewer to accept a platform entry they cannot resolve."),
    ],
    "libtock-rs:async/alarm": [
        ("What it adds", "A Future and executor layer over Tock's syscalls: futures for the alarm and console drivers, a single-task executor with `block_on`, `join` and `select`, and unittest fakes that model alarm expiration and an outstanding console receive."),
        ("How it was verified", "`make test` green. On a Pico 2 W running the Pico 2 W kernel, every 500 ms await lands within a few hundred microseconds of its deadline, including the two immediately after a cancelled five-second sleep — 500250 and 500249 ticks. That discriminates working cancellation from both a leaked upcall, which would return instantly, and a timer left armed, which would take five million."),
        ("It is not one pull request", "Intended as two, and it is not two branches yet: the two unittest commits sit inside this one and have to be lifted out first. The order is forced rather than preferred — the async tests call `fake::Alarm::new_deferred` and `fake::Console::new_deferred` in three places and those constructors are what the unittest commits add."),
        ("Known gap", "The console half of concurrency is untested, and cannot be tested until the UART defect above is fixed. The failure is in the kernel, not in the futures."),
    ],
    "libtock-rs:pico2-platform": [
        ("What it adds", "Build platform entries for the Raspberry Pi Pico 2 and Pico 2 W, and a build error that named neither the platform nor the file to edit."),
        ("Where the addresses came from", "Read off a linked kernel with nm rather than off the linker script, because the application region is what the kernel leaves rather than what the board reserves. For the Pico 2 W: _sapps 0x10090000, _eapps 0x100d0000, _sappmem 0x20005c04, _eappmem 0x20082000. The RAM row starts at 0x20020000 and +392K lands exactly on _eappmem."),
        ("Verified", "Applications built through these rows load, run and print on a Pico 2 W. Both boards' numbers were reproduced independently in two sessions against separately built kernels that came out to identical text and bss."),
        ("It should be split before it goes", "Two of its three commits are ready: the Pico 2 row and the error-message fix. The third adds a `raspberry_pi_pico_2_w` row, and that board is not upstream yet — it is an open pull request in the kernel repository. A reviewer meeting a platform entry for a board they cannot find would be right to ask, and the answer is another repository's unmerged work. Send the Pico 2 row now; the W row follows the board."),
    ],
    "book:pico2-getting-started": [
        ("What it adds", "A getting-started page for the Raspberry Pi Pico 2. The book currently has no Pico coverage at all."),
        ("Verified", "The documented route was walked end to end on real hardware, and five things that were wrong got fixed in the process."),
        ("Caveat to disclose", "The BOOTSEL flashing route is unverified on macOS, because the board is never connected to the development machine here. The page tells the reader to check where the volume mounted before naming it, so the literal path is illustrative rather than load-bearing, and the bootrom behaviour underneath is documented and host-independent."),
    ],
}

# Real dependencies the API cannot see, because they cross pull requests.
# Hardware blocks, keyed by the name the reset controller gives them with any
# instance number stripped. The list itself is NOT written here -- it is read
# from `chips/*/src/resets.rs`, one bit per resettable block, so the chip's own
# source says how many blocks it has and which chip has which. This table only
# says what each one is for, and which driver module covers it.
#
# A block the reset controller names with no entry here fails `blocks` in
# check.py, so a chip crate gaining a peripheral cannot pass silently.
BLOCKS = {
    "ADC": ("Analogue", "Analogue in", "adc",
            "Turns a voltage on a pin into a number. The joystick, the potentiometer and the on-chip temperature sensor all arrive through it."),
    "BUSCTRL": ("Moving data", "Bus arbiter", None,
                "Decides who wins when both cores and the DMA want the same bus in the same cycle."),
    "DMA": ("Moving data", "Direct memory access", "dma",
            "Moves bytes between memory and a peripheral without the processor being involved. The radio's firmware goes up this way."),
    "HSTX": ("Buses", "High-speed transmit", None,
             "A parallel-to-serial output built for driving displays."),
    "I2C": ("Buses", "I2C bus", "i2c",
            "Two wires, many sensors, each with an address."),
    "IO_BANK0": ("Pins", "Pin function select", "gpio",
                 "Which peripheral each pin is wired to. Set it wrong and a write to the pin goes nowhere, silently."),
    "IO_QSPI": ("Pins", "Flash pin select", None,
                "The same function select, for the six pins that talk to the flash chip."),
    "JTAG": ("Chip services", "Debug port", None,
             "Where the debug probe attaches."),
    "PADS_BANK0": ("Pins", "Pin pad controls", "pads",
                   "The analogue half of a pin: drive strength, pull-up, pull-down, input enable, schmitt trigger."),
    "PADS_QSPI": ("Pins", "Flash pad controls", None,
                  "The same pad controls, for the flash pins."),
    "PIO": ("Buses", "Programmable IO", "pio",
            "Small state machines running an instruction set of their own, so the chip can speak a bus it has no hardware for. On a Pico 2 W they clock the radio."),
    "PLL_SYS": ("Clocks", "System PLL", "clocks",
                "Multiplies the crystal up to the speed the processor runs at."),
    "PLL_USB": ("Clocks", "USB PLL", "clocks",
                "The second multiplier, for the 48 MHz USB needs."),
    "PWM": ("Analogue", "Pulse width modulation", "pwm",
            "A square wave with an adjustable duty cycle: motor speed, servo angle, LED brightness."),
    "RTC": ("Time", "Real-time clock", "rtc",
            "Wall-clock date and time, kept running across sleep."),
    "SHA256": ("Chip services", "Hash accelerator", None,
               "SHA-256 in hardware, for verifying a boot image."),
    "SPI": ("Buses", "SPI bus", "spi",
            "Four wires, one clock, a chip-select per device. The breadboard kit's display is on it."),
    "SYSCFG": ("Chip services", "System config", None,
               "Chip-level odds and ends: processor configuration, which pins the debug interface uses."),
    "SYSINFO": ("Chip services", "Chip identity", "sysinfo",
                "Chip id, revision and manufacturer, readable at runtime."),
    "TBMAN": ("Chip services", "Testbench manager", None,
              "Reports whether the code is running on real silicon or in simulation."),
    "TIMER": ("Time", "Microsecond timer", "timer",
              "A counter that ticks once a microsecond, with alarms that fire off it. Every sleep in the kernel rests here."),
    "TRNG": ("Chip services", "Random numbers", None,
             "A hardware entropy source."),
    "UART": ("Buses", "Serial port", "uart",
             "The console. The kernel's own output and an application's both arrive over one of these."),
    "USBCTRL": ("Buses", "USB", "usb",
                "Device or host USB, including the bootloader's drive."),
}

# Modules that are not one of the reset controller's blocks. The oscillator,
# the always-on watchdog and the reset controller itself sit outside it, and
# the rest are Tock's own scaffolding rather than hardware.
PLUMBING = {
    "chip": "Ties the peripherals to the interrupt table.",
    "clocks": "Brings the PLLs and the clock tree up at boot.",
    "deferred_calls": "Lets a driver finish work after returning.",
    "interrupts": "Names every interrupt line the chip can raise.",
    "lib": "The crate root.",
    "mod": "A module index.",
    "resets": "Holds each block in reset until it is asked for.",
    "ticks": "The RP2350's tick generator, which feeds the timer.",
    "watchdog": "Resets the chip if the kernel stops feeding it.",
    "xosc": "The crystal oscillator everything else is derived from.",
}

# The 40-pin header, which is the board's form factor rather than anything in
# Tock's source. Physical pin order, 1 to 40; the right-hand column of a real
# board runs 40 down to 21, and the page draws it that way.
#
# Only the shape is written here. Which pins do what is read from the board's
# own source, below.
HEADER = [
    (1, "gpio", "GP0"), (2, "gpio", "GP1"), (3, "gnd", "GND"),
    (4, "gpio", "GP2"), (5, "gpio", "GP3"), (6, "gpio", "GP4"),
    (7, "gpio", "GP5"), (8, "gnd", "GND"), (9, "gpio", "GP6"),
    (10, "gpio", "GP7"), (11, "gpio", "GP8"), (12, "gpio", "GP9"),
    (13, "gnd", "GND"), (14, "gpio", "GP10"), (15, "gpio", "GP11"),
    (16, "gpio", "GP12"), (17, "gpio", "GP13"), (18, "gnd", "GND"),
    (19, "gpio", "GP14"), (20, "gpio", "GP15"),
    (21, "gpio", "GP16"), (22, "gpio", "GP17"), (23, "gnd", "GND"),
    (24, "gpio", "GP18"), (25, "gpio", "GP19"), (26, "gpio", "GP20"),
    (27, "gpio", "GP21"), (28, "gnd", "GND"), (29, "gpio", "GP22"),
    (30, "ctrl", "RUN"), (31, "gpio", "GP26"), (32, "gpio", "GP27"),
    (33, "gnd", "AGND"), (34, "gpio", "GP28"), (35, "ctrl", "ADC_VREF"),
    (36, "power", "3V3(OUT)"), (37, "ctrl", "3V3_EN"), (38, "gnd", "GND"),
    (39, "power", "VSYS"), (40, "power", "VBUS"),
]

# GPIOs the chip has that the header does not carry. On a Pico 2 W these four
# are the radio, which is why an application cannot have them.
OFF_HEADER = [23, 24, 25, 29]

# What an identifier found beside a pin means. Keyed by the name the board's
# own source uses, so an unrecognised one renders raw and `pins` reports it
# rather than the page quietly inventing a role.
PIN_ROLE = {
    "gpio_tx": ("UART0 TX, the console out", "kernel"),
    "gpio_rx": ("UART0 RX, the console in", "kernel"),
    "spi_clk": ("SPI0 SCK, the display's clock", "kernel"),
    "spi_tx": ("SPI0 TX, the display's data", "kernel"),
    "SpiSyscallComponent": ("SPI chip select", "kernel"),
    "Stepper": ("stepper phase", "kernel"),
    "led_kernel_pin": ("on-board LED", "kernel"),
    "LedsComponent": ("on-board LED", "kernel"),
    "cs": ("radio chip select", "radio"),
    "pwr": ("radio power", "radio"),
    "PioGspiComponent": ("radio gSPI, clocked by PIO", "radio"),
    "pad setup": ("analogue pad, prepared for the ADC", "adc"),
}

# Which boards get a pin map, and at which ref.
PIN_BOARDS = [
    ("raspberry_pi_pico_2", "upstream", "Pico 2", "as it is upstream"),
    ("raspberry_pi_pico_2_w", "fork", "Pico 2 W", "the bench kernel"),
]

# Which block a driver module covers. Kept separately from BLOCKS because the
# relation is many-to-one: three PIO-backed bus drivers all cover the PIO
# block. A module in any surveyed crate that appears in neither this table nor
# PLUMBING fails `blocks`.
MODULE_BLOCK = {
    "adc": "ADC", "dma": "DMA", "gpio": "IO_BANK0", "i2c": "I2C",
    "pads": "PADS_BANK0", "pio": "PIO", "pio_gspi": "PIO", "pio_pwm": "PIO",
    "pio_spi": "PIO", "pwm": "PWM", "rtc": "RTC", "spi": "SPI",
    "sysinfo": "SYSINFO", "timer": "TIMER", "uart": "UART", "usb": "USBCTRL",
}

# Where a block is covered but not well. Each names the defect or the branch
# that answers it, and `refs` checks any "#1234" inside one resolves.
BLOCK_CAVEAT = {
    "IO_BANK0": ("Pins work; pin interrupts panic the kernel. IO_IRQ_BANK0 is "
                 "defined on the RP2350 and routed nowhere, so a legal syscall "
                 "brings the board down. Four lines on rp2350-gpio-irq.", "rp2350-gpio-irq"),
    "PIO": ("Five defects, all with fixes proposed in #5157. Four were found "
            "by the driver's first host tests; the fifth came out of a security "
            "pass and is the one demonstrated on silicon \u2014 a block interrupt "
            "flag delivered to the wrong state machine's client, which can hang "
            "the kernel.", 5157),
    "UART": ("An aborted receive tears down every other receive on the same "
             "multiplexer. Three defects, fix written on rp2-uart-abort-fix.",
             "rp2-uart-abort-fix"),
}


EXTRA_DEPS = {
    "chips: rp2040: move the PIO driver into the shared rp2xxx crate": [
        "chips: rp2040: move the PL022 SPI driver into a shared rp2xxx crate",
    ],
    "chips: rp2xxx: share the GPIO pad control enums": [
        "chips: rp2040: move the PL022 SPI driver into a shared rp2xxx crate",
    ],
}

# status -> (pill class, pill label)
DEFECT_PILL = {
    "fixed": ("merged", "fix proposed"),
    "fixed-local": ("approved", "fix written, not sent"),
    "unfiled": ("unfiled", "not filed"),
}

DEFECTS = [
    ("PIO: the RX FIFO join never happened", "fixed", 5150,
     "Joining the FIFOs silently did nothing, so a program relying on the depth dropped words."),
    ("PIO: add_program panicked on half its own range", "fixed", 5150,
     "A valid load address panicked the kernel instead of returning an error."),
    ("PIO: three of four interrupt lines unserviced", "fixed", 5150,
     "Only one state machine's interrupt was ever handled."),
    ("PIO: an interrupt flag scoped to the wrong thing", "fixed", 5150,
     "The flag belongs to the block; treating it as per-state-machine mis-attributes interrupts."),
    ("UART: an aborted receive tears down every other receive", "fixed-local", "rp2-uart-abort-fix",
     "The abort completion calls the client back before marking the receiver idle, so the multiplexer's restart is refused and it ends every device's receive instead. The same code is in three chip drivers, and eleven boards pair a process console with the userspace console on one multiplexer. Reproducible under QEMU with no hardware, on hifive1, at the eighteen-month-old revision libtock-rs already pins — and no application can avoid it. Removing the delay before the read, and then issuing the read before any other system call, both still fail: the process console's prompt prints before the application's first line, so the receive is already armed before the application's first instruction. \u201cThe app read too early\u201d is not an available explanation. What the reproduction still lacks is the opposite control, a kernel with no process console on that multiplexer, which is a board change rather than an application one."),
    ("UART: a failed receive hands back the wrong static buffer", "fixed-local", "rp2-uart-abort-fix",
     "A virtual device propagates the multiplexer's error with `?`, and that error carries the multiplexer's buffer rather than the caller's. Two static buffers change owners and the multiplexer's slot is left empty for the life of the board."),
    ("UART: the teardown drops a buffer it cannot deliver", "fixed-local", "rp2-uart-abort-fix",
     "When a restart fails the mux takes every device's buffer, but only returns it to devices still in the Receiving state — so a device that had aborted a read loses its buffer permanently. Found while fixing the two above."),
    ("A stopped process never gets its GPIO reclaimed", "unfiled", None,
     "The pin stays driven forever. A sibling capsule already has the fix, which makes this a consistency bug. Five of forty-five capsules are affected."),
    ("`make program` cannot flash an app on the Pico 2", "unfiled", None,
     "The objcopy step gives the stack segment a file size it should not have; picotool then refuses the image and leaves a zero-byte UF2 behind."),
]

# Write-ups under findings/. The slug is the directory, so a page and its
# row cannot drift apart -- check.py refuses a row with no page and a page
# with no row. The issue state is fetched rather than written down, because
# an issue drawn as open after it is closed is the page lying.
FINDINGS = [
    (4770, "4770", "make program builds an ELF no UF2 tool will take",
     "Splicing an app into the kernel makes objcopy lay the segments out again, "
     "and the (NOLOAD) stack segment comes back claiming 5,376 bytes of file "
     "content for RAM. The reported cause is not what is happening, and the "
     "workaround in the issue strips a section that is only safe to strip by "
     "accident. Six candidate fixes measured against a kernel built from "
     "upstream; the one that works is a single objcopy line, and it is A/B verified on all four RP2 boards by running their real make targets."),
    (5156, "5156", "a flashing route with no ELF to get wrong",
     "The reviewer who approved the four-line fix for #4770 asked for something "
     "else in the same sentence: that these boards stop splicing an application "
     "into the kernel ELF and use tockloader local-board instead. That route was "
     "run end to end -- a kernel and an application assembled by tockloader, "
     "programmed over SWD, and the process live in the kernel's own process "
     "list. It cannot hit the defect because it never opens an ELF. Four costs "
     "come with it, and the tool swap on three RP2040 boards is the one a "
     "reviewer would stop on."),
    (5157, "5157", "a PIO interrupt flag delivered to the wrong client",
     "A PIO block raises eight IRQ flags that belong to the block, and the "
     "driver delivered flag n to state machine n's client -- an association the "
     "hardware does not have and the datasheet invites by naming those bits "
     "SM0-SM3. A flag whose state machine has no client is never cleared, so "
     "the peripheral keeps asserting and the kernel spins. Invisible in the "
     "tree because the only user sits on the diagonal. Four more defects "
     "alongside it, and the misrouting plus its fix were both run on silicon."),
    (5153, "5153", "EP0 IN is armed at bus reset and never taken back",
     "The RP2040 USB driver hands EP0's IN buffer to the controller during bus "
     "reset, with a length of 64 and a PID of DATA0 and nothing queued to send. "
     "A SETUP packet does not take it back, so the first control read can be "
     "answered out of a buffer nobody filled. Two of the three claims in the "
     "issue's own AI analysis hold up; the third points at a delay already in "
     "the code. Not tested -- there is no RP2040 board here, and rp2350 has no "
     "USB driver to stand in for one."),
]

SILICON = [
    ("Pico 2 W scans WiFi", "Firmware up over PIO and DMA, MAC read from the radio's OTP, scan completed."),
    ("SPI loopback", "A 32-byte pattern written and read back through the RP2350 SPI driver."),
    ("Boot from RAM", "The layout from #5109, booting."),
    ("Two co-resident apps", "Applications load, run and print, which is what makes any userspace claim checkable."),
    ("Async sleep and cancellation", "A 500 ms await lands within a few hundred microseconds of its deadline, including immediately after a cancelled five-second sleep. That distinguishes working cancellation from both a leaked callback and a timer left armed."),
    ("PIO and DMA register readback", "The interrupt block's offset, the state machine count and the instruction memory size, read off the chip."),
]

DOWNSTREAM = [
    ("Async userspace", "blocked",
     "A Future and executor layer over Tock's syscalls in libtock-rs, validated on a Pico 2 W running the Pico 2 W kernel. The alarm half is done and measured. The console half is blocked on the UART defect being fixed, and that question is now closed rather than open: QEMU was the last candidate for an environment where a userspace console read stays outstanding, and it reproduces the defect too."),
    ("A Pico page for the Tock book", "ready",
     "The book has no Pico coverage at all. Written and pushed; the pull request is not open yet."),
    ("Nine chapters on how the kernel works", "drafted",
     "From what a register is through grants and the memory protection unit, written while learning the codebase."),
]

NOT_DONE = [
    ("Give the QEMU reproduction a home someone can reach",
     "`examples/console_read_busy.rs` currently exists only on a branch marked never-for-upstream, which is the wrong address for the one artefact here that a maintainer is meant to run themselves. It travels with the defect report, or goes up on its own as a libtock-rs example, but it cannot stay where it is."),
    ("Extract the unittest fixes onto their own branch",
     "Two commits currently inside the async branch, and the smaller of the two asks. Roughly half an hour of cherry-picking and a gate run."),
    ("File the four unfiled defects", "Each is demonstrated and none is filed. The constraint is review throughput, not the work."),
    ("Fix the reclaim leak", "The sibling capsule already shows what the fix looks like."),
    ("A userspace driver for PIO", "The RP2's most distinctive peripheral, and no process can reach it."),
    ("Hardware CI for the RP2 boards", "The project's testbed runs one board and never on pull requests. Named as a dependency in #5152 rather than promised."),
]


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def gh_json(args):
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True,
                             check=True).stdout
    except FileNotFoundError:
        sys.exit("error: the gh CLI is not installed")
    except subprocess.CalledProcessError as err:
        sys.exit(f"error: gh failed: {err.stderr.strip()}")
    return json.loads(out)


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def remote_heads(path):
    """Every branch tip the repo's remotes actually hold, asked of the remotes.

    Deliberately not `origin/<branch>`, which this function replaced because that
    ref is wrong in both directions here:

      it names the WRONG REMOTE.  In ~/forge/book, `origin` is the upstream
      tock/book and the fork is the remote named `fork`. A branch pushed to the
      fork had no `origin/` ref and read as local-only — a false alarm, visible.

      it is a LOCAL CACHE.  `origin/<branch>` keeps existing after the branch
      moves on locally, so a branch pushed once and committed to since read as
      backed. That is a false green, and it is the one that matters: the page
      said work was safe while it existed on one disk.

    Existence is not the question either; the tip is. A branch three commits
    ahead of what the remote holds is not "pushed", however true it is that a
    ref by that name is up there.

    Fails toward the alarm: if a remote cannot be reached, it contributes no
    tips and its branches read as unpushed rather than as backed.
    """
    tips = {}
    for remote in (git(path, "remote") or "").splitlines():
        ls = git(path, "ls-remote", "--heads", remote)
        if ls is None:
            continue
        for line in ls.splitlines():
            sha, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                tips.setdefault(ref[len("refs/heads/"):], set()).add(sha)
    return tips


def survey_local():
    """Branches in each local clone, how far ahead they are, and their commits."""
    out = {}
    for name, (path, base) in LOCAL.items():
        if not path.exists():
            continue
        refs = git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        if refs is None:
            continue
        tips = remote_heads(path)
        branches = {}
        for branch in refs.splitlines():
            log = git(path, "log", "--format=%s", f"{base}..{branch}")
            if log is None:
                continue
            commits = [l for l in log.splitlines() if l]
            stat = git(path, "diff", "--shortstat", f"{base}...{branch}") or ""
            head = git(path, "rev-parse", branch) or ""
            held = tips.get(branch, set())
            # A remote tip is only usable as a --not argument if this clone has
            # the object; a remote that is AHEAD of us names commits we lack.
            known = [sha for sha in held
                     if git(path, "cat-file", "-e", sha + "^{commit}") is not None]
            if head and head in held:
                pushed, unpushed = True, 0
            elif known:
                # Count what no remote can reach, then decide. Asking instead
                # whether a remote holds our exact tip answers a different
                # question from the one the pill renders: a branch BEHIND its
                # remote has all its work backed up and no tip match, and read
                # as "0 commits not pushed" -- a false alarm whose text is also
                # nonsense. The question is "is any of this only on this disk".
                unpushed = int(git(path, "rev-list", "--count", branch,
                                   "--not", *known) or 0)
                pushed = unpushed == 0
            else:
                # On no remote at all, or on a remote this clone cannot follow:
                # everything since the base is unbacked as far as we can tell.
                pushed, unpushed = False, len(commits)
            branches[branch] = {
                "ahead": len(commits),
                "commits": commits,
                "stat": stat.strip(),
                "base": base,
                # The MERGE-BASE, not the tip of `base`. Rendered as "Cut from
                # <base> at <sha>", which is a claim about where this branch
                # actually diverged -- and `rev-parse base` answered a different
                # question, so the page asserted every branch was cut from the
                # current upstream tip. That was false for eight of ten, by up
                # to 40 commits.
                "base_sha": ((git(path, "merge-base", branch, base) or "")[:9]),
                "behind": int(git(path, "rev-list", "--count",
                                  f"{branch}..{base}") or 0),
                "pushed": pushed,
                "on_remote": bool(held),
                "unpushed": unpushed,
            }
        out[name] = branches
    return out


# --------------------------------------------------------------------------
# The chip survey: what Tock can actually drive on an RP2350, read from the
# tree rather than written down.
#
# Every number in the coverage section comes from here. The denominator is the
# reset controller's own bitfield -- `chips/rp2350/src/resets.rs` names one bit
# per resettable hardware block, so "how many blocks does this chip have" is a
# question Tock's source already answers. The numerator is which of those
# blocks has a driver module. Both move on their own when the tree moves.
# --------------------------------------------------------------------------

CHIP_CRATES = ("rp2040", "rp2350", "rp2xxx")
CHIP_BOARDS = ("raspberry_pi_pico", "raspberry_pi_pico_2",
               "raspberry_pi_pico_2_w", "raspberry_pi_pico_w")
UPSTREAM_REF = "upstream/master"
FORK_REF = "bench/stepper-pico2w"          # the bench kernel: everything, merged

_RESET_BIT = re.compile(r"^\s+([A-Za-z0-9_]+) OFFSET\((\d+)\)", re.M)
_ARM = re.compile(r"((?:capsules_\w+|kernel)(?:::\w+)+)::DRIVER_NUM\s*=>")
_BASE_PLATFORM = re.compile(r"base:\s*(\w+)::Platform")
_WITH_DRIVER = re.compile(r"fn with_driver.*?\n    \}", re.S)
_STATIC_REF = re.compile(r"StaticRef::new\((0x[0-9A-Fa-f_]+)")
_REG_STRUCT = re.compile(r"register_structs!\s*\{(.*?)\n\}", re.S)
_REG_NAME = re.compile(r"pub\s+(\w+)\s*\{")
_REG_FIELD = re.compile(r"\((0x[0-9A-Fa-f]+)\s*=>\s*(\w+)")
# The bitfield block a register is typed with: `cs: ReadWrite<u32, CS::Register>`.
_REG_TYPE = re.compile(r"\((0x[0-9A-Fa-f]+)\s*=>\s*(\w+):\s*\w+<u(\d+)(?:,\s*(\w+)::Register)?>")
_BITFIELD_HEAD = re.compile(r"\s*(?://[^\n]*\n\s*)*([A-Z][A-Z0-9_]*)\s*\[")
_BITFIELD_FIELD = re.compile(r"([A-Z][A-Z0-9_]*)\s+OFFSET\((\d+)\)\s+NUMBITS\((\d+)\)")
_BITFIELD_SEP = re.compile(r"\s*,")


def _bitfields(src):
    """The named fields inside each register, from `register_bitfields!`.

    Bracket-matched rather than regexed as a whole, because a field may carry
    its own `[ VARIANT = 0 ]` list and a non-greedy match to the first `]`
    stops inside the first field it meets.
    """
    out = {}
    start = re.search(r"register_bitfields!\s*\[\s*u(\d+)\s*,", src)
    if not start:
        return out, 32
    width, i = int(start.group(1)), start.end()
    while True:
        head = _BITFIELD_HEAD.match(src, i)
        if not head:
            break
        depth, j = 1, head.end()
        while j < len(src) and depth:
            depth += 1 if src[j] == "[" else -1 if src[j] == "]" else 0
            j += 1
        out[head.group(1)] = [[f, int(o), int(n)] for f, o, n
                              in _BITFIELD_FIELD.findall(src[head.end():j - 1])]
        i = j
        sep = _BITFIELD_SEP.match(src, i)
        if not sep:
            break
        i = sep.end()
    return out, width
_HIL_PATH = re.compile(r"hil::([a-z_0-9]+)::([A-Z]\w+)")
_HIL_MOD = re.compile(r"hil::([a-z_0-9]+)")
_HIL_USE = re.compile(r"use\s+kernel::hil::([a-z_0-9]+)::(?:\{([^}]*)\}|(\w+))")
_IMPL_QUALIFIED = re.compile(r"impl(?:<[^>]*>)?\s+(?:kernel::)?hil::([a-z_0-9]+)::(\w+)")
_IMPL_SHORT = re.compile(r"impl(?:<[^>]*>)?\s+(?:([a-z_0-9]+)::)?(\w+)(?:<[^>]*>)?\s+for\s")


def _implements(src):
    """The HIL traits a chip driver actually implements.

    Naming a HIL module is not the same as implementing one. `pio.rs` imports
    `hil::gpio` to configure the pins its state machines drive, and joining on
    names put the GPIO and LED capsules above the PIO block -- a page claiming
    a system call reaches PIO, on the same page that lists a userspace PIO
    driver as not done. Only an `impl ... for` counts, whether the trait is
    written out in full or imported and used short.
    """
    trait_mod = {}
    for mod, braced, single in _HIL_USE.findall(src):
        for trait in ([t.strip() for t in braced.split(",")] if braced else [single]):
            trait = trait.split(" as ")[0].strip()
            if trait:
                trait_mod[trait] = mod
    found = {"%s::%s" % (mod, trait) for mod, trait in _IMPL_QUALIFIED.findall(src)}
    for qualifier, trait in _IMPL_SHORT.findall(src):
        mod = trait_mod.get(trait)
        if mod and qualifier in ("", mod):
            found.add("%s::%s" % (mod, trait))
    return sorted(found)
_NUM_ARM = re.compile(r"^\s+(\w+)\s*=\s*(0x[0-9A-Fa-f]+),?\s*$", re.M)


def _show(repo, ref, path):
    return git(repo, "show", f"{ref}:{path}")


def _tree(repo, ref, *paths):
    out = git(repo, "ls-tree", "--name-only", "-r", ref, *paths)
    return [l for l in (out or "").splitlines() if l.endswith(".rs")]


def _modules(repo, ref):
    """{crate: {module: line count}} for the three RP2 chip crates at a ref."""
    out = {}
    for crate in CHIP_CRATES:
        mods = {}
        for path in _tree(repo, ref, f"chips/{crate}/src/"):
            src = _show(repo, ref, path)
            if src is None:
                continue
            mods[path.rsplit("/", 1)[-1][:-3]] = len(src.splitlines())
        out[crate] = mods
    return out


def _reset_bits(repo, ref, crate):
    """The hardware blocks a chip has, from its reset controller's bitfield.

    One bit per resettable block, so this is the chip's own list rather than
    one kept here. Names are upper-cased because the two crates disagree on
    case for the same peripherals.
    """
    src = _show(repo, ref, f"chips/{crate}/src/resets.rs")
    if src is None:
        return {}
    body = re.search(r"\n\s*RESET \[(.*?)\n\s*\]", src, re.S)
    if not body:
        return {}
    return {name.upper(): int(off) for name, off in _RESET_BIT.findall(body.group(1))}


def _board_drivers(repo, ref, board, seen=None):
    """Every syscall driver a process on this board can reach.

    Follows delegation. `raspberry_pi_pico/src/main.rs` answers four driver
    numbers and passes everything else to `self.base.with_driver`, where the
    base is a *different* board crate -- so reading main.rs alone reports one
    driver on a board that exposes ten. Both hops are followed, and a board
    seen twice terminates rather than recursing.
    """
    seen = set() if seen is None else seen
    if board in seen:
        return set()
    seen.add(board)
    found, bases = set(), set()
    for path in _tree(repo, ref, f"boards/{board}/src/"):
        src = _show(repo, ref, path)
        if src is None:
            continue
        for match in _WITH_DRIVER.finditer(src):
            found |= set(_ARM.findall(match.group(0)))
        bases |= set(_BASE_PLATFORM.findall(src))
    for base in bases:
        found |= _board_drivers(repo, ref, base, seen)
    return found


_PIN = re.compile(r"RPGpio::GPIO(\d+)")
_HELPER = re.compile(r"^\s*(//\s*)?(\d+)\s*=>")
_LET = re.compile(r"let\s+(?:mut\s+)?([a-z_][a-z_0-9]*)\s*=")
_CTOR = re.compile(r"([A-Z][A-Za-z0-9]*)::new\s*\(")


def _pin_label(lines, i, line):
    """What this pin is being used for, from the code around it.

    Deliberately shallow. It reads the userspace GPIO table's own arm number,
    or the name of the binding or the component being built beside the pin,
    and hands that to a table that says what such a name means. Anything it
    cannot name renders raw rather than being guessed at.
    """
    helper = _HELPER.match(line)
    if helper:
        return "userspace gpio %s" % helper.group(2), bool(helper.group(1))
    commented = line.lstrip().startswith("//")
    here = _LET.search(line)
    if here:
        return here.group(1), commented
    for back in range(1, 9):
        if i - back < 0:
            break
        prev = lines[i - back]
        ctor = _CTOR.search(prev)
        if ctor:
            return ctor.group(1), commented
        binding = _LET.search(prev)
        if binding:
            return binding.group(1), commented
        if "for pin in" in prev or "for pin in" in line:
            return "pad setup", commented
    return line.strip()[:40], commented


def _board_pins(repo, ref, board, seen=None, shared_only=False):
    """Every pin the board's source names, and what it names it for.

    Recursion into a base board reads its `lib.rs` and not its `main.rs`. The
    distinction is the whole correctness of this: `raspberry_pi_pico_2/lib.rs`
    is shared platform setup that every board built on it runs, but
    `raspberry_pi_pico_2/main.rs` is a *different binary* with its own
    userspace GPIO table. Reading both put the standalone Pico 2's pin
    assignments on the Pico 2 W, which passes its own table into the shared
    setup and shares none of them.
    """
    seen = set() if seen is None else seen
    if board in seen:
        return {}
    seen.add(board)
    found, bases = {}, set()
    for path in _tree(repo, ref, f"boards/{board}/src/"):
        if shared_only and not path.endswith("/lib.rs"):
            continue
        src = _show(repo, ref, path)
        if src is None:
            continue
        bases |= set(_BASE_PLATFORM.findall(src))
        lines = src.splitlines()
        for i, line in enumerate(lines):
            for pin in _PIN.findall(line):
                label, commented = _pin_label(lines, i, line)
                entry = {"label": label, "off": commented,
                         "file": path.rsplit("/", 1)[-1]}
                bucket = found.setdefault(int(pin), [])
                if entry not in bucket:
                    bucket.append(entry)
    for base in bases:
        for pin, entries in _board_pins(repo, ref, base, seen, shared_only=True).items():
            for entry in entries:
                if entry not in found.setdefault(pin, []):
                    found[pin].append(entry)
    return found

def _driver_nums(repo, ref):
    """Capsule name -> syscall driver number, from the one enum that assigns them."""
    src = _show(repo, ref, "capsules/core/src/driver.rs")
    if src is None:
        return {}
    return {name: num for name, num in _NUM_ARM.findall(src)}


def _capsule_info(repo, ref, capsule):
    """The middle rungs: which enum entry a capsule takes its driver number
    from, and which HIL modules it names. Both read out of the capsule itself,
    so `spi_controller` resolving to `Spi` is derived rather than guessed at
    from the name."""
    if capsule == "kernel::ipc":
        return {"path": "kernel/src/ipc.rs", "num_name": "Ipc", "hil": []}
    crate, _, name = capsule.rpartition("::")
    folder = {"capsules_core": "core", "capsules_extra": "extra"}.get(crate)
    if folder is None:
        return None
    # A capsule is either a file or a directory with a mod.rs. The wifi capsule
    # is the second kind, so looking only for `wifi.rs` left the one driver the
    # Pico 2 W exists for with no number beside it.
    for candidate in (f"capsules/{folder}/src/{name}.rs",
                      f"capsules/{folder}/src/{name}/mod.rs"):
        src = _show(repo, ref, candidate)
        if src is not None:
            break
    else:
        return None
    num = re.search(r"DRIVER_NUM[^=]*=\s*[\w:]*?NUM::(\w+)", src)
    return {
        "path": candidate,
        "num_name": num.group(1) if num else "",
        "hil": sorted(set(_HIL_MOD.findall(src))),
    }


def _chain(repo, ref, crate, module):
    """The bottom rungs: the file, the HIL traits it names, its registers, its base."""
    path = f"chips/{crate}/src/{module}.rs"
    src = _show(repo, ref, path)
    if src is None:
        return None
    regs, block, typed = [], "", []
    for body in _REG_STRUCT.findall(src):
        name = _REG_NAME.search(body)
        if name and not block:
            block = name.group(1)
        regs += _REG_FIELD.findall(body)
        typed += _REG_TYPE.findall(body)
    bits, width = _bitfields(src)
    return {
        "bitfields": bits,
        "bitwidth": width,
        "typed": [[off, name, bf] for off, name, _, bf in typed if bf],
        "path": path,
        "lines": len(src.splitlines()),
        "hil": sorted(set(_HIL_MOD.findall(src))),
        "impls": _implements(src),
        "regblock": block,
        "regs": [[off, name] for off, name in regs if name != "@END"],
        "bases": _STATIC_REF.findall(src),
    }


def survey_chip():
    """Read the coverage story out of the Tock clone. Skipped if it is missing."""
    path = LOCAL["tock"][0]
    if not path.exists() or git(path, "rev-parse", "--verify", "-q", UPSTREAM_REF) is None:
        return {"ok": False}

    branches = [b.split(":", 1)[1] for b, (kind, _, _) in INTENT.items()
                if b.startswith("tock:") and kind == "upstream"]
    refs = [UPSTREAM_REF, FORK_REF] + sorted(branches)
    refs = [r for r in refs if git(path, "rev-parse", "--verify", "-q", r) is not None]

    modules = {ref: _modules(path, ref) for ref in refs}
    boards, pins = {}, {}
    for ref in (UPSTREAM_REF, FORK_REF):
        if ref not in refs:
            continue
        boards[ref] = {b: sorted(_board_drivers(path, ref, b))
                       for b in CHIP_BOARDS
                       if _tree(path, ref, f"boards/{b}/src/")}

    # Pins are surveyed only for the boards that get a map. Surveying the
    # others put identifiers on the checked list that nothing on the page
    # would ever render, which is a gate reporting work that does not exist.
    for board, which, _, _ in PIN_BOARDS:
        ref = {"upstream": UPSTREAM_REF, "fork": FORK_REF}[which]
        if ref in boards and board in boards[ref]:
            pins.setdefault(ref, {})[board] = _board_pins(path, ref, board)

    capsules = {}
    for ref, per_board in boards.items():
        for names in per_board.values():
            for capsule in names:
                if capsule not in capsules:
                    info = _capsule_info(path, ref, capsule)
                    if info:
                        capsules[capsule] = info

    fork = FORK_REF if FORK_REF in refs else UPSTREAM_REF
    chains = {}
    for crate in CHIP_CRATES:
        for module in modules[fork][crate]:
            chains.setdefault(module, {})[crate] = _chain(path, fork, crate, module)

    # Which branch first carries a module that upstream does not have. Derived,
    # so a module that moves between branches re-attributes itself.
    up_mods = set(modules[UPSTREAM_REF]["rp2350"]) | set(modules[UPSTREAM_REF]["rp2xxx"])
    added_by = {}
    for branch in sorted(branches):
        if branch not in modules:
            continue
        for crate in CHIP_CRATES:
            if crate == "rp2040":
                continue
            for module in modules[branch][crate]:
                if module not in up_mods:
                    added_by.setdefault(module, branch)

    touched = {}
    for branch in sorted(set(branches) | {FORK_REF}):
        out = git(path, "diff", "--name-only", f"{UPSTREAM_REF}...{branch}")
        if out is not None:
            touched[branch] = sorted(f for f in out.splitlines() if f)

    return {
        "ok": True,
        "upstream_ref": UPSTREAM_REF,
        "fork_ref": fork,
        "head": git(path, "rev-parse", "--short", UPSTREAM_REF) or "",
        "resets": {c: _reset_bits(path, UPSTREAM_REF, c) for c in ("rp2040", "rp2350")},
        "modules": modules,
        "boards": boards,
        "pins": pins,
        "chains": chains,
        "driver_nums": {**_driver_nums(path, UPSTREAM_REF), **_driver_nums(path, fork)},
        "capsules": capsules,
        "added_by": added_by,
        "touched": touched,
    }


def fetch():
    # Commits and files are fetched per pull request: asking for them across a
    # 100-item list exceeds GitHub's GraphQL node budget and the whole query is
    # refused.
    prs = gh_json([
        "pr", "list", "--repo", REPO, "--author", AUTHOR, "--state", "all",
        "--limit", "100", "--json",
        "number,title,state,isDraft,createdAt,mergedAt,closedAt,additions,"
        "deletions,changedFiles,url,reviewDecision,body",
    ])
    for pr in prs:
        # GitHub's own closing-keyword set, and its two other accepted forms:
        # an optional colon, and an explicit same-repo prefix. `\b` matters --
        # without it "prefixes #123" and "affixes #99" both matched "fixes".
        # A reference to another repository is deliberately not accepted: it
        # closes something that is not ours and does not belong in this queue.
        pr["closes"] = sorted({int(n) for n in re.findall(
            r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
            r"(?:tock/tock)?#(\d+)",
            pr.pop("body", "") or "", re.I)})
        detail = gh_json(["pr", "view", str(pr["number"]), "--repo", REPO,
                          "--json", "commits,files"])
        pr["commits"] = [{"messageHeadline": c["messageHeadline"]}
                         for c in detail["commits"]]
        pr["files"] = sorted(f["path"] for f in detail["files"])
    issues = gh_json([
        "issue", "list", "--repo", REPO, "--author", AUTHOR, "--state", "all",
        "--limit", "100", "--json", "number,title,state,createdAt,url",
    ])
    findings = []
    for number, _, _, _ in FINDINGS:
        # Comments come along because the pages quote them: a finding gets
        # confirmed or disputed in the thread, not in the opening post, and a
        # quotation nobody can check is the one that drifts.
        issue = gh_json(["issue", "view", str(number), "--repo", REPO, "--json",
                         "number,title,state,author,createdAt,url,body,comments"])
        issue["comments"] = [{"author": c["author"]["login"], "body": c["body"]}
                             for c in issue.get("comments", [])]
        findings.append(issue)
    return {
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "prs": sorted(prs, key=lambda p: p["number"]),
        "findings": sorted(findings, key=lambda i: i["number"]),
        "issues": sorted(issues, key=lambda i: i["number"]),
        "local": survey_local(),
        "chip": survey_chip(),
    }


# --------------------------------------------------------------------------
# Graph, derived from the fetched data
# --------------------------------------------------------------------------

STATE_RANK = {"merged": 0, "approved": 1, "review": 2, "draft": 3, "closed": 4}


def pr_state(pr):
    if pr["mergedAt"]:
        return "merged", "merged"
    if pr["state"] == "CLOSED":
        return "closed", "closed"
    if pr["isDraft"]:
        return "draft", "draft"
    if pr.get("reviewDecision") == "APPROVED":
        return "approved", "approved"
    return "review", "in review"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def build_graph(data):
    nodes, order = {}, []
    for pr in data["prs"]:
        for i, c in enumerate(pr["commits"]):
            head = c["messageHeadline"]
            if head not in nodes:
                ann = WORK.get(head, {})
                nodes[head] = {
                    "id": slug(head), "head": head,
                    "short": ann.get("short", head),
                    "verify": ann.get("verify"), "note": ann.get("note"),
                    "prs": [], "deps": set(),
                }
                order.append(head)
            nodes[head]["prs"].append(pr["number"])
            if i > 0:
                nodes[head]["deps"].add(pr["commits"][i - 1]["messageHeadline"])

    for head, deps in EXTRA_DEPS.items():
        if head in nodes:
            nodes[head]["deps"].update(d for d in deps if d in nodes)

    layer = {}

    def depth(head, seen=()):
        if head in layer:
            return layer[head]
        if head in seen:          # a cycle would be a data error, not a stack
            return 0
        layer[head] = 1 + max((depth(d, seen + (head,))
                               for d in nodes[head]["deps"]), default=-1)
        return layer[head]

    for head in order:
        nodes[head]["layer"] = depth(head)

    # Two open branches that change the same file will conflict on rebase
    # whichever lands first. Derived so it cannot drift from the branches.
    overlaps = []
    open_prs = [p for p in data["prs"] if p["state"] == "OPEN"]
    for i, a in enumerate(open_prs):
        for b in open_prs[i + 1:]:
            shared = sorted(set(a.get("files", [])) & set(b.get("files", [])))
            if shared:
                overlaps.append({"a": a["number"], "b": b["number"], "files": shared})
    return nodes, order, overlaps


# --------------------------------------------------------------------------
# Coverage, derived from the chip survey
# --------------------------------------------------------------------------

GROUP_ORDER = ["Pins", "Buses", "Analogue", "Time", "Moving data", "Clocks",
               "Chip services", "Unannotated"]

# Where a driver module can live, per chip. The shared crate counts for both,
# which is the whole point of it.
CRATES_FOR = {"rp2040": ("rp2040", "rp2xxx"), "rp2350": ("rp2350", "rp2xxx")}


def block_names(resets):
    """Map each reset bit to the block it is an instance of.

    SPI0 and SPI1 are two instances of one block and the driver is not per
    instance, so they collapse to SPI. But IO_BANK0 and PADS_BANK0 are single
    blocks whose names happen to end in a digit -- stripping unconditionally
    invented a block called PADS_BANK that no chip has. A name is only treated
    as instanced when some chip really has two or more of it, which also keeps
    the RP2040's lone TIMER and the RP2350's TIMER0/TIMER1 as one block.
    """
    counts = {}
    for bits in resets.values():
        for bit in bits:
            counts.setdefault(re.sub(r"\d+$", "", bit), set()).add(bit)
    return {bit: (stem if len(counts[stem]) > 1 else bit)
            for bits in resets.values() for bit in bits
            for stem in [re.sub(r"\d+$", "", bit)]}


def coverage(data):
    """One row per hardware block, with who has it and who drives it.

    The row list is the union of the two reset controllers' bitfields, so this
    cannot claim the chip has a block it does not, or miss one it does.
    """
    chip = data.get("chip") or {}
    if not chip.get("ok"):
        return None
    mods, up, fork = chip["modules"], chip["upstream_ref"], chip["fork_ref"]

    def crate_holding(ref, chipname, module):
        if module is None or ref not in mods:
            return None
        for crate in CRATES_FOR[chipname]:
            if module in mods[ref].get(crate, {}):
                return crate
        return None

    canon = block_names(chip["resets"])
    instances = {}
    for chipname in ("rp2040", "rp2350"):
        for bit, offset in chip["resets"].get(chipname, {}).items():
            instances.setdefault(canon[bit], {}).setdefault(chipname, []).append(
                (offset, bit))

    rows = []
    for name, per_chip in instances.items():
        group, label, module, what = BLOCKS.get(name, (
            "Unannotated", name, None,
            "No entry in BLOCKS. This block is named by a reset controller in "
            "the tree and nothing here says what it is."))
        row = {
            "name": name, "group": group, "label": label, "module": module,
            "what": what,
            "instances": {c: [b for _, b in sorted(v)] for c, v in per_chip.items()},
            "on": {c: c in per_chip for c in ("rp2040", "rp2350")},
            "rp2040_up": crate_holding(up, "rp2040", module),
            "rp2350_up": crate_holding(up, "rp2350", module),
            "rp2350_fork": crate_holding(fork, "rp2350", module),
            "added_by": chip["added_by"].get(module),
            "caveat": BLOCK_CAVEAT.get(name),
        }
        # The three states the grid draws, in the order a reader compares them.
        # A known defect is deliberately NOT one of them: it belongs to the
        # block, not to a column. Marking the fork's cell for the GPIO
        # interrupt defect would have said the fork is the broken one, when
        # the fork is where the fix is; marking upstream's would have been
        # wrong for the UART, whose fix is unsent and so absent everywhere.
        # The row carries a flag instead, and the detail says who has the fix.
        for key, chipname, ref in (("a", "rp2040", "rp2040_up"),
                                   ("b", "rp2350", "rp2350_up"),
                                   ("c", "rp2350", "rp2350_fork")):
            if not row["on"][chipname]:
                state = "absent"          # the chip has no such block
            elif row[ref]:
                state = "driven"          # a driver module covers it
            else:
                state = "undriven"        # the block is there, nothing drives it
            row[key] = state
        row["flag"] = bool(row["caveat"])
        rows.append(row)

    rank = {"driven": 0, "undriven": 1, "absent": 2}
    rows.sort(key=lambda r: (GROUP_ORDER.index(r["group"]), rank[r["c"]], r["label"]))

    have = [r for r in rows if r["on"]["rp2350"]]
    totals = {
        "blocks2350": len(have),
        "blocks2040": len([r for r in rows if r["on"]["rp2040"]]),
        "up2350": len([r for r in have if r["rp2350_up"]]),
        "fork2350": len([r for r in have if r["rp2350_fork"]]),
        "up2040": len([r for r in rows if r["on"]["rp2040"] and r["rp2040_up"]]),
    }

    modules_seen = sorted({m for ref in (up, fork) if ref in mods
                           for crate in CHIP_CRATES for m in mods[ref][crate]})
    plumbing = [(m, PLUMBING[m]) for m in modules_seen if m in PLUMBING]
    return {"rows": rows, "totals": totals, "plumbing": plumbing,
            "upstream_ref": up, "fork_ref": fork, "head": chip["head"]}


def traces(data, cov):
    """The rungs from a system call down to a register, per block.

    Every rung is read from the tree: the driver number from the enum that
    assigns them, the capsule from the board's own `with_driver`, the HIL from
    what that capsule imports, the chip driver from the crate implementing it,
    and the registers from its `register_structs!`.

    The RP2350's files and the RP2040's are kept apart on purpose. Taking
    whichever file happened to come first put the RP2040's ADC base, 0x4004C000,
    under a block whose RP2350 base is 0x400A0000 -- a page that is wrong in a
    way only somebody with the datasheet open would catch. The RP2040's driver
    is still worth showing, because for the blocks the RP2350 lacks it is the
    thing that would be ported, but it is shown as what it is.
    """
    chip = data.get("chip") or {}
    if not chip.get("ok") or not cov:
        return {}
    fork = chip["fork_ref"]
    nums, capsules = chip["driver_nums"], chip["capsules"]

    # Which capsule sits above which HIL module, so a block can be reached from
    # below. `capsules_core::spi_controller` names hil::spi; the chip's spi.rs
    # names it too, and that is the join.
    by_hil = {}
    for capsule, info in capsules.items():
        for hil in info["hil"]:
            by_hil.setdefault(hil, []).append(capsule)

    boards = chip["boards"].get(fork, {})
    out = {}
    for row in cov["rows"]:
        module = row["module"]
        chain = (chip["chains"].get(module) or {}) if module else {}
        here = [chain[c] for c in ("rp2350", "rp2xxx") if chain.get(c)]
        older = [chain[c] for c in ("rp2040",) if chain.get(c)]
        impls = sorted({i for c in (here or older) for i in c.get("impls", [])})
        # The join is on what the chip driver implements, not what it mentions.
        hil = sorted({i.split("::")[0] for i in impls})
        regs = next((c for c in here if c["regs"]), None)
        source = regs or next((c for c in older if c.get("typed")), None)
        # Up to three registers to open up, richest first and one per bitfield
        # block: inte, intf and ints on the ADC are all typed `INTE::Register`
        # and would otherwise draw the same strip three times.
        inside, seen_blocks = [], set()
        for off, name, blk in (source or {}).get("typed") or []:
            fields = ((source or {}).get("bitfields") or {}).get(blk)
            if not fields or blk in seen_blocks:
                continue
            seen_blocks.add(blk)
            inside.append({"offset": off, "name": name, "block": blk, "fields": fields})
        inside.sort(key=lambda r: (-len(r["fields"]), r["offset"]))
        base = next((c for c in here if c["bases"]), None)
        above = sorted({cap for h in hil for cap in by_hil.get(h, [])})
        out[row["name"]] = {
            "label": row["label"],
            "capsules": [
                {"path": capsules[c]["path"], "name": c,
                 "num": nums.get(capsules[c]["num_name"], ""),
                 "boards": sorted(b for b, ds in boards.items() if c in ds)}
                for c in above],
            "hil": hil,
            "impls": impls,
            "files": [{"path": c["path"], "lines": c["lines"]} for c in here],
            "older": [{"path": c["path"], "lines": c["lines"]} for c in older],
            "regblock": regs["regblock"] if regs else "",
            # A reserved gap is a hole in the map, not a register.
            "regs": [r for r in (regs["regs"] if regs else [])
                     if not r[1].startswith("_")][:20],
            "nregs": len([r for r in (regs["regs"] if regs else [])
                          if not r[1].startswith("_")]),
            "bases": base["bases"] if base else [],
            "inside": inside[:3],
            "bitwidth": (source or {}).get("bitwidth", 32),
            "on2350": row["on"]["rp2350"],
        }
    return out


def queue_rows(data):
    """Every local branch, matched to its pull request where one exists.

    The match is by commit headline overlap rather than by branch name, so a
    renamed branch still finds its pull request and a branch that has drifted
    from the one that was proposed shows up as drifted.
    """
    prs = {p["number"]: p for p in data["prs"]}
    pr_commits = {n: {c["messageHeadline"] for c in p["commits"]}
                  for n, p in prs.items()}
    rows = []
    for repo, branches in sorted(data.get("local", {}).items()):
        for branch, info in sorted(branches.items()):
            key = f"{repo}:{branch}"
            intent, note, blocked = INTENT.get(key, (None, "", None))
            mine = set(info["commits"])
            match, overlap = None, 0
            if repo == "tock" and mine:
                for num, commits in pr_commits.items():
                    shared = len(mine & commits)
                    if shared > overlap:
                        match, overlap = num, shared
            drifted = bool(match) and overlap < len(pr_commits[match])
            rows.append({
                "repo": repo, "branch": branch, "ahead": info["ahead"],
                "commits": info["commits"], "stat": info.get("stat", ""),
                "base": info.get("base", ""), "base_sha": info.get("base_sha", ""),
                "behind": info.get("behind", 0),
                "pushed": info["pushed"], "intent": intent, "note": note,
                # .get for both: a data.json cached before these existed still
                # renders under --offline rather than raising.
                "on_remote": info.get("on_remote", info["pushed"]),
                "unpushed": info.get("unpushed", 0),
                "blocked": blocked, "pr": match, "drifted": drifted,
                "state": pr_state(prs[match])[0] if match else None,
                "label": pr_state(prs[match])[1] if match else None,
            })
    return rows


def queue_groups(rows):
    """Three buckets, and a fourth that is deliberately not shown.

    A branch already merged or closed is dropped: it is in the pull request
    section, and repeating it here would double-count the queue. Tracking
    branches that are level with upstream are dropped for the same reason.
    """
    in_review, ready, never = [], [], []
    for r in rows:
        if r["intent"] == "never":
            r["pr"] = r["state"] = r["label"] = None   # a bench branch that
            r["drifted"] = False                       # contains a proposed
            if r["ahead"] > 0:                         # commit is not that PR
                never.append(r)
        elif r["ahead"] == 0:
            continue                                   # landed, or tracking
        elif r["pr"] and r["state"] in ("review", "approved", "draft"):
            in_review.append(r)
        elif r["pr"] and r["state"] in ("merged", "closed"):
            continue                                   # shown as a pull request
        else:
            ready.append(r)
    order = {"tock": 0, "libtock-rs": 1, "book": 2}
    key = lambda r: (order.get(r["repo"], 9), -r["ahead"])
    return sorted(in_review, key=key), sorted(ready, key=key), sorted(never, key=key)


# --------------------------------------------------------------------------
# Layout and SVG
# --------------------------------------------------------------------------

NODE_W, NODE_H = 198, 62
GAP_X, GAP_Y = 22, 30
PAD = 22
HEADER_H = 44


def wrap(text, width=30, lines=2):
    words, out, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) <= width:
            cur = trial
        elif len(out) + 1 < lines:
            out.append(cur or w)
            cur = "" if not cur else w
        else:
            out.append(cur)
            cur = w
            break
    if cur:
        out.append(cur)
    out = [o for o in out if o][:lines]
    joined = " ".join(out)
    if len(joined) < len(text):
        out[-1] = out[-1][:width - 1].rstrip() + "…"
    return out


def layout(nodes, order, lanes):
    """One column per pull request; depth down the column is stack order.

    A commit that appears in two pull requests is drawn in the lane of the
    lower-numbered one — the smaller review that is already open on its own —
    so every node has exactly one home and the edges into the taller stack
    show the crossing rather than hiding it.
    """
    lane_x = {pr: PAD + i * (NODE_W + GAP_X) for i, pr in enumerate(lanes)}
    for head in order:
        n = nodes[head]
        n["lane"] = min(n["prs"])
        n["x"] = lane_x[n["lane"]]
        n["y"] = PAD + HEADER_H + n["layer"] * (NODE_H + GAP_Y)
    canvas_w = PAD * 2 + len(lanes) * NODE_W + (len(lanes) - 1) * GAP_X
    depth = max(nodes[h]["layer"] for h in order) + 1
    canvas_h = PAD * 2 + HEADER_H + depth * (NODE_H + GAP_Y) - GAP_Y
    return canvas_w, canvas_h, lane_x


def e(t):
    return html.escape(str(t))


def para(text):
    blocks = [b.strip().replace("\n", " ") for b in text.strip().split("\n\n")]
    return "\n".join("<p>" + e(b) + "</p>" for b in blocks if b)


def svg(nodes, order, pr_by_num):
    lanes = sorted(pr_by_num)
    w, h, lane_x = layout(nodes, order, lanes)

    bands, heads = [], []
    for pr in lanes:
        st, label = pr_state(pr_by_num[pr])
        x = lane_x[pr]
        bands.append('<rect class="lane l-%s" x="%.0f" y="%.0f" width="%d" height="%.0f" rx="9"/>'
                     % (st, x - 9, PAD + 4, NODE_W + 18, h - PAD * 2 - 4))
        heads.append('<text class="lanenum" x="%.0f" y="%.0f">#%d</text>'
                     '<text class="lanest s-%s" x="%.0f" y="%.0f">%s</text>'
                     % (x, PAD + 22, pr, st, x, PAD + 37, e(label)))

    edges = []
    for head in order:
        n = nodes[head]
        for dep in sorted(n["deps"]):
            d = nodes[dep]
            x1, y1 = d["x"] + NODE_W / 2, d["y"] + NODE_H
            x2, y2 = n["x"] + NODE_W / 2, n["y"]
            mid = (y1 + y2) / 2
            cross = " cross" if d["lane"] != n["lane"] else ""
            shared = " ".join(str(p) for p in sorted(set(d["prs"]) & set(n["prs"])))
            edges.append('<path class="edge%s" d="M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" '
                         'data-prs="%s"/>'
                         % (cross, x1, y1, x1, mid, x2, mid, x2, y2, shared))

    boxes = []
    for head in order:
        n = nodes[head]
        st = min((pr_state(pr_by_num[p])[0] for p in n["prs"]),
                 key=lambda s: STATE_RANK[s])
        tspans = "".join('<tspan x="%.0f" dy="%d">%s</tspan>'
                         % (n["x"] + 12, 0 if i == 0 else 14, e(l))
                         for i, l in enumerate(wrap(n["short"], 25, 2)))
        badge = ""
        if n["verify"]:
            badge = ('<text class="badge v-%s" x="%.0f" y="%.0f">%s</text>'
                     % (n["verify"], n["x"] + 12, n["y"] + NODE_H - 9,
                        e(VERIFY[n["verify"]][0])))
        refs = " ".join("#%d" % p for p in sorted(n["prs"]))
        shared_cls = " shared" if len(n["prs"]) > 1 else ""
        aria = "%s, in %s, %s" % (n["short"], refs,
                                  VERIFY[n["verify"]][0] if n["verify"] else "unannotated")
        boxes.append(
            '<g class="node st-%s%s" data-prs="%s" data-id="%s" tabindex="0" '
            'role="listitem" aria-label="%s">'
            '<rect x="%.0f" y="%.0f" width="%d" height="%d" rx="7"/>'
            '<text class="label" x="%.0f" y="%.0f">%s</text>%s'
            '<text class="refs" x="%.0f" y="%.0f" text-anchor="end">%s</text></g>'
            % (st, shared_cls, " ".join(str(p) for p in n["prs"]), n["id"], e(aria),
               n["x"], n["y"], NODE_W, NODE_H,
               n["x"] + 12, n["y"] + 21, tspans, badge,
               n["x"] + NODE_W - 12, n["y"] + NODE_H - 9, e(refs))
        )

    return ('<svg id="graph" viewBox="0 0 %.0f %.0f" width="%.0f" height="%.0f" '
            'role="list" aria-label="Every commit across the pull requests, one column per request">'
            '<g class="lanes">%s</g><g class="laneheads">%s</g>'
            '<g class="edges">%s</g>%s</svg>'
            % (w, h, w, h, "".join(bands), "".join(heads), "".join(edges), "".join(boxes)))


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

CSS = """
:root{--bg:#fbfaf8;--panel:#fff;--ink:#16171a;--ink-soft:#4f5157;--ink-faint:#6f7278;
--line:#e4e2dd;--accent:#7a4b1e;--edge:#c6c3bc;
--merged-bg:#e3f0e4;--merged-ink:#1c5228;--merged-line:#5f9c6d;
--review-bg:#e2ecf7;--review-ink:#1d4b7a;--review-line:#6b9ac6;
--approved-bg:#e7ecda;--approved-ink:#46561f;--approved-line:#8aa053;
--draft-bg:#eceae7;--draft-ink:#4e4f54;--draft-line:#a3a2a0;
--closed-bg:#f6e3e3;--closed-ink:#86282a;--closed-line:#c08a8a;
--unfiled-bg:#f8ecd8;--unfiled-ink:#744d0d;
--host:#1d4b7a;--silicon:#7a3b12;--sections:#46561f;--build:#5b5c62;--none:#636469;
--driven:#1c5228;--undriven:#744d0d;--absent:#6f7278;}
@media (prefers-color-scheme:dark){:root{
--bg:#131316;--panel:#1b1c20;--ink:#edecea;--ink-soft:#b6b6ba;--ink-faint:#8e8f95;
--line:#2c2d33;--accent:#d9a273;--edge:#42444c;
--merged-bg:#1d3324;--merged-ink:#8fd3a0;--merged-line:#4a8a5e;
--review-bg:#1b2c3f;--review-ink:#8fbde8;--review-line:#4574a0;
--approved-bg:#2a3119;--approved-ink:#b9cd88;--approved-line:#728848;
--draft-bg:#26272c;--draft-ink:#a9aab0;--draft-line:#5d5e65;
--closed-bg:#3a2222;--closed-ink:#e29a9a;--closed-line:#8a5252;
--unfiled-bg:#3a2f1a;--unfiled-ink:#e3bd7c;
--host:#8fbde8;--silicon:#e0a874;--sections:#b9cd88;--build:#a9aab0;--none:#9a9ba1;
--driven:#8fd3a0;--undriven:#e3bd7c;--absent:#8e8f95;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);min-width:1040px;
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1280px;margin:0 auto;padding:0 32px 100px}
header{padding:64px 0 30px}
h1{font-size:2.4rem;margin:0 0 10px;letter-spacing:-.02em}
.tagline{color:var(--ink-soft);font-size:1.1rem;margin:0 0 30px;max-width:64ch}
blockquote{margin:0 0 20px;padding:16px 22px;border-left:3px solid var(--accent);
background:var(--panel);border-radius:0 8px 8px 0;color:var(--ink-soft);font-size:.97rem}
blockquote cite{display:block;margin-top:9px;font-style:normal;font-size:.83rem;color:var(--ink-faint)}
blockquote cite a{color:var(--accent)}
header p{max-width:76ch;color:var(--ink-soft)}
h2{font-size:1.4rem;margin:0 0 6px;letter-spacing:-.01em}
.lede{color:var(--ink-soft);max-width:78ch;margin:0 0 18px}
section{padding:50px 0 0}
ul.counts{display:flex;gap:34px;list-style:none;padding:0;margin:30px 0 0}
ul.counts a{text-decoration:none;color:inherit;display:block}
ul.counts a:hover .k{color:var(--accent)}
ul.counts .n{display:block;font-size:1.9rem;font-weight:600;letter-spacing:-.02em}
ul.counts .k{display:block;font-size:.78rem;text-transform:uppercase;
letter-spacing:.07em;color:var(--ink-faint)}
code.branch{background:var(--draft-bg);padding:2px 7px;border-radius:5px;
font-size:.8rem;color:var(--ink)}
details.facts{margin:10px 0 0}
details.facts>summary{cursor:pointer;font-size:.82rem;color:var(--accent);
font-weight:600;list-style:none;display:inline-block;padding:3px 0}
details.facts>summary::-webkit-details-marker{display:none}
details.facts>summary::before{content:"\25B8 ";display:inline-block;
transition:transform .12s;font-size:.8em}
details.facts[open]>summary::before{content:"\25BE "}
details.facts .basis{font-size:.78rem;color:var(--ink-faint);margin:8px 0 12px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
details.facts dl{margin:0;padding:14px 16px;background:var(--bg);
border:1px solid var(--line);border-radius:8px}
details.facts dt{font-size:.78rem;font-weight:700;text-transform:uppercase;
letter-spacing:.05em;color:var(--ink);margin:12px 0 3px}
details.facts dt:first-child{margin-top:0}
details.facts dd{margin:0;font-size:.9rem;color:var(--ink-soft);max-width:80ch}
details.facts h4{font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;
color:var(--ink-faint);margin:14px 0 4px}
ol.commitlist{margin:0;padding-left:22px;font-size:.85rem;color:var(--ink-soft);
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
ol.commitlist li{margin:3px 0}
ol.commitlist li.more{list-style:none;color:var(--ink-faint);font-style:italic}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}
.chip{display:flex;align-items:center;gap:9px;padding:7px 12px 7px 13px;border-radius:999px;
border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;font:inherit;font-size:.84rem}
.chip:hover{border-color:var(--accent)}
.chip .num{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;color:var(--accent)}
.chip .ct{color:var(--ink-faint);font-size:.78rem}
/* A closing reference, not a mention: `Fixes #N` in the body, which is
   what GitHub turns into a linked issue that closes on merge. A bare
   "#N" only makes a timeline cross-reference and is not shown. */
.chip .closes{color:var(--ink-soft);font-size:.72rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;border-left:1px solid var(--line);padding-left:9px}
.chip[aria-pressed=true]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.hint{color:var(--ink-faint);font-size:.84rem;margin:0 0 16px}
.canvas{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px;overflow-x:auto}
svg#graph{display:block}
.lane{fill:var(--bg);stroke:var(--line);stroke-width:1}
.lane.l-merged{fill:color-mix(in srgb,var(--merged-bg) 34%,var(--bg))}
.lane.l-approved{fill:color-mix(in srgb,var(--approved-bg) 34%,var(--bg))}
.lane.l-review{fill:color-mix(in srgb,var(--review-bg) 30%,var(--bg))}
.lane.l-draft{fill:var(--bg)}
.lane.l-closed{fill:color-mix(in srgb,var(--closed-bg) 26%,var(--bg))}
.lanenum{font:700 14px ui-monospace,SFMono-Regular,Menlo,monospace;fill:var(--accent)}
.lanest{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.s-merged{fill:var(--merged-ink)}.s-approved{fill:var(--approved-ink)}
.s-review{fill:var(--review-ink)}.s-draft{fill:var(--draft-ink)}.s-closed{fill:var(--closed-ink)}
.edge{fill:none;stroke:var(--edge);stroke-width:1.6}
.edge.cross{stroke-dasharray:5 4;stroke:var(--accent);stroke-width:2}
.node.shared rect{stroke-dasharray:6 3;stroke-width:2.2}
.node{cursor:pointer;outline:none}
.node rect{fill:var(--panel);stroke:var(--draft-line);stroke-width:1.5}
.node .label{font-size:12.5px;font-weight:600;fill:var(--ink)}
.node .refs{font-size:10.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;fill:var(--ink-faint)}
.node .badge{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.node:hover rect,.node:focus rect{stroke-width:3}
.st-merged rect{stroke:var(--merged-line);fill:var(--merged-bg)}
.st-approved rect{stroke:var(--approved-line);fill:var(--approved-bg)}
.st-review rect{stroke:var(--review-line);fill:var(--review-bg)}
.st-draft rect{stroke:var(--draft-line);fill:var(--draft-bg)}
.st-closed rect{stroke:var(--closed-line);fill:var(--closed-bg)}
.v-host{fill:var(--host)}.v-silicon{fill:var(--silicon)}.v-sections{fill:var(--sections)}
.v-build{fill:var(--build)}.v-none{fill:var(--none)}
svg.filtered .node{opacity:.15}svg.filtered .node.on{opacity:1}
svg.filtered .edge{opacity:.07}
svg.filtered .edge.on{opacity:1;stroke:var(--accent);stroke-width:2.2}
.readout{display:grid;grid-template-columns:1fr 340px;gap:18px;margin-top:18px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px}
.panel h3{margin:0 0 8px;font-size:1rem}
.panel p{margin:0 0 8px;font-size:.9rem;color:var(--ink-soft)}
.panel .head{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.76rem;
color:var(--ink-faint);word-break:break-word;margin:0}
ul.plain{list-style:none;padding:0;margin:0}
ul.plain li{padding:13px 0;border-top:1px solid var(--line);color:var(--ink-soft);font-size:.93rem}
ul.plain li strong{color:var(--ink);font-weight:600}
ul.plain li .dd{display:block;margin-top:3px}
ul.plain li .pill{margin-right:9px}
ul.legend li{display:flex;gap:14px;align-items:baseline}
ul.legend .badge{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
min-width:132px;display:inline-block}
ul.legend .n{min-width:24px;text-align:right;color:var(--ink);font-weight:600}
.badge.v-host{color:var(--host)}.badge.v-silicon{color:var(--silicon)}
.badge.v-sections{color:var(--sections)}.badge.v-build{color:var(--build)}.badge.v-none{color:var(--none)}
h3.qh{font-size:1rem;margin:26px 0 2px;color:var(--ink)}
ul.queue li .qhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
ul.queue li code{font-size:.84rem;color:var(--ink);font-weight:600}
ul.queue .ahead{font-size:.78rem;color:var(--ink-faint)}
ul.queue .dd.blocked{color:var(--ink-faint);font-style:italic}
.prgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:14px}
.prcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;scroll-margin:80px}
.prcard.lit{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.prhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
.prcard h3{font-size:.97rem;margin:0 0 9px;line-height:1.4}
.prcard .share{font-size:.85rem;color:var(--ink-faint);margin:9px 0 0;
border-top:1px dashed var(--line);padding-top:9px}
.ref{font:600 .85rem/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent);text-decoration:none}
.ref:hover{text-decoration:underline}
.pill{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
padding:3px 9px;border-radius:999px;white-space:nowrap}
.pill.merged{background:var(--merged-bg);color:var(--merged-ink)}
.pill.review{background:var(--review-bg);color:var(--review-ink)}
.pill.approved{background:var(--approved-bg);color:var(--approved-ink)}
.pill.draft{background:var(--draft-bg);color:var(--draft-ink)}
.pill.closed{background:var(--closed-bg);color:var(--closed-ink)}
.pill.unfiled{background:var(--unfiled-bg);color:var(--unfiled-ink)}
.meta{display:flex;gap:14px;font-size:.78rem;color:var(--ink-faint)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82em}
footer{margin-top:70px;padding-top:22px;border-top:1px solid var(--line);color:var(--ink-faint);font-size:.85rem}
footer a{color:var(--accent)}
/* ---- the shell: a rail that stays put, and a column that scrolls ---- */
.skip{position:absolute;left:-9999px;top:0;background:var(--panel);color:var(--ink);
padding:10px 14px;border:1px solid var(--accent);border-radius:0 0 8px 0;z-index:99}
.skip:focus{left:0}
.app{display:grid;grid-template-columns:238px minmax(0,1fr);align-items:start}
.rail{position:sticky;top:0;height:100vh;overflow-y:auto;background:var(--panel);
border-right:1px solid var(--line);padding:26px 14px 22px}
.rail .mark{display:block;text-decoration:none;color:var(--ink);font-size:.95rem;
padding:0 8px;margin:0 0 20px;letter-spacing:-.01em}
.rail .mark b{color:var(--accent)}
.rail ul{list-style:none;margin:0;padding:0}
.rail .navgroup{font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;
color:var(--ink-faint);padding:0 8px;margin:20px 0 5px}
.rail .navgroup:first-child{margin-top:0}
.rail a{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
text-decoration:none;color:var(--ink-soft);font-size:.85rem;padding:5px 8px;border-radius:6px}
.rail a:hover{background:var(--bg);color:var(--ink)}
.rail a.here{background:var(--bg);color:var(--ink);box-shadow:inset 2px 0 0 var(--accent)}
.rail .rn{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.71rem;
color:var(--ink-faint);white-space:nowrap}
.railkeys{margin:24px 8px 0;font-size:.72rem;color:var(--ink-faint)}
kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;
border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:1px 5px;
background:var(--bg);color:var(--ink-soft)}
section{scroll-margin-top:18px}

/* ---- the coverage grid ---- */
ul.counts .k em{display:block;font-style:normal;text-transform:none;letter-spacing:0;
font-size:.78rem;color:var(--ink-faint);margin-top:2px}
ul.cellkey{display:flex;gap:26px;margin:0 0 14px}
ul.cellkey li{display:flex;align-items:center;gap:9px;border-top:0;padding:0;
font-size:.8rem;color:var(--ink-faint)}
.covwrap{background:var(--panel);border:1px solid var(--line);border-radius:10px;
overflow:hidden}
.covhead,.brow{display:grid;grid-template-columns:minmax(210px,1.5fr) repeat(3,62px) minmax(150px,.85fr);
gap:10px;align-items:center}
.covhead{padding:10px 16px;border-bottom:1px solid var(--line);font-size:.68rem;
text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint)}
.chead{text-align:center}
.covhead .bby{text-align:right}
ul.cov{list-style:none;margin:0;padding:0}
ul.cov li{padding:0}
ul.cov li.cgroup{padding:14px 16px 6px;border-top:1px solid var(--line);font-size:.68rem;
text-transform:uppercase;letter-spacing:.08em;color:var(--ink-faint)}
ul.cov li.cgroup:first-child{border-top:0}
.brow{width:100%;text-align:left;background:none;border:0;font:inherit;color:var(--ink);
padding:7px 16px;cursor:pointer}
.brow:hover{background:var(--bg)}
.brow.sel{background:var(--bg);box-shadow:inset 3px 0 0 var(--accent)}
.brow.flat{cursor:default}
.bname{font-size:.89rem;display:flex;align-items:center;gap:8px}
.cell{width:15px;height:15px;border-radius:4px;justify-self:center;display:block;position:relative}
.c-driven{background:var(--driven)}
.c-undriven{box-shadow:inset 0 0 0 1.5px var(--undriven)}
.c-absent::after{content:"";position:absolute;left:2px;right:2px;top:7px;height:1.5px;
background:var(--absent)}
.bby{font-size:.75rem;color:var(--ink-faint);text-align:right;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.bby .up{font-style:italic}
.flag{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;
border-radius:50%;background:var(--accent);color:var(--panel);font-size:.62rem;
font-weight:700;flex:none}
.foot{font-size:.78rem;color:var(--ink-faint);margin:12px 0 0;max-width:80ch}

/* ---- the trace: a ladder from a system call to a register ---- */
.traces{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px 22px}
.trace h3{margin:0 0 5px;font-size:1.06rem;display:flex;gap:11px;align-items:baseline;flex-wrap:wrap}
.binst{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.71rem;
color:var(--ink-faint);font-weight:400}
.trace .what{margin:0 0 15px;color:var(--ink-soft);font-size:.92rem;max-width:82ch}
.tcaveat{margin:0 0 15px;padding:11px 14px;background:var(--unfiled-bg);color:var(--unfiled-ink);
border-radius:8px;font-size:.86rem;max-width:82ch}
.tcaveat strong{color:var(--unfiled-ink)}
.tnote{margin:0 0 15px;font-size:.86rem;color:var(--ink-faint);max-width:82ch}
ol.rungs{list-style:none;margin:0;padding:0;position:relative}
ol.rungs::before{content:"";position:absolute;left:145px;top:16px;bottom:16px;width:1px;
background:var(--line)}
ol.rungs li{display:grid;grid-template-columns:130px minmax(0,1fr);gap:30px;
padding:11px 0;border-top:1px solid var(--line);align-items:baseline;position:relative}
ol.rungs li:first-child{border-top:0}
ol.rungs li::after{content:"";position:absolute;left:142px;top:17px;width:7px;height:7px;
border-radius:50%;background:var(--accent)}
ol.rungs li.off::after{background:var(--line)}
.rname{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-faint)}
.rval{font-size:.88rem;color:var(--ink-soft)}
ol.rungs li.off .rval{color:var(--ink-faint);font-style:italic}
.rval .dim{color:var(--ink-faint);font-size:.8rem}
.num{color:var(--accent)}
.regblock{display:block;margin-bottom:7px}
.regs{display:flex;flex-wrap:wrap;gap:5px}
.reg{display:inline-flex;flex-direction:column;gap:1px;border:1px solid var(--line);
border-radius:5px;padding:3px 7px;background:var(--bg);
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.69rem;color:var(--ink-soft)}
.reg b{color:var(--accent);font-size:.65rem;font-weight:600}
.reg.more{justify-content:center;color:var(--ink-faint)}

/* ---- the forty pins ---- */
.ptabs{display:flex;gap:8px;margin:0 0 14px}
.ptab{display:flex;flex-direction:column;gap:2px;align-items:flex-start;padding:8px 14px;
border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--ink);
font:inherit;font-size:.88rem;cursor:pointer}
.ptab em{font-style:normal;font-size:.74rem;color:var(--ink-faint)}
.ptab:hover{border-color:var(--accent)}
.ptab.sel{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.pinswatch{width:13px;height:13px;border-radius:3px;display:inline-block;flex:none}
.pinmap{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
.header{display:grid;grid-template-columns:1fr 1fr;gap:0 30px}
ol.hcol{list-style:none;margin:0;padding:0}
.pin{display:flex;align-items:center;gap:10px;padding:4px 8px;border-radius:6px;
font-size:.82rem;line-height:1.3;border-left:3px solid transparent}
.pin.mirror{flex-direction:row-reverse;text-align:right;border-left:0;
border-right:3px solid transparent}
.pnum{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.7rem;
color:var(--ink-faint);width:20px;flex:none;text-align:center}
.pname{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;
width:66px;flex:none;color:var(--ink)}
.pin.mirror .pname{text-align:right}
.prole{color:var(--ink-soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.p-user{background:color-mix(in srgb,var(--merged-bg) 60%,transparent);border-left-color:var(--driven)}
.p-user.mirror{border-right-color:var(--driven)}
.p-kernel{background:color-mix(in srgb,var(--review-bg) 55%,transparent);border-left-color:var(--review-line)}
.p-kernel.mirror{border-right-color:var(--review-line)}
.p-radio{background:color-mix(in srgb,var(--unfiled-bg) 60%,transparent);border-left-color:var(--undriven)}
.p-radio.mirror{border-right-color:var(--undriven)}
.p-adc{background:color-mix(in srgb,var(--approved-bg) 60%,transparent);border-left-color:var(--approved-line)}
.p-adc.mirror{border-right-color:var(--approved-line)}
.p-off{background:var(--bg);border-left-color:var(--line)}
.p-off.mirror{border-right-color:var(--line)}
.p-free{color:var(--ink-faint)}
.p-gnd,.p-power,.p-ctrl{color:var(--ink-faint)}
.p-gnd .pname{color:var(--ink-faint)}
.p-power .pname{color:var(--closed-ink)}
.p-ctrl .pname{color:var(--ink-soft)}
h3.offh{margin:22px 0 4px;font-size:1rem}
ul.offpins{list-style:none;margin:10px 0 0;padding:0;display:grid;
grid-template-columns:repeat(4,1fr);gap:8px}
ul.offpins .pin{border:1px solid var(--line);flex-direction:column;align-items:flex-start;gap:3px}
ul.offpins .pname{width:auto}
ul.offpins .prole{white-space:normal;font-size:.78rem}

/* ---- one register, opened up ---- */
.insides{margin-top:9px}
.rtabs{display:flex;gap:6px;margin:0 0 9px;flex-wrap:wrap}
.rtab{display:flex;align-items:baseline;gap:7px;padding:4px 10px;border-radius:7px;
border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit;
font-size:.78rem;cursor:pointer}
.rtab:hover{border-color:var(--accent)}
.rtab.sel{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.rtab code{font-weight:600}
.bits{display:flex;gap:2px;align-items:stretch;min-height:44px}
.bf{display:flex;flex-direction:column;justify-content:center;gap:2px;min-width:0;
padding:5px 4px;border-radius:5px;background:color-mix(in srgb,var(--review-bg) 70%,transparent);
border:1px solid var(--review-line);font-size:.66rem;color:var(--ink);text-align:center;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bf b{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;
font-size:.6rem;color:var(--ink-faint)}
.bf.gap{background:transparent;border-style:dashed;border-color:var(--line);color:var(--ink-faint)}

/* ---- the queue, drawn ---- */
svg#queuegraph{display:block}
.qhname{font-size:12px;font-weight:700;letter-spacing:.02em}
.qhname.s-draft{fill:var(--accent)}
.qhsub{font-size:10px;fill:var(--ink-faint)}
.qcard{cursor:pointer;outline:none}
.qcard rect{fill:var(--panel);stroke:var(--draft-line);stroke-width:1.5}
.qcard .qlabel{font-size:12px;font-weight:600;fill:var(--ink)}
.qcard .qmeta{font-size:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
fill:var(--ink-soft)}
.qcard .qwait{fill:var(--accent);font-weight:700}
.qcard:hover rect,.qcard:focus rect{stroke-width:3}
.qcard.sel rect{stroke-width:3;stroke:var(--accent)}
.qedge{fill:none;stroke:var(--accent);stroke-width:2;stroke-dasharray:5 4}
.qhead{fill:var(--accent)}

.bigref{display:inline-block;padding:9px 16px;border-radius:9px;border:1px solid var(--accent);
color:var(--accent);text-decoration:none;font-weight:600;font-size:.92rem}
.bigref:hover{background:var(--accent);color:var(--panel)}

/* ---- what selecting a block lights up elsewhere ---- */
.rel{box-shadow:inset 3px 0 0 var(--accent)}
.qcard.rel rect{stroke:var(--accent);stroke-width:3}
.chip.rel,.prcard.rel{box-shadow:0 0 0 1px var(--accent)}

/* ---- search and the key sheet ---- */
.sheet{position:fixed;inset:0;z-index:60;display:flex;justify-content:center;
align-items:flex-start;padding-top:11vh;background:rgba(12,12,14,.45)}
.sheet[hidden]{display:none}
.sheetbox{background:var(--panel);border:1px solid var(--line);border-radius:12px;
width:min(660px,92vw);padding:18px;box-shadow:0 20px 64px rgba(0,0,0,.3)}
.sheetbox h2{margin:0 0 12px}
#q{width:100%;font:inherit;font-size:1rem;padding:11px 13px;border-radius:8px;
border:1px solid var(--line);background:var(--bg);color:var(--ink)}
#q:focus{outline:2px solid var(--accent);outline-offset:1px}
.phint{font-size:.76rem;color:var(--ink-faint);margin:9px 3px 0}
#presults{list-style:none;margin:8px 0 0;padding:0;max-height:46vh;overflow-y:auto}
#presults li{display:flex;justify-content:space-between;gap:14px;padding:8px 10px;
border-radius:7px;font-size:.87rem;color:var(--ink-soft);cursor:pointer}
#presults li.on{background:var(--bg);color:var(--ink)}
#presults .kind{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;
color:var(--ink-faint);white-space:nowrap}
dl.keys{display:grid;grid-template-columns:130px 1fr;gap:9px 16px;margin:0;
font-size:.88rem;color:var(--ink-soft)}
dl.keys dt,dl.keys dd{margin:0}

@media (max-width:1100px){
.app{grid-template-columns:minmax(0,1fr)}
.rail{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}
.rail ul{display:flex;flex-wrap:wrap;gap:3px}
.rail .navgroup,.rail .rn{display:none}
}
"""

JS = """
const NODES = __NODES__;
const svg = document.getElementById('graph');
const chips = [...document.querySelectorAll('.chip')];
let active = null;

function applyFilter(pr) {
  active = pr;
  chips.forEach(c => c.setAttribute('aria-pressed', String(c.dataset.pr === pr)));
  document.querySelectorAll('.prcard').forEach(
    c => c.classList.toggle('lit', c.dataset.pr === pr));
  if (!pr) { svg.classList.remove('filtered'); return; }
  svg.classList.add('filtered');
  svg.querySelectorAll('.node, .edge').forEach(el => {
    const prs = (el.dataset.prs || '').split(' ').filter(Boolean);
    el.classList.toggle('on', prs.includes(pr));
  });
}

chips.forEach(c => c.addEventListener('click', () => {
  applyFilter(active === c.dataset.pr ? null : c.dataset.pr);
}));

function showDetail(id) {
  const n = NODES[id];
  if (!n) return;
  document.getElementById('d-title').textContent = n.short;
  const bits = [];
  if (n.note) bits.push(n.note);
  if (n.verify) bits.push(n.verifyLabel.toUpperCase() + ' — ' + n.verify);
  document.getElementById('d-note').textContent =
    bits.join(' ') || 'No annotation for this commit yet.';
  document.getElementById('d-head').textContent =
    n.head + '  ·  in ' + n.prs.map(p => '#' + p).join(', ');
}

svg.querySelectorAll('.node').forEach(g => {
  g.addEventListener('click', () => showDetail(g.dataset.id));
  g.addEventListener('focus', () => showDetail(g.dataset.id));
  g.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); showDetail(g.dataset.id); }
  });
});

/* ---- hardware blocks: one selection drives the trace and lights the work ---- */
const REL = __REL__;
const brows = [...document.querySelectorAll('.brow[data-block]')];
const traceEls = [...document.querySelectorAll('.trace')];
let block = (brows.find(b => b.classList.contains('sel')) || brows[0] || {dataset: {}}).dataset.block;

function selectBlock(name) {
  if (!name) return;
  block = name;
  brows.forEach(b => b.classList.toggle('sel', b.dataset.block === name));
  traceEls.forEach(t => { t.hidden = t.id !== 'tr-' + name; });
  const r = REL[name] || {branches: [], prs: []};
  document.querySelectorAll('[data-branch]').forEach(
    el => el.classList.toggle('rel', r.branches.includes(el.dataset.branch)));
  document.querySelectorAll('.prcard, .chip').forEach(
    el => el.classList.toggle('rel', r.prs.includes(Number(el.dataset.pr))));
}

brows.forEach(b => b.addEventListener('click', () => selectBlock(b.dataset.block)));
if (block) selectBlock(block);

function stepBlock(delta) {
  if (!brows.length) return;
  const at = brows.findIndex(b => b.dataset.block === block);
  const next = brows[(at + delta + brows.length) % brows.length];
  selectBlock(next.dataset.block);
  next.scrollIntoView({block: 'nearest'});
}

/* ---- the queue graph ---- */
const QUEUE = __QUEUE__;
const qcards = [...document.querySelectorAll('.qcard[data-card]')];

function showQueue(id) {
  const card = QUEUE[id];
  if (!card) return;
  qcards.forEach(c => c.classList.toggle('sel', c.dataset.card === id));
  document.getElementById('q-title').textContent = card.title;
  const said = [];
  if (card.note) said.push(card.note);
  if (card.blocked) said.push(card.blocked);
  card.waits.forEach(w => said.push(w));
  document.getElementById('q-note').textContent =
    said.join(' ') || 'No intent recorded for this one.';
  document.getElementById('q-meta').textContent =
    [card.key, card.meta, card.stat].filter(Boolean).join('  ·  ');
}

qcards.forEach(card => {
  card.addEventListener('click', () => showQueue(card.dataset.card));
  card.addEventListener('focus', () => showQueue(card.dataset.card));
  card.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      showQueue(card.dataset.card);
    }
  });
});

/* ---- the pin map: one board at a time ---- */
const ptabs = [...document.querySelectorAll('.ptab[data-board]')];
ptabs.forEach(tab => tab.addEventListener('click', () => {
  ptabs.forEach(other => {
    const on = other === tab;
    other.classList.toggle('sel', on);
    other.setAttribute('aria-pressed', String(on));
  });
  document.querySelectorAll('.pinmap').forEach(
    map => { map.hidden = map.id !== 'pm-' + tab.dataset.board; });
}));

/* ---- register tabs, scoped to the trace they sit in ---- */
document.querySelectorAll('.insides').forEach(group => {
  const tabs = [...group.querySelectorAll('.rtab')];
  tabs.forEach(tab => tab.addEventListener('click', () => {
    tabs.forEach(other => {
      const on = other === tab;
      other.classList.toggle('sel', on);
      other.setAttribute('aria-pressed', String(on));
    });
    group.querySelectorAll('.bits').forEach(
      strip => { strip.hidden = strip.id !== tab.dataset.panel; });
  }));
});

/* ---- which section the rail points at ----
   Feature-detected, and deliberately so: this is a nicety, and everything
   below it -- search, the keys, the whole palette -- is not. One script means
   one throw takes out every feature after the throw, which is how a page keeps
   working in the browser it was written in and quietly stops being useful in
   an older one. */
const links = new Map([...document.querySelectorAll('.rail a[href^="#"]')]
  .filter(a => a.getAttribute('href').length > 1)
  .map(a => [a.getAttribute('href').slice(1), a]));
if (typeof IntersectionObserver === 'function') {
  const spy = new IntersectionObserver(entries => {
    entries.forEach(en => {
      const a = links.get(en.target.id);
      if (a && en.isIntersecting) {
        links.forEach(l => l.classList.remove('here'));
        a.classList.add('here');
      }
    });
  }, {rootMargin: '0px 0px -72% 0px'});
  links.forEach((a, id) => { const el = document.getElementById(id); if (el) spy.observe(el); });
}

/* ---- search: the index is the page, so it cannot drift from it ---- */
const palette = document.getElementById('palette');
const keysheet = document.getElementById('keysheet');
const qbox = document.getElementById('q');
const presults = document.getElementById('presults');
let hits = [], at = 0;

function jumpTo(el, then) {
  el.scrollIntoView({block: 'center', behavior: 'smooth'});
  if (then) then();
}

function buildIndex() {
  const items = [];
  const add = (kind, text, act) => { if (text) items.push({kind, text: text.trim(), act}); };
  brows.forEach(b => add('block', b.dataset.label,
    () => { selectBlock(b.dataset.block); jumpTo(b); }));
  document.querySelectorAll('.prcard').forEach(c => add(
    'pull request', '#' + c.dataset.pr + ' ' + c.querySelector('h3').textContent,
    () => jumpTo(c)));
  document.querySelectorAll('#stack .node').forEach(g => add(
    'commit', g.querySelector('.label').textContent,
    () => { showDetail(g.dataset.id); jumpTo(document.getElementById('stack')); }));
  document.querySelectorAll('[data-branch]').forEach(li => add(
    'branch', li.dataset.branch, () => jumpTo(li)));
  document.querySelectorAll('#defects li strong').forEach(el => add(
    'defect', el.textContent, () => jumpTo(el.closest('li'))));
  document.querySelectorAll('#silicon li strong').forEach(el => add(
    'on silicon', el.textContent, () => jumpTo(el.closest('li'))));
  document.querySelectorAll('.rail a[href^="#"]').forEach(a => {
    const id = a.getAttribute('href').slice(1);
    const el = id && document.getElementById(id);
    if (el) add('section', a.firstChild.textContent, () => jumpTo(el));
  });
  return items;
}
const INDEX = brows.length || document.querySelector('.prcard') ? buildIndex() : [];

function score(text, q) {
  const t = text.toLowerCase();
  const i = t.indexOf(q);
  if (i === 0) return 0;
  if (i > 0) return 1;
  let at = 0;                       // every letter, in order, anywhere
  for (const ch of q) { at = t.indexOf(ch, at) + 1; if (!at) return -1; }
  return 2;
}

function runSearch() {
  const q = qbox.value.trim().toLowerCase();
  hits = !q ? INDEX.slice(0, 8)
            : INDEX.map(it => [score(it.text, q), it]).filter(p => p[0] >= 0)
                   .sort((a, b) => a[0] - b[0]).slice(0, 12).map(p => p[1]);
  at = 0;
  presults.replaceChildren(...hits.map((it, i) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.className = i === 0 ? 'on' : '';
    const label = document.createElement('span');
    label.textContent = it.text;
    const kind = document.createElement('span');
    kind.className = 'kind';
    kind.textContent = it.kind;
    li.append(label, kind);
    li.addEventListener('click', () => { closeSheets(); it.act(); });
    return li;
  }));
}

function mark() {
  [...presults.children].forEach((li, i) => li.classList.toggle('on', i === at));
  const on = presults.children[at];
  if (on) on.scrollIntoView({block: 'nearest'});
}

function openPalette() {
  keysheet.hidden = true;
  palette.hidden = false;
  qbox.value = '';
  runSearch();
  qbox.focus();
}

function closeSheets() {
  palette.hidden = true;
  keysheet.hidden = true;
}

[palette, keysheet].forEach(sheet => sheet.addEventListener('click', ev => {
  if (ev.target === sheet) closeSheets();
}));

qbox.addEventListener('input', runSearch);
qbox.addEventListener('keydown', ev => {
  if (ev.key === 'ArrowDown') { ev.preventDefault(); at = Math.min(at + 1, hits.length - 1); mark(); }
  else if (ev.key === 'ArrowUp') { ev.preventDefault(); at = Math.max(at - 1, 0); mark(); }
  else if (ev.key === 'Enter' && hits[at]) { ev.preventDefault(); const it = hits[at]; closeSheets(); it.act(); }
});

document.addEventListener('keydown', ev => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if (ev.key === 'Escape') {
    if (!palette.hidden || !keysheet.hidden) closeSheets();
    else if (active) applyFilter(null);
    return;
  }
  if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  if (ev.key === '/') { ev.preventDefault(); openPalette(); }
  else if (ev.key === '?') { ev.preventDefault(); palette.hidden = true; keysheet.hidden = !keysheet.hidden; }
  else if (ev.key === 'j') { ev.preventDefault(); stepBlock(1); }
  else if (ev.key === 'k') { ev.preventDefault(); stepBlock(-1); }
});
"""


def ref_html(ref):
    """A defect points at the pull request carrying its fix, or at the branch.

    An unpushed branch has no URL, so it renders as a name. That is the point:
    a reader can see the fix exists and see that it is not somewhere they can
    fetch it from.
    """
    if ref is None:
        return ""
    if isinstance(ref, int):
        return (' <a class="ref" href="https://github.com/%s/pull/%d">#%d</a>'
                % (REPO, ref, ref))
    return ' <code class="branch">%s</code>' % e(ref)


def queue_html(rows, with_facts=False):
    out = []
    for r in rows:
        pr = ('<a class="ref" href="https://github.com/%s/pull/%d">#%d</a>'
              '<span class="pill %s">%s</span>' % (REPO, r["pr"], r["pr"],
                                                   r["state"], e(r["label"]))
              ) if r["pr"] else ""
        drift = ('<span class="pill closed">branch has moved on</span>'
                 if r["drifted"] else "")
        # Three states, not two. "local only" was being printed over a branch
        # the fork held in full, and nothing at all over one whose last three
        # commits existed on this disk and nowhere else.
        if r["pushed"]:
            where = ""
        elif not r["on_remote"]:
            where = '<span class="pill draft">local only</span>'
        else:
            where = ('<span class="pill draft">%d commit%s not pushed</span>'
                     % (r["unpushed"], "" if r["unpushed"] == 1 else "s"))
        blocked = ('<span class="dd blocked">%s</span>' % e(r["blocked"])) if r["blocked"] else ""
        note = ('<span class="dd">%s</span>' % e(r["note"])) if r["note"] else (
            '<span class="dd blocked">No intent recorded for this branch.</span>')
        out.append(
            '<li data-branch="%s"><div class="qhead"><code>%s</code><span class="ahead">%d commit%s</span>'
            '%s%s%s</div>%s%s%s</li>'
            % (e(r["branch"]), e(r["repo"] + " · " + r["branch"]), r["ahead"],
               "" if r["ahead"] == 1 else "s", pr, drift, where, note, blocked,
               facts_html(r) if with_facts else "")
        )
    return "".join(out)


def facts_html(r):
    """The evidence behind an unsent branch, folded away until asked for.

    Everything a pull request description would rest on, in one place, so the
    person writing it and a reviewer who goes looking are reading the same
    thing. Commits, diffstat and base are derived; the numbered evidence is
    written by hand and verified.
    """
    facts = FACTS.get(f"{r['repo']}:{r['branch']}")
    if not facts and not r.get("commits"):
        return ""
    rows = "".join(
        "<dt>%s</dt><dd>%s</dd>" % (e(head), e(body)) for head, body in (facts or [])
    )
    shown = r.get("commits", [])[:40]
    commits = "".join("<li>%s</li>" % e(c) for c in shown)
    if len(r.get("commits", [])) > len(shown):
        commits += ("<li class=\"more\">and %d more</li>"
                    % (len(r["commits"]) - len(shown)))
    base = ""
    if r.get("base"):
        behind = r.get("behind") or 0
        base = ("<p class=\"basis\">Cut from <code>%s</code> at <code>%s</code>%s%s</p>"
                % (e(r["base"]), e(r["base_sha"]),
                   ", %d commit%s behind" % (behind, "" if behind == 1 else "s")
                   if behind else "",
                   " &middot; " + e(r["stat"]) if r.get("stat") else ""))
    return (
        '<details class="facts"><summary>Evidence for a pull request '
        '&mdash; %d commit%s</summary>'
        '%s<dl>%s</dl><h4>Commits</h4><ol class="commitlist">%s</ol></details>'
        % (r["ahead"], "" if r["ahead"] == 1 else "s", base, rows, commits)
    )


CELL_WORD = {"driven": "a driver", "undriven": "no driver", "absent": "not on this chip"}

# Which block the trace opens on. Sorted order puts a flash pad controller
# first, which is a true row and a useless first impression -- the opening
# trace should be one with every rung filled in.
OPENS_ON = ("ADC", "SPI", "UART", "IO_BANK0")


def first_block(cov):
    names = [r["name"] for r in cov["rows"]]
    return next((n for n in OPENS_ON if n in names), names[0] if names else None)
COL_WORD = {"a": "RP2040", "b": "RP2350 upstream", "c": "RP2350 on this fork"}


def cov_html(cov, opening):
    """The coverage grid. One row per hardware block, three columns of state.

    The row is the control and the cells are decoration: a screen reader gets
    one sentence naming the block and all three states, rather than three
    unlabelled marks it has to re-associate with a column header.
    """
    out, group = [], None
    for r in cov["rows"]:
        if r["group"] != group:
            group = r["group"]
            out.append('<li class="cgroup"><span>%s</span></li>' % e(group))
        cells = "".join('<span class="cell c-%s" aria-hidden="true"></span>' % r[k]
                        for k in ("a", "b", "c"))
        says = "; ".join("%s %s" % (COL_WORD[k], CELL_WORD[r[k]]) for k in ("a", "b", "c"))
        by = ""
        if r["added_by"]:
            by = '<code class="branch">%s</code>' % e(r["added_by"])
        elif r["module"] and r["rp2350_fork"]:
            by = '<span class="up">upstream</span>'
        flag = '<span class="flag" aria-hidden="true">!</span>' if r["flag"] else ""
        out.append(
            '<li><button class="brow%s" data-block="%s" data-label="%s" aria-label="%s. %s.">'
            '<span class="bname">%s%s</span>%s<span class="bby">%s</span>'
            '</button></li>'
            % (" sel" if r["name"] == opening else "", e(r["name"]), e(r["label"]),
               e(r["label"]), e(says), e(r["label"]), flag, cells, by))
    return "".join(out)


def rung(name, value, empty=False):
    return ('<li%s><span class="rname">%s</span><span class="rval">%s</span></li>'
            % (' class="off"' if empty else "", e(name), value))



# --------------------------------------------------------------------------
# The queue, drawn
# --------------------------------------------------------------------------

# What has to land before what. Keyed by the thing that waits; the value is
# what it waits for, either another branch or a pull request number, and why.
# Hand-written because the coupling is a judgement about review order, not
# something the commits say -- and checked, so both ends must exist.
QUEUE_DEPS = {
    "libtock-rs:async/alarm": [
        ("libtock-rs:unittest-fakes",
         "The async tests call fake::Alarm::new_deferred and "
         "fake::Console::new_deferred, which are exactly what the unittest "
         "commits add. Either those land first, or this pull request carries "
         "them itself."),
    ],
    "libtock-rs:pico2-platform": [
        (5141, "The platform row names raspberry_pi_pico_2_w, which is this "
               "pull request and not upstream yet."),
    ],
    "libtock-rs:stepper": [
        ("tock:stepper-capsule",
         "The two halves of one feature. Neither is any use without the other, "
         "and the capsule is the larger ask because it needs a new driver "
         "number."),
    ],
}

STAGES = [
    ("fork", "On the fork", "finished, not proposed"),
    ("review", "In review", "waiting on a maintainer"),
    ("approved", "Approved", "waiting to be merged"),
    ("merged", "Merged", "upstream"),
    ("closed", "Closed", "withdrawn"),
]

QCARD_W, QCARD_H = 200, 62
QGAP_X, QGAP_Y = 18, 14
QPAD, QHEAD_H = 18, 42


def queue_cards(data, ready, in_review):
    """One card per thing in the queue, in the stage it is actually in.

    Branches that have no pull request come from the working clones; anything
    with one is represented by the pull request instead, so a branch in review
    is not counted twice.
    """
    by_pr = {r["pr"]: r for r in in_review if r["pr"]}
    cards = {stage: [] for stage, _, _ in STAGES}
    for r in ready:
        key = "%s:%s" % (r["repo"], r["branch"])
        cards["fork"].append({
            "id": "b:" + key, "key": key, "title": r["branch"],
            "meta": "%s · %d commit%s" % (r["repo"], r["ahead"],
                                          "" if r["ahead"] == 1 else "s"),
            "note": r["note"] or "", "blocked": r["blocked"] or "",
            "branch": r["branch"], "pr": None, "stat": r.get("stat", ""),
            "pushed": r["pushed"],
        })
    for pr in sorted(data["prs"], key=lambda p: -p["number"]):
        state = pr_state(pr)[0]
        stage = "review" if state in ("review", "draft") else state
        if stage not in cards:
            continue
        row = by_pr.get(pr["number"])
        key = ("%s:%s" % (row["repo"], row["branch"])) if row else "#%d" % pr["number"]
        cards[stage].append({
            "id": "p:%d" % pr["number"], "key": key, "title": pr["title"],
            "meta": "#%d · %d commit%s" % (pr["number"], len(pr["commits"]),
                                           "" if len(pr["commits"]) == 1 else "s"),
            "note": (row or {}).get("note", ""), "blocked": (row or {}).get("blocked") or "",
            "branch": (row or {}).get("branch"), "pr": pr["number"],
            "stat": "+%d / −%d over %d files" % (pr["additions"], pr["deletions"],
                                                 pr["changedFiles"]),
            "pushed": True,
        })
    return cards


def queue_svg(cards):
    """Stages left to right, one card per unit of work, arrows for what waits.

    The columns are deliberately not balanced. A pipeline whose first column is
    five times the height of the rest is the whole point of drawing it: the
    constraint is not how fast the work goes, it is how fast it is asked for.
    """
    where = {}
    for col, (stage, _, _) in enumerate(STAGES):
        x = QPAD + col * (QCARD_W + QGAP_X)
        for row, card in enumerate(cards[stage]):
            card["x"] = x
            card["y"] = QPAD + QHEAD_H + row * (QCARD_H + QGAP_Y)
            card["stage"] = stage
            where[card["key"]] = card
            if card["pr"]:
                where["#%d" % card["pr"]] = card

    tall = max(len(cards[s]) for s, _, _ in STAGES)
    width = QPAD * 2 + len(STAGES) * QCARD_W + (len(STAGES) - 1) * QGAP_X
    height = QPAD * 2 + QHEAD_H + tall * (QCARD_H + QGAP_Y) - QGAP_Y

    heads = []
    for col, (stage, label, sub) in enumerate(STAGES):
        x = QPAD + col * (QCARD_W + QGAP_X)
        heads.append(
            '<text class="qhname s-%s" x="%d" y="%d">%s</text>'
            '<text class="qhsub" x="%d" y="%d">%d — %s</text>'
            % (stage if stage != "fork" else "draft", x, QPAD + 16, e(label),
               x, QPAD + 32, len(cards[stage]), e(sub)))

    edges = []
    for waiter, deps in QUEUE_DEPS.items():
        target = where.get(waiter)
        if not target:
            continue
        for dep, _ in deps:
            source = where.get(dep if isinstance(dep, str) else "#%d" % dep)
            if not source:
                continue
            x1, y1 = source["x"] + QCARD_W, source["y"] + QCARD_H / 2
            x2, y2 = target["x"], target["y"] + QCARD_H / 2
            if source["stage"] == target["stage"]:      # same column, curve out
                x1, y1 = source["x"] + QCARD_W / 2, source["y"] + QCARD_H
                x2, y2 = target["x"] + QCARD_W / 2, target["y"]
                mid = (y1 + y2) / 2
                path = "M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" % (
                    x1, y1, x1, mid, x2, mid, x2, y2)
            else:
                mid = (x1 + x2) / 2
                path = "M%.0f,%.0f C%.0f,%.0f %.0f,%.0f %.0f,%.0f" % (
                    x1, y1, mid, y1, mid, y2, x2, y2)
            edges.append('<path class="qedge" d="%s" marker-end="url(#qarrow)"/>' % path)

    boxes = []
    for stage, _, _ in STAGES:
        for card in cards[stage]:
            lines = wrap(card["title"], 26, 2)
            tspans = "".join('<tspan x="%d" dy="%d">%s</tspan>'
                             % (card["x"] + 11, 0 if i == 0 else 14, e(line))
                             for i, line in enumerate(lines))
            waits = ' <tspan class="qwait">waiting</tspan>' if card["key"] in QUEUE_DEPS else ""
            boxes.append(
                '<g class="qcard st-%s" data-card="%s"%s%s tabindex="0" role="listitem" '
                'aria-label="%s. %s, %s.">'
                '<rect x="%d" y="%d" width="%d" height="%d" rx="7"/>'
                '<text class="qlabel" x="%d" y="%d">%s</text>'
                '<text class="qmeta" x="%d" y="%d">%s%s</text></g>'
                % (stage if stage != "fork" else "draft", e(card["id"]),
                   ' data-branch="%s"' % e(card["branch"]) if card["branch"] else "",
                   ' data-pr="%d"' % card["pr"] if card["pr"] else "",
                   e(card["title"]), e(card["meta"]),
                   e(dict((s, l) for s, l, _ in STAGES)[card["stage"]]),
                   card["x"], card["y"], QCARD_W, QCARD_H,
                   card["x"] + 11, card["y"] + 21, tspans,
                   card["x"] + 11, card["y"] + QCARD_H - 10, e(card["meta"]), waits))

    return ('<svg id="queuegraph" viewBox="0 0 %d %d" width="%d" height="%d" '
            'role="list" aria-label="The queue, one column per stage">'
            '<defs><marker id="qarrow" viewBox="0 0 8 8" refX="7" refY="4" '
            'markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M0,0 L8,4 L0,8 z" class="qhead"/></marker></defs>'
            '<g class="qheads">%s</g><g class="qedges">%s</g>%s</svg>'
            % (width, height, width, height, "".join(heads), "".join(edges),
               "".join(boxes)))

def bit_strip(width, fields):
    """One register drawn as its bits, high to low, gaps included.

    The gaps are the point as much as the fields are: a control register is
    mostly nothing, and a picture that packs the named fields together tells
    you the opposite of what the silicon does.
    """
    taken = {}
    for name, offset, count in fields:
        for bit in range(offset, min(offset + count, width)):
            taken[bit] = (name, offset, count)
    out, bit = [], width - 1
    while bit >= 0:
        here = taken.get(bit)
        if here:
            name, offset, count = here
            high, low, label = offset + count - 1, offset, name
        else:
            low = bit
            while low >= 0 and low not in taken:
                low -= 1
            low, high, label = low + 1, bit, ""
        span = "%d" % high if high == low else "%d:%d" % (high, low)
        out.append('<span class="bf%s" style="flex:%d"><b>%s</b>%s</span>'
                   % ("" if label else " gap", high - low + 1, span, e(label)))
        bit = low - 1
    return "".join(out)


def inside_html(block, trace):
    """The registers worth opening up, as tabs over bit strips."""
    inside = trace.get("inside") or []
    if not inside:
        return ""
    width = trace.get("bitwidth", 32)
    tabs, strips = [], []
    for i, reg in enumerate(inside):
        ident = "bf-%s-%s" % (block, reg["name"])
        tabs.append('<button class="rtab%s" data-panel="%s" aria-pressed="%s">'
                    '<code>%s</code><span class="dim">%s</span></button>'
                    % (" sel" if i == 0 else "", e(ident), "true" if i == 0 else "false",
                       e(reg["name"]), e(reg["offset"])))
        says = ", ".join(
            "%s at %s" % (name, offset if count == 1
                          else "%d to %d" % (offset + count - 1, offset))
            for name, offset, count in reg["fields"])
        strips.append('<div class="bits" id="%s"%s role="img" '
                      'aria-label="%s, %d bits: %s">%s</div>'
                      % (e(ident), "" if i == 0 else " hidden", e(reg["block"]),
                         width, e(says), bit_strip(width, reg["fields"])))
    return ('<div class="insides"><div class="rtabs">%s</div>%s</div>'
            % ("".join(tabs), "".join(strips)))


def trace_html(cov, traces, opening):
    """Every block's trace, in the markup, all but one hidden.

    Rendered rather than assembled in the browser so that the page still says
    what an ADC read touches with scripting off, and so that a browser's own
    find-in-page reaches a register name.
    """
    out = []
    for r in cov["rows"]:
        t = traces.get(r["name"]) or {}
        rows = []

        caps = t.get("capsules") or []
        for c in caps:
            boards = (" &middot; reachable on " +
                      ", ".join("<code>%s</code>" % e(b) for b in c["boards"])
                      ) if c["boards"] else " &middot; on no RP2 board"
            rows.append(rung("System call",
                             '<code class="num">%s</code> <code>%s</code>%s'
                             % (e(c["num"] or "?"), e(c["name"]), boards)))
            rows.append(rung("Capsule", "<code>%s</code>" % e(c["path"])))
        if not caps:
            rows.append(rung("System call", "no capsule sits above this block", True))

        impls = t.get("impls") or []
        if impls:
            rows.append(rung("Kernel interface",
                             " ".join("<code>kernel::hil::%s</code>" % e(x)
                                      for x in impls[:6])))
        else:
            rows.append(rung("Kernel interface",
                             "the driver implements no HIL trait, so nothing in "
                             "the kernel's device interface describes this block",
                             True))

        files = t.get("files") or []
        for f in files:
            rows.append(rung("Chip driver",
                             '<code>%s</code> <span class="dim">%d lines</span>'
                             % (e(f["path"]), f["lines"])))
        if not files:
            rows.append(rung("Chip driver",
                             "nothing in the tree drives this block on an RP2350", True))

        if t.get("bases"):
            rows.append(rung("Peripheral base",
                             " ".join('<code class="num">%s</code>' % e(b)
                                      for b in t["bases"])))
        regs = t.get("regs") or []
        if regs:
            strip = "".join('<span class="reg"><b>%s</b>%s</span>' % (e(off), e(name))
                            for off, name in regs)
            more = ('<span class="reg more">+%d</span>' % (t["nregs"] - len(regs))
                    ) if t["nregs"] > len(regs) else ""
            block = ('<span class="regblock"><code>%s</code></span>'
                     % e(t["regblock"])) if t.get("regblock") else ""
            rows.append(rung("Registers",
                             '%s<span class="regs">%s%s</span>' % (block, strip, more)))
        elif files:
            rows.append(rung("Registers", "no register block in these files", True))

        opened = inside_html(r["name"], t)
        if opened:
            rows.append(rung("Inside a register", opened))

        # The RP2040's driver, named as the RP2040's. For a block the RP2350
        # has and nothing drives, this is what would be ported.
        for f in t.get("older") or []:
            rows.append(rung("On the RP2040",
                             '<code>%s</code> <span class="dim">%d lines</span>'
                             % (e(f["path"]), f["lines"])))

        caveat = ""
        if r["caveat"]:
            caveat = ('<p class="tcaveat"><strong>Known defect.</strong> %s%s</p>'
                      % (e(r["caveat"][0]), ref_html(r["caveat"][1])))
        note = ""
        if not r["on"]["rp2350"]:
            note = ('<p class="tnote">The RP2350 does not have this block at all '
                    '&mdash; its reset controller names no bit for one.</p>')
        # The RP2350's names for it, or the RP2040's if only that chip has it.
        # Merging both printed "TIMER TIMER0 TIMER1", which reads as three.
        inst = " ".join(r["instances"].get("rp2350") or r["instances"].get("rp2040") or [])
        out.append(
            '<article class="trace" id="tr-%s"%s>'
            '<h3>%s <span class="binst">%s</span></h3>'
            '<p class="what">%s</p>%s%s<ol class="rungs">%s</ol></article>'
            % (e(r["name"]), "" if r["name"] == opening else " hidden",
               e(r["label"]), e(inst), e(r["what"]), note, caveat, "".join(rows)))
    return "".join(out)


def pin_state(entries):
    """What one pin is doing on one board, from what its board's source says.

    Order matters. A pin the kernel has taken for the console or the radio is
    not free just because it also appears, commented out, in the userspace
    table -- the comment is the board saying why the application cannot have
    it.
    """
    if not entries:
        return "free", "", []
    labels = []
    for entry in entries:
        if entry["label"] not in [l for l, _ in labels]:
            labels.append((entry["label"], entry["off"]))
    taken = [(l, o) for l, o in labels if not l.startswith("userspace gpio")]
    live = [(l, o) for l, o in taken if not o]
    if live:
        role, kind = PIN_ROLE.get(live[0][0], (live[0][0], "kernel"))
        return kind, role, [l for l, _ in labels]
    exposed = next((l for l, o in labels if l.startswith("userspace gpio") and not o), None)
    if exposed:
        return "user", "an app can drive it as " + exposed.replace("userspace ", ""), \
               [l for l, _ in labels]
    withheld = next((l for l, o in labels if o), None)
    if withheld:
        role, _ = PIN_ROLE.get(taken[0][0], ("", "")) if taken else ("", "")
        note = role or "taken out of the app's GPIO table"
        return "off", note, [l for l, _ in labels]
    return "free", "", [l for l, _ in labels]


PIN_KIND_WORD = {
    "user": "an application can drive it",
    "kernel": "the kernel has it",
    "radio": "the radio has it",
    "adc": "prepared as an analogue input",
    "off": "named by the board, not offered to applications",
    "free": "the board does not name it",
    "gnd": "ground", "power": "power", "ctrl": "board control",
}


def pin_row(physical, kind, name, board_pins, mirror):
    gp = int(name[2:]) if name.startswith("GP") else None
    role, note, raw = "", "", []
    if gp is None:
        state = kind
        note = PIN_KIND_WORD[kind]
    else:
        state, note, raw = pin_state(board_pins.get(str(gp)) or board_pins.get(gp) or [])
        note = note or PIN_KIND_WORD[state]
    return ('<li class="pin p-%s%s"><span class="pnum">%d</span>'
            '<span class="pname">%s</span><span class="prole">%s</span></li>'
            % (state, " mirror" if mirror else "", physical, e(name), e(note)))


def pins_html(data, opening_board):
    chip = data.get("chip") or {}
    if not chip.get("ok") or not chip.get("pins"):
        return "", ""
    refs = {"upstream": chip["upstream_ref"], "fork": chip["fork_ref"]}
    tabs, panels = [], []
    for board, which, label, sub in PIN_BOARDS:
        per_board = chip["pins"].get(refs[which], {})
        if board not in per_board:
            continue
        board_pins = per_board[board]
        left = "".join(pin_row(p, k, n, board_pins, False)
                       for p, k, n in HEADER if p <= 20)
        right = "".join(pin_row(p, k, n, board_pins, True)
                        for p, k, n in sorted(HEADER, reverse=True) if p > 20)
        off = []
        for gp in OFF_HEADER:
            state, note, _ = pin_state(board_pins.get(str(gp)) or board_pins.get(gp) or [])
            off.append('<li class="pin p-%s"><span class="pname">GP%d</span>'
                       '<span class="prole">%s</span></li>'
                       % (state, gp, e(note or PIN_KIND_WORD[state])))
        off = "".join(off)
        on = board == opening_board
        tabs.append('<button class="ptab%s" data-board="%s" aria-pressed="%s">'
                    '%s<em>%s</em></button>'
                    % (" sel" if on else "", e(board), "true" if on else "false",
                       e(label), e(sub)))
        panels.append(
            '<div class="pinmap" id="pm-%s"%s>'
            '<div class="header"><ol class="hcol">%s</ol><ol class="hcol">%s</ol></div>'
            '<h3 class="offh">Not brought out to the header</h3>'
            "<p class=\"lede\">Four of the chip's GPIOs are not on the forty pins. "
            'On a Pico 2 W they are the radio, which is why an application cannot '
            'have them and why the board has no fourth ADC channel.</p>'
            '<ul class="offpins">%s</ul></div>'
            % (e(board), "" if on else " hidden", left, right, off))
    return "".join(tabs), "".join(panels)

REACH_BOARDS = [
    ("raspberry_pi_pico_w", "upstream", "Pico W", "RP2040, upstream"),
    ("raspberry_pi_pico_2", "upstream", "Pico 2", "RP2350, upstream"),
    ("raspberry_pi_pico_2_w", "fork", "Pico 2 W", "RP2350, this fork"),
]


def reach_html(data):
    """What a process can actually call, per board, read from `with_driver`."""
    chip = data.get("chip") or {}
    if not chip.get("ok"):
        return "", []
    refs = {"upstream": chip["upstream_ref"], "fork": chip["fork_ref"]}
    per = {}
    for board, which, _, _ in REACH_BOARDS:
        per[board] = set(chip["boards"].get(refs[which], {}).get(board, []))
    nums, capsules = chip["driver_nums"], chip["capsules"]

    def num_of(cap):
        info = capsules.get(cap) or {}
        return nums.get(info.get("num_name", ""), "")

    every = sorted({c for v in per.values() for c in v},
                   key=lambda c: (num_of(c) or "zzz", c))
    rows = []
    for cap in every:
        cells = "".join('<span class="cell c-%s" aria-hidden="true"></span>'
                        % ("driven" if cap in per[b] else "undriven")
                        for b, _, _, _ in REACH_BOARDS)
        says = "; ".join("%s %s" % (label, "yes" if cap in per[b] else "no")
                         for b, _, label, _ in REACH_BOARDS)
        rows.append('<li><span class="brow flat" aria-label="%s: %s">'
                    '<span class="bname"><code>%s</code></span>%s'
                    '<span class="bby"><code class="num">%s</code></span></span></li>'
                    % (e(cap.rpartition("::")[2]), e(says),
                       e(cap.rpartition("::")[2]), cells, e(num_of(cap) or "?")))
    counts = [(label, sub, len(per[b])) for b, _, label, sub in REACH_BOARDS]
    return "".join(rows), counts





def pin_labels(data):
    """Every identifier the pin survey found beside a pin, across all boards."""
    chip = data.get("chip") or {}
    return {entry["label"]
            for per_board in (chip.get("pins") or {}).values()
            for entries in per_board.values()
            for bucket in entries.values() for entry in bucket}


def unnamed_pin_roles(data):
    """Identifiers found beside a pin that PIN_ROLE does not translate.

    A pin whose role is not in the table renders the raw identifier, which is
    honest but ugly, and means a board started using a pin for something this
    page cannot describe.
    """
    return {label for label in pin_labels(data)
            if not label.startswith("userspace gpio") and label not in PIN_ROLE}


def unannotated_blocks(data):
    """Blocks a reset controller names that BLOCKS does not describe."""
    chip = data.get("chip") or {}
    if not chip.get("ok"):
        return set()
    canon = block_names(chip["resets"])
    return {canon[bit] for bits in chip["resets"].values() for bit in bits
            if canon[bit] not in BLOCKS}


def unplaced_modules(data):
    """Driver modules that are neither a block's driver nor known plumbing.

    A module in neither table appears nowhere on the page. That is the failure
    this catches: work landing in the tree and the coverage grid not moving.
    """
    chip = data.get("chip") or {}
    if not chip.get("ok"):
        return set()
    return {m for per_crate in chip["modules"].values()
            for mods in per_crate.values() for m in mods
            if m not in MODULE_BLOCK and m not in PLUMBING}



def dangling_queue_deps(data):
    """Ends of QUEUE_DEPS that name nothing in the queue.

    A dependency whose branch has been renamed, merged or dropped simply does
    not draw its arrow. Nothing about the page looks wrong; the coupling just
    stops being stated, which is the opposite of what this table is for.
    """
    in_review, ready, _ = queue_groups(queue_rows(data))
    cards = queue_cards(data, ready, in_review)
    known = {c["key"] for group in cards.values() for c in group}
    known |= {"#%d" % c["pr"] for group in cards.values() for c in group if c["pr"]}
    missing = set()
    for waiter, deps in QUEUE_DEPS.items():
        if waiter not in known:
            missing.add(waiter)
        for dep, _ in deps:
            name = dep if isinstance(dep, str) else "#%d" % dep
            if name not in known:
                missing.add(name)
    return missing


def relations(data, cov):
    """Which branches and pull requests touch each hardware block.

    Derived from the file lists that are already fetched: a branch relates to a
    block when it changes one of that block's driver modules. So selecting the
    ADC lights the branch that ports it without anyone recording that it does.
    """
    chip = data.get("chip") or {}
    if not chip.get("ok") or not cov:
        return {}
    out = {}
    for row in cov["rows"]:
        mods = [m for m, blk in MODULE_BLOCK.items() if blk == row["name"]]
        paths = {"chips/%s/src/%s.rs" % (crate, m)
                 for crate in CHIP_CRATES for m in mods}
        branches = sorted(br for br, files in chip["touched"].items()
                          if paths & set(files))
        prs = sorted(p["number"] for p in data["prs"]
                     if paths & set(p.get("files") or []))
        if branches or prs:
            out[row["name"]] = {"branches": branches, "prs": prs}
    return out


def render(data):
    nodes, order, overlaps = build_graph(data)
    pr_by_num = {p["number"]: p for p in data["prs"]}
    graph = svg(nodes, order, pr_by_num)

    chips = []
    for pr in sorted(data["prs"], key=lambda p: -p["number"]):
        st, label = pr_state(pr)
        n = sum(1 for h in order if pr["number"] in nodes[h]["prs"])
        chips.append(
            '<button class="chip" aria-pressed="false" data-pr="%d">'
            '<span class="num">#%d</span><span class="ct">%d commit%s</span>'
            '%s<span class="pill %s">%s</span></button>'
            % (pr["number"], pr["number"], n, "" if n == 1 else "s",
               "".join('<span class="closes">closes #%d</span>' % c
                       for c in pr.get("closes", [])),
               st, e(label))
        )

    cards = []
    for pr in sorted(data["prs"], key=lambda p: -p["number"]):
        st, label = pr_state(pr)
        shared = sorted({p for h in order if pr["number"] in nodes[h]["prs"]
                         for p in nodes[h]["prs"] if p != pr["number"]})
        note = ""
        if shared:
            note = ('<p class="share">Shares commits with %s. Those are the base of '
                    'this stack and are already in review on their own — not a second '
                    'submission of the same work.</p>'
                    % ", ".join("#%d" % p for p in shared))
        date = (pr["mergedAt"] or pr["closedAt"] or pr["createdAt"])[:10]
        cards.append(
            '<article class="prcard" data-pr="%d"><div class="prhead">'
            '<a class="ref" href="%s">#%d</a><span class="pill %s">%s</span></div>'
            '<h3>%s</h3><div class="meta"><span>+%d / &minus;%d</span>'
            '<span>%d files</span><span>%s</span></div>%s</article>'
            % (pr["number"], e(pr["url"]), pr["number"], st, e(label), e(pr["title"]),
               pr["additions"], pr["deletions"], pr["changedFiles"], e(date), note)
        )

    rows = []
    for o in overlaps:
        shown = ", ".join("<code>%s</code>" % e(f) for f in o["files"][:3])
        more = (" and %d more" % (len(o["files"]) - 3)) if len(o["files"]) > 3 else ""
        rows.append("<li><strong>#%d and #%d</strong> both change %s%s — whichever "
                    "lands first, the other rebases.</li>"
                    % (o["a"], o["b"], shown, more))
    overlap_rows = "".join(rows) or "<li>No two open pull requests touch the same file.</li>"

    counts = {}
    for h in order:
        k = nodes[h]["verify"] or "none"
        counts[k] = counts.get(k, 0) + 1
    verify_rows = "".join(
        '<li><span class="badge v-%s">%s</span><span class="n">%d</span>'
        '<span>%s</span></li>' % (k, e(VERIFY[k][0]), counts.get(k, 0), e(VERIFY[k][1]))
        for k in ("host", "silicon", "sections", "build", "none")
    )

    defect_rows = "".join(
        '<li><span class="pill %s">%s</span><strong>%s</strong>%s'
        '<span class="dd">%s</span></li>'
        % (DEFECT_PILL[st][0], DEFECT_PILL[st][1], e(name),
           ref_html(ref), e(detail))
        for name, st, ref, detail in DEFECTS
    )
    fetched_findings = {i["number"]: i for i in data.get("findings", [])}
    finding_rows = "".join(
        '<li><span class="pill %s">%s</span>'
        '<strong><a href="findings/%s/">#%d &mdash; %s</a></strong>'
        '<span class="dd">%s</span>'
        '<span class="dd">Reported by %s. '
        '<a href="%s">The issue on GitHub</a>.</span></li>'
        % ("review" if fetched_findings.get(number, {}).get("state") == "OPEN"
           else "closed",
           e(fetched_findings.get(number, {}).get("state", "unknown").lower()),
           e(slug), number, e(title), e(blurb),
           e(fetched_findings.get(number, {}).get("author", {}).get("login", "?")),
           e(fetched_findings.get(number, {}).get(
               "url", "https://github.com/tock/tock/issues/%d" % number)))
        for number, slug, title, blurb in FINDINGS)
    silicon_rows = "".join("<li><strong>%s</strong><span class='dd'>%s</span></li>"
                           % (e(n), e(d)) for n, d in SILICON)
    downstream_rows = "".join(
        '<li><span class="pill %s">%s</span><strong>%s</strong>'
        '<span class="dd">%s</span></li>'
        % ("closed" if s == "blocked" else "draft", e(s), e(n), e(d))
        for n, s, d in DOWNSTREAM)
    not_done_rows = "".join("<li><strong>%s</strong><span class='dd'>%s</span></li>"
                            % (e(n), e(d)) for n, d in NOT_DONE)
    issue_rows = "".join('<li><a class="ref" href="%s">#%d</a> <strong>%s</strong></li>'
                         % (e(i["url"]), i["number"], e(i["title"]))
                         for i in data["issues"])

    merged = [p for p in data["prs"] if p["mergedAt"]]
    open_prs = [p for p in data["prs"] if p["state"] == "OPEN"]
    in_review, ready, never = queue_groups(queue_rows(data))
    ready_commits = sum(r["ahead"] for r in ready)

    node_json = json.dumps({
        n["id"]: {"head": n["head"], "short": n["short"], "note": n.get("note") or "",
                  "verify": VERIFY[n["verify"]][1] if n["verify"] else "",
                  "verifyLabel": VERIFY[n["verify"]][0] if n["verify"] else "",
                  "prs": sorted(n["prs"])}
        for n in nodes.values()
    })

    cov = coverage(data)
    tr = traces(data, cov) if cov else {}
    rel_json = json.dumps(relations(data, cov))
    qcards = queue_cards(data, ready, in_review)
    queue_json = json.dumps({
        c["id"]: {"title": c["title"], "meta": c["meta"], "note": c["note"],
                  "blocked": c["blocked"], "stat": c["stat"], "key": c["key"],
                  "waits": [w for _, w in QUEUE_DEPS.get(c["key"], [])]}
        for cards in qcards.values() for c in cards})
    reach_rows, reach_counts = reach_html(data)

    chip_nav, chip_sections = "", ""
    if cov:
        t = cov["totals"]
        opening = first_block(cov)
        ptabs, ppanels = pins_html(data, PIN_BOARDS[-1][0])
        pin_key = "".join(
            '<li><span class="pinswatch p-%s" aria-hidden="true"></span>%s</li>'
            % (k, e(v)) for k, v in (
                ("user", "an application can drive it"),
                ("kernel", "the kernel has taken it"),
                ("radio", "the radio has it"),
                ("adc", "an analogue input"),
                ("off", "named by the board, withheld from applications"),
                ("free", "the board does not name it")))
        legend = "".join(
            '<li><span class="cell c-%s" aria-hidden="true"></span>%s</li>' % (k, e(v))
            for k, v in (("driven", "a driver module covers it"),
                         ("undriven", "the block is there, nothing drives it"),
                         ("absent", "this chip does not have the block")))
        heads = "".join('<span class="chead">%s</span>' % e(h)
                        for h in ("RP2040", "RP2350", "fork"))
        plumb = ", ".join("<code>%s</code>" % e(m) for m, _ in cov["plumbing"])
        board_counts = "".join(
            '<li><span class="n">%d</span><span class="k">%s<em>%s</em></span></li>'
            % (n, e(label), e(sub)) for label, sub, n in reach_counts)
        reach_heads = "".join('<span class="chead">%s</span>' % e(label)
                              for _, _, label, _ in REACH_BOARDS)
        chip_sections = """
<section id="chip">
  <h2>What Tock can drive on this chip</h2>
  <p class="lede">The list of blocks is not kept here. Every chip crate has a
  <code>resets.rs</code> holding one bit per resettable hardware block, so the
  chip's own source says what it has &mdash; %(nb2350)d blocks on the RP2350,
  %(nb2040)d on the RP2040. A cell is filled when a driver module for that
  block exists in the crate. That is presence, not completeness: it says a
  driver is there, not that every feature of the block is reachable.</p>
  <ul class="counts">
    <li><span class="n">%(up2350)d</span><span class="k">driven upstream
      <em>of %(nb2350)d RP2350 blocks</em></span></li>
    <li><span class="n">%(fork2350)d</span><span class="k">driven on this fork
      <em>the bench kernel, everything merged</em></span></li>
    <li><span class="n">%(up2040)d</span><span class="k">driven on the RP2040
      <em>the older chip, better covered</em></span></li>
  </ul>
  <ul class="plain cellkey">%(legend)s</ul>
  <div class="covwrap">
    <div class="covhead"><span class="bname">Hardware block</span>%(heads)s
      <span class="bby">covered by</span></div>
    <ul class="cov">%(cov)s</ul>
  </div>
  <p class="hint">Click a block to trace it down to its registers. The
  <span class="flag" aria-hidden="true">!</span> marks a block with a defect
  found here.</p>
  <p class="foot">Read at <code>%(upref)s</code> (<code>%(head)s</code>) and
  <code>%(forkref)s</code>. Not shown because they are not blocks the reset
  controller names: %(plumb)s.</p>
</section>

<section id="trace">
  <h2>From a system call to a register</h2>
  <p class="lede">Every rung comes from the tree. The driver number from the one
  enum that assigns them, the capsule from the board's own <code>with_driver</code>,
  the kernel interface from what that capsule imports, the chip driver from the
  crate implementing it, and the registers from its <code>register_structs!</code>.
  A rung with no answer is a fact about the tree rather than a gap here.</p>
  <div class="traces">%(traces)s</div>
</section>

<section id="pins">
  <h2>The board in your hand</h2>
  <p class="lede">The forty pins, and what each one is doing on a kernel you
  can actually flash. The header's shape is the board's form factor; every
  role on it is read from that board's own source, so a pin the kernel has
  taken shows as taken and a pin an application can drive shows the number it
  drives it by. The Pico 2 W's map is the bench kernel: the display, the
  stepper and the radio are all on it.</p>
  <div class="ptabs">%(ptabs)s</div>
  <ul class="plain cellkey">%(pinkey)s</ul>
  %(ppanels)s
</section>

<section id="reach">
  <h2>What a process can actually call</h2>
  <p class="lede">Not what the kernel supports &mdash; what an application on
  each board can reach, read from every <code>with_driver</code> arm on it.
  A board can answer some driver numbers in its own file and pass the rest to a
  base platform in another crate, so both hops are followed &mdash; reading only
  the first reports one driver on a board that exposes ten.</p>
  <ul class="counts">%(bcounts)s</ul>
  <div class="covwrap">
    <div class="covhead"><span class="bname">Driver</span>%(rheads)s
      <span class="bby">number</span></div>
    <ul class="cov">%(reach)s</ul>
  </div>
</section>
""" % {
            "nb2350": t["blocks2350"], "nb2040": t["blocks2040"],
            "up2350": t["up2350"], "fork2350": t["fork2350"], "up2040": t["up2040"],
            "legend": legend, "heads": heads, "cov": cov_html(cov, opening),
            "traces": trace_html(cov, tr, opening), "plumb": plumb,
            "upref": e(cov["upstream_ref"]), "forkref": e(cov["fork_ref"]),
            "head": e(cov["head"]), "bcounts": board_counts,
            "rheads": reach_heads, "reach": reach_rows,
            "ptabs": ptabs, "ppanels": ppanels, "pinkey": pin_key,
        }
        chip_nav = (
            '<li class="navgroup">The chip</li>'
            '<li><a href="#chip">Coverage<span class="rn">%d of %d</span></a></li>'
            '<li><a href="#trace">Syscall to register<span class="rn">%d</span></a></li>'
            '<li><a href="#pins">The forty pins<span class="rn">%d</span></a></li>'
            '<li><a href="#reach">What a process calls<span class="rn">%d</span></a></li>'
            % (t["fork2350"], t["blocks2350"], len(cov["rows"]), len(HEADER),
               max((n for _, _, n in reach_counts), default=0)))

    nav = chip_nav + (
        '<li class="navgroup">The work</li>'
        '<li><a href="#stack">The stack<span class="rn">%d</span></a></li>'
        '<li><a href="#queue">The queue<span class="rn">%d</span></a></li>'
        '<li><a href="#collide">Collisions<span class="rn">%d</span></a></li>'
        '<li><a href="#prs">Pull requests<span class="rn">%d</span></a></li>'
        '<li class="navgroup">The evidence</li>'
        '<li><a href="#defects">Defects<span class="rn">%d</span></a></li>'
        '<li><a href="#findings">Findings<span class="rn">%d</span></a></li>'
        '<li><a href="#silicon">On silicon<span class="rn">%d</span></a></li>'
        '<li><a href="#plan">Test plan<span class="rn">%d</span></a></li>'
        '<li class="navgroup">Ahead</li>'
        '<li><a href="#course">The course<span class="rn">9</span></a></li>'
        '<li><a href="#downstream">Downstream<span class="rn">%d</span></a></li>'
        '<li><a href="#notdone">Not done<span class="rn">%d</span></a></li>'
        % (len(order), len(ready), len(overlaps), len(data["prs"]), len(DEFECTS),
           len(FINDINGS), len(SILICON), len(data["issues"]), len(DOWNSTREAM),
           len(NOT_DONE)))

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(tagline)s">
<style>%(css)s</style>
</head>
<body>
<a class="skip" href="#main">Skip to the page</a>
<div class="app">

<nav class="rail" aria-label="Sections">
  <a class="mark" href="#main"><b>Tock</b> on the RP2350</a>
  <ul>%(nav)s</ul>
  <p class="railkeys"><kbd>/</kbd> search &nbsp; <kbd>?</kbd> keys</p>
</nav>

<main id="main">
<div class="wrap">

<header>
  <h1>%(title)s</h1>
  <p class="tagline">%(tagline)s</p>
  <blockquote>%(quote)s
    <cite>&mdash; %(who)s, reviewing <a href="%(qurl)s">%(where)s</a></cite>
  </blockquote>
  %(answer)s
  <ul class="counts">
    <li><a href="#queue"><span class="n">%(nreview)d</span>
      <span class="k">in review</span></a></li>
    <li><a href="#queue"><span class="n">%(nready)d</span>
      <span class="k">finished, not sent &mdash; %(readyc)d commits</span></a></li>
    <li><a href="#defects"><span class="n">%(nfixed)d</span>
      <span class="k">defects with a fix written</span></a></li>
  </ul>
</header>
%(chipsections)s
<section id="stack">
  <h2>The stack</h2>
  <p class="lede">One column per pull request, %(nprs)d of them, holding all %(nnodes)d commits.
  Depth down a column is stack order: an arrow runs from each commit to the one that needs it
  first. A <strong>dashed box</strong> is a commit that belongs to two pull requests, and a
  <strong>dashed orange arrow</strong> is a dependency that crosses between columns &mdash; together
  those are the whole reason the same work appears twice on GitHub. The word at the bottom left
  of a box is how that change is verified.</p>
  <div class="chips">%(chips)s</div>
  <p class="hint">Click a pull request to light up exactly the commits it carries.
  Click a node for detail.</p>
  <div class="canvas">%(graph)s</div>
  <div class="readout">
    <div class="panel">
      <h3>How each change is verified</h3>
      <ul class="plain legend">%(verify)s</ul>
    </div>
    <div class="panel">
      <h3 id="d-title">Nothing selected</h3>
      <p id="d-note">Click any node in the graph.</p>
      <p class="head" id="d-head"></p>
    </div>
  </div>
</section>

<section id="queue">
  <h2>The queue</h2>
  %(policy)s
  <p class="lede">Read from the working clones, so it is what exists rather than what
  was last written down. A branch is matched to its pull request by which commits they
  share, not by name.</p>
  <div class="canvas">%(qgraph)s</div>
  <div class="readout">
    <div class="panel">
      <h3>What the columns mean</h3>
      <p>A unit of work moves left to right. The first column is not a backlog
      being worked through &mdash; everything in it is finished, demonstrated and
      pushed. It is waiting to be <em>asked for</em>, a few at a time, because
      the constraint upstream is review throughput. A dashed arrow is one piece
      of work that cannot go until another lands.</p>
    </div>
    <div class="panel">
      <h3 id="q-title">Nothing selected</h3>
      <p id="q-note">Click any card above.</p>
      <p class="head" id="q-meta"></p>
    </div>
  </div>
  <h3 class="qh">In review now &mdash; %(nreview)d</h3>
  <ul class="plain queue">%(qreview)s</ul>
  <h3 class="qh">Finished, not proposed yet &mdash; %(nready)d branches, %(readyc)d commits</h3>
  <ul class="plain queue">%(qready)s</ul>
  <h3 class="qh">Never going upstream &mdash; %(nnever)d</h3>
  <p class="lede">Bench harnesses and teaching material. Listed so that nobody browsing
  the fork has to guess which branches are waiting to be proposed.</p>
  <ul class="plain queue">%(qnever)s</ul>
</section>

<section id="collide">
  <h2>Where the open branches collide</h2>
  <p class="lede">Derived by comparing the file list of every open pull request against
  every other, so it cannot drift from what the branches do.</p>
  <ul class="plain">%(overlaps)s</ul>
</section>

<section id="prs">
  <h2>Pull requests</h2>
  <p class="lede">%(nmerged)d merged, %(nopen)d open.</p>
  <div class="prgrid">%(cards)s</div>
</section>

<section id="defects">
  <h2>Defects found</h2>
  <p class="lede">Each demonstrated before it was written down &mdash; by a test that fails
  without the fix, or by an instrumented kernel on a board. The UART pair needs no board
  at all: <code>make qemu-example EXAMPLE=console_read_busy</code> against libtock-rs's
  own pinned kernel prints <code>read -&gt; 0 bytes, Err(BUSY)</code> on an affected build,
  where a correct one would leave the read outstanding.</p>
  <ul class="plain">%(defects)s</ul>
</section>

<section id="findings">
  <h2>Findings</h2>
  <p class="lede">Open Pico issues somebody else reported, worked through far enough to
  be useful to whoever fixes them. Each page pins its citations to a commit, ships the
  script that produced any tool output it quotes, and ends with what it does
  <em>not</em> establish &mdash; which for the USB one is most of it.</p>
  <ul class="plain">%(findings)s</ul>
  <p class="foot">Written with AI assistance, disclosed on each page, which is also why
  the evidence is arranged to be checked rather than believed.</p>
</section>

<section id="silicon">
  <h2>Run on hardware</h2>
  <p class="lede">A Raspberry Pi flashes the board and holds its serial line, so the
  machine that builds never touches the hardware.</p>
  <ul class="plain">%(silicon)s</ul>
</section>

<section id="plan">
  <h2>Test plan</h2>
  <ul class="plain">%(issues)s</ul>
</section>

<section id="course">
  <h2>The course</h2>
  <p class="lede">Nine chapters on how the kernel works, written while learning
  it on this board and checked the same way this page is &mdash; every figure is
  something to drive rather than a picture to read, and every claim about the
  tree is verified against a commit the chapter names. It starts at what a
  register is and ends at grants.</p>
  <p><a class="bigref" href="read/">Read it &rarr;</a></p>
  <p class="foot">Its own gate runs 35 assertions on the cover and a suite per
  chapter. Sources are under <code>learning/</code>; <code>read/</code> is what
  is served, and a check here fails if the two disagree.</p>
</section>

<section id="downstream">
  <h2>Downstream</h2>
  <ul class="plain">%(downstream)s</ul>
</section>

<section id="notdone">
  <h2>Not done</h2>
  <ul class="plain">%(notdone)s</ul>
</section>

<footer>
  <p>Pull request state, sizes, dates, commit lists and file overlaps are read from the
  GitHub API when this page is built &mdash; current as of %(fetched)s. The graph's edges come
  from commit order inside each branch. Coverage, driver numbers and every rung of the
  trace are read from the Tock working clone at build time. Short labels and notes are
  written by hand.</p>
  <p><a href="https://github.com/%(author)s">%(author)s</a> &middot;
  <a href="https://github.com/%(repo)s">%(repo)s</a> &middot;
  <a href="https://github.com/tock/libtock-rs">tock/libtock-rs</a></p>
</footer>

</div>
</main>
</div>

<div class="sheet" id="keysheet" hidden role="dialog" aria-modal="true"
     aria-labelledby="keystitle">
  <div class="sheetbox">
    <h2 id="keystitle">Keys</h2>
    <dl class="keys">
      <dt><kbd>/</kbd></dt><dd>Search everything on the page</dd>
      <dt><kbd>?</kbd></dt><dd>This list</dd>
      <dt><kbd>j</kbd> <kbd>k</kbd></dt><dd>Next and previous hardware block</dd>
      <dt><kbd>Esc</kbd></dt><dd>Close, or clear the pull request filter</dd>
    </dl>
  </div>
</div>

<div class="sheet" id="palette" hidden role="dialog" aria-modal="true"
     aria-label="Search the page">
  <div class="sheetbox">
    <input id="q" type="search" autocomplete="off" spellcheck="false"
           placeholder="Blocks, pull requests, branches, commits, defects"
           aria-controls="presults" aria-describedby="phint">
    <p id="phint" class="phint">Type to search everything on this page. Enter jumps to it.</p>
    <ul id="presults" role="listbox" aria-label="Results"></ul>
  </div>
</div>

<script>%(js)s</script>
</body>
</html>
""" % {
        "title": e(SITE["title"]), "tagline": e(SITE["tagline"]),
        # `</` inside the JSON would close the script element early.
        "css": CSS,
        "js": (JS.replace("__NODES__", node_json.replace("</", "<\\/"))
                 .replace("__REL__", rel_json.replace("</", "<\\/"))
                 .replace("__QUEUE__", queue_json.replace("</", "<\\/"))),
        "quote": e(PROVOCATION["quote"]), "who": e(PROVOCATION["who"]),
        "where": e(PROVOCATION["where"]), "qurl": e(PROVOCATION["url"]),
        "answer": para(PROVOCATION["answer"]),
        "nprs": len(data["prs"]), "nnodes": len(order),
        "chips": "".join(chips), "graph": graph, "verify": verify_rows,
        "overlaps": overlap_rows, "cards": "".join(cards),
        "nmerged": len(merged), "nopen": len(open_prs),
        "defects": defect_rows, "findings": finding_rows,
        "silicon": silicon_rows, "issues": issue_rows,
        "policy": para(POLICY), "nreview": len(in_review), "nready": len(ready),
        "nfixed": len([d for d in DEFECTS if d[1] == "fixed-local"]),
        "nnever": len(never), "readyc": ready_commits,
        "qgraph": queue_svg(qcards),
        "qreview": queue_html(in_review),
        "qready": queue_html(ready, with_facts=True),
        "qnever": queue_html(never),
        "downstream": downstream_rows, "notdone": not_done_rows,
        "fetched": e(data["fetched"]), "author": AUTHOR, "repo": REPO,
        "nav": nav, "chipsections": chip_sections,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="rebuild from the cached data.json instead of fetching")
    args = parser.parse_args()

    cache = ROOT / "data.json"
    if args.offline:
        if not cache.exists():
            sys.exit("error: no data.json to build from; run once without --offline")
        data = json.loads(cache.read_text())
    else:
        data = fetch()
        cache.write_text(json.dumps(data, indent=2) + "\n")

    nodes, order, overlaps = build_graph(data)
    (ROOT / "index.html").write_text(render(data))
    print("wrote index.html — %d commits, %d pull requests, %d branch collisions, "
          "data from %s" % (len(order), len(data["prs"]), len(overlaps), data["fetched"]))
    missing = [h for h in order if h not in WORK]
    if missing:
        print("  no annotation in WORK (these still render, unlabelled):")
        for h in missing:
            print("    " + h)
    for name in sorted(unannotated_blocks(data)):
        print("  no annotation in BLOCKS: " + name)
    for name in sorted(unplaced_modules(data)):
        print("  module in no block and no PLUMBING: " + name)
    for name in sorted(unnamed_pin_roles(data)):
        print("  no entry in PIN_ROLE, renders raw: " + name)


if __name__ == "__main__":
    main()
