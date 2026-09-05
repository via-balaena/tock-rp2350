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
    "tock:rp2-pad-controls": ("upstream", "Shared pad enums and the RP2350 pad controls.", None),
    "tock:pico2w-typed": ("upstream", "The Pico 2 W board and the radio.", None),
    "tock:rp2-pio-tests": ("upstream", "Five PIO fixes and the driver's first host tests.", None),
    "tock:boards-fix-ram-layout": ("upstream", "Merged.", None),
    "tock:boards-remove-dead-ram-layout": ("upstream", "Closed in favour of fixing the addresses.", None),
    "tock:rp2-uart-abort-fix": ("upstream", "The fix for all three UART defects: the abort ordering in the three chip drivers, and the two buffer-ownership bugs in the mux. Three commits, each building standalone, no size change on any board.", "Verified by A/B under QEMU on the pinned hifive1 kernel — Err(BUSY) without it, the read left outstanding with it, and 16 bytes typed completing it Ok. Waiting only on a pull request description."),
    "tock:rp2350-spi-bench": ("never", "A bench harness that drives the SPI loopback.", None),
    "tock:pico2w-radio-bench": ("never", "Every commit titled NOT FOR UPSTREAM: it starts the radio from the board so a scan can be driven without an app.", None),
    "tock:bench/reclaim-leak-demo": ("never", "Reproduces the GPIO reclaim leak on a board.", None),
    "tock:learning/series": ("never", "Nine chapters on how the kernel works, plus the tooling that builds them.", None),
    "tock:master": ("never", "Tracking branch.", None),
    "libtock-rs:pico2-platform": ("upstream", "Load addresses for the Pico 2 and Pico 2 W, and a build error that named neither the platform nor the file to edit.", "Ready now, and independent of the async work."),
    "libtock-rs:async/alarm": ("upstream", "Futures over the alarm and console drivers, a single-task executor, select, and fakes that model cancellation. Meant to become two pull requests, but it is not two branches yet: the two unittest commits sit inside this one and have to be lifted out first.", "Hard order, not a preference. The async tests call fake::Alarm::new_deferred and fake::Console::new_deferred in three places, and those constructors are exactly what the unittest commits add — so either the unittest fixes land first and the async work builds on them, or the async pull request carries both commits itself. It cannot go first and cannot go alone."),
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
}

# Real dependencies the API cannot see, because they cross pull requests.
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
    ("UART: an aborted receive tears down every other receive", "fixed-local", None,
     "The abort completion calls the client back before marking the receiver idle, so the multiplexer's restart is refused and it ends every device's receive instead. The same code is in three chip drivers, and eleven boards pair a process console with the userspace console on one multiplexer. Reproducible under QEMU with no hardware, on hifive1, at the eighteen-month-old revision libtock-rs already pins — and no application can avoid it. Removing the delay before the read, and then issuing the read before any other system call, both still fail: the process console's prompt prints before the application's first line, so the receive is already armed before the application's first instruction. \u201cThe app read too early\u201d is not an available explanation. What the reproduction still lacks is the opposite control, a kernel with no process console on that multiplexer, which is a board change rather than an application one."),
    ("UART: a failed receive hands back the wrong static buffer", "fixed-local", None,
     "A virtual device propagates the multiplexer's error with `?`, and that error carries the multiplexer's buffer rather than the caller's. Two static buffers change owners and the multiplexer's slot is left empty for the life of the board."),
    ("UART: the teardown drops a buffer it cannot deliver", "fixed-local", None,
     "When a restart fails the mux takes every device's buffer, but only returns it to devices still in the Receiving state — so a device that had aborted a read loses its buffer permanently. Found while fixing the two above."),
    ("A stopped process never gets its GPIO reclaimed", "unfiled", None,
     "The pin stays driven forever. A sibling capsule already has the fix, which makes this a consistency bug. Five of forty-five capsules are affected."),
    ("`make program` cannot flash an app on the Pico 2", "unfiled", None,
     "The objcopy step gives the stack segment a file size it should not have; picotool then refuses the image and leaves a zero-byte UF2 behind."),
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


def survey_local():
    """Branches in each local clone, how far ahead they are, and their commits."""
    out = {}
    for name, (path, base) in LOCAL.items():
        if not path.exists():
            continue
        refs = git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        if refs is None:
            continue
        branches = {}
        for branch in refs.splitlines():
            log = git(path, "log", "--format=%s", f"{base}..{branch}")
            if log is None:
                continue
            commits = [l for l in log.splitlines() if l]
            branches[branch] = {
                "ahead": len(commits),
                "commits": commits,
                "pushed": git(path, "rev-parse", "--verify", "-q",
                              f"origin/{branch}") is not None,
            }
        out[name] = branches
    return out


def fetch():
    # Commits and files are fetched per pull request: asking for them across a
    # 100-item list exceeds GitHub's GraphQL node budget and the whole query is
    # refused.
    prs = gh_json([
        "pr", "list", "--repo", REPO, "--author", AUTHOR, "--state", "all",
        "--limit", "100", "--json",
        "number,title,state,isDraft,createdAt,mergedAt,closedAt,additions,"
        "deletions,changedFiles,url,reviewDecision",
    ])
    for pr in prs:
        detail = gh_json(["pr", "view", str(pr["number"]), "--repo", REPO,
                          "--json", "commits,files"])
        pr["commits"] = [{"messageHeadline": c["messageHeadline"]}
                         for c in detail["commits"]]
        pr["files"] = sorted(f["path"] for f in detail["files"])
    issues = gh_json([
        "issue", "list", "--repo", REPO, "--author", AUTHOR, "--state", "all",
        "--limit", "100", "--json", "number,title,state,createdAt,url",
    ])
    return {
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "prs": sorted(prs, key=lambda p: p["number"]),
        "issues": sorted(issues, key=lambda i: i["number"]),
        "local": survey_local(),
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
                "pushed": info["pushed"], "intent": intent, "note": note,
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
--host:#1d4b7a;--silicon:#7a3b12;--sections:#46561f;--build:#5b5c62;--none:#636469;}
@media (prefers-color-scheme:dark){:root{
--bg:#131316;--panel:#1b1c20;--ink:#edecea;--ink-soft:#b6b6ba;--ink-faint:#8e8f95;
--line:#2c2d33;--accent:#d9a273;--edge:#42444c;
--merged-bg:#1d3324;--merged-ink:#8fd3a0;--merged-line:#4a8a5e;
--review-bg:#1b2c3f;--review-ink:#8fbde8;--review-line:#4574a0;
--approved-bg:#2a3119;--approved-ink:#b9cd88;--approved-line:#728848;
--draft-bg:#26272c;--draft-ink:#a9aab0;--draft-line:#5d5e65;
--closed-bg:#3a2222;--closed-ink:#e29a9a;--closed-line:#8a5252;
--unfiled-bg:#3a2f1a;--unfiled-ink:#e3bd7c;
--host:#8fbde8;--silicon:#e0a874;--sections:#b9cd88;--build:#a9aab0;--none:#9a9ba1;}}
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
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}
.chip{display:flex;align-items:center;gap:9px;padding:7px 12px 7px 13px;border-radius:999px;
border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;font:inherit;font-size:.84rem}
.chip:hover{border-color:var(--accent)}
.chip .num{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;color:var(--accent)}
.chip .ct{color:var(--ink-faint);font-size:.78rem}
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
"""


def queue_html(rows):
    out = []
    for r in rows:
        pr = ('<a class="ref" href="https://github.com/%s/pull/%d">#%d</a>'
              '<span class="pill %s">%s</span>' % (REPO, r["pr"], r["pr"],
                                                   r["state"], e(r["label"]))
              ) if r["pr"] else ""
        drift = ('<span class="pill closed">branch has moved on</span>'
                 if r["drifted"] else "")
        where = "" if r["pushed"] else '<span class="pill draft">local only</span>'
        blocked = ('<span class="dd blocked">%s</span>' % e(r["blocked"])) if r["blocked"] else ""
        note = ('<span class="dd">%s</span>' % e(r["note"])) if r["note"] else (
            '<span class="dd blocked">No intent recorded for this branch.</span>')
        out.append(
            '<li><div class="qhead"><code>%s</code><span class="ahead">%d commit%s</span>'
            '%s%s%s</div>%s%s</li>'
            % (e(r["repo"] + " · " + r["branch"]), r["ahead"],
               "" if r["ahead"] == 1 else "s", pr, drift, where, note, blocked)
        )
    return "".join(out)


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
            '<span class="pill %s">%s</span></button>'
            % (pr["number"], pr["number"], n, "" if n == 1 else "s", st, e(label))
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
           (' <a class="ref" href="https://github.com/%s/pull/%d">#%d</a>'
            % (REPO, ref, ref)) if ref else "",
           e(detail))
        for name, st, ref, detail in DEFECTS
    )
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

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>%(title)s</title>
<meta name="description" content="%(tagline)s">
<style>%(css)s</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>%(title)s</h1>
  <p class="tagline">%(tagline)s</p>
  <blockquote>%(quote)s
    <cite>— %(who)s, reviewing <a href="%(qurl)s">%(where)s</a></cite>
  </blockquote>
  %(answer)s
</header>

<section>
  <h2>The stack</h2>
  <p class="lede">One column per pull request, %(nprs)d of them, holding all %(nnodes)d commits.
  Depth down a column is stack order: an arrow runs from each commit to the one that needs it
  first. A <strong>dashed box</strong> is a commit that belongs to two pull requests, and a
  <strong>dashed orange arrow</strong> is a dependency that crosses between columns — together
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

<section>
  <h2>The queue</h2>
  %(policy)s
  <p class="lede">Read from the working clones, so it is what exists rather than what
  was last written down. A branch is matched to its pull request by which commits they
  share, not by name.</p>
  <h3 class="qh">In review now — %(nreview)d</h3>
  <ul class="plain queue">%(qreview)s</ul>
  <h3 class="qh">Finished, not proposed yet — %(nready)d branches, %(readyc)d commits</h3>
  <ul class="plain queue">%(qready)s</ul>
  <h3 class="qh">Never going upstream — %(nnever)d</h3>
  <p class="lede">Bench harnesses and teaching material. Listed so that nobody browsing
  the fork has to guess which branches are waiting to be proposed.</p>
  <ul class="plain queue">%(qnever)s</ul>
</section>

<section>
  <h2>Where the open branches collide</h2>
  <p class="lede">Derived by comparing the file list of every open pull request against
  every other, so it cannot drift from what the branches do.</p>
  <ul class="plain">%(overlaps)s</ul>
</section>

<section>
  <h2>Pull requests</h2>
  <p class="lede">%(nmerged)d merged, %(nopen)d open.</p>
  <div class="prgrid">%(cards)s</div>
</section>

<section>
  <h2>Defects found</h2>
  <p class="lede">Each demonstrated before it was written down — by a test that fails
  without the fix, or by an instrumented kernel on a board. The UART pair needs no board
  at all: <code>make qemu-example EXAMPLE=console_read_busy</code> against libtock-rs's
  own pinned kernel prints <code>read -&gt; 0 bytes, Err(BUSY)</code> on an affected build,
  where a correct one would leave the read outstanding.</p>
  <ul class="plain">%(defects)s</ul>
</section>

<section>
  <h2>Run on hardware</h2>
  <p class="lede">A Raspberry Pi flashes the board and holds its serial line, so the
  machine that builds never touches the hardware.</p>
  <ul class="plain">%(silicon)s</ul>
</section>

<section>
  <h2>Test plan</h2>
  <ul class="plain">%(issues)s</ul>
</section>

<section>
  <h2>Downstream</h2>
  <ul class="plain">%(downstream)s</ul>
</section>

<section>
  <h2>Not done</h2>
  <ul class="plain">%(notdone)s</ul>
</section>

<footer>
  <p>Pull request state, sizes, dates, commit lists and file overlaps are read from the
  GitHub API when this page is built — current as of %(fetched)s. The graph's edges come
  from commit order inside each branch. Short labels and notes are written by hand.</p>
  <p><a href="https://github.com/%(author)s">%(author)s</a> ·
  <a href="https://github.com/%(repo)s">%(repo)s</a> ·
  <a href="https://github.com/tock/libtock-rs">tock/libtock-rs</a></p>
</footer>

</div>
<script>%(js)s</script>
</body>
</html>
""" % {
        "title": e(SITE["title"]), "tagline": e(SITE["tagline"]),
        # `</` inside the JSON would close the script element early.
        "css": CSS, "js": JS.replace("__NODES__", node_json.replace("</", "<\\/")),
        "quote": e(PROVOCATION["quote"]), "who": e(PROVOCATION["who"]),
        "where": e(PROVOCATION["where"]), "qurl": e(PROVOCATION["url"]),
        "answer": para(PROVOCATION["answer"]),
        "nprs": len(data["prs"]), "nnodes": len(order),
        "chips": "".join(chips), "graph": graph, "verify": verify_rows,
        "overlaps": overlap_rows, "cards": "".join(cards),
        "nmerged": len(merged), "nopen": len(open_prs),
        "defects": defect_rows, "silicon": silicon_rows, "issues": issue_rows,
        "policy": para(POLICY), "nreview": len(in_review), "nready": len(ready),
        "nnever": len(never), "readyc": ready_commits,
        "qreview": queue_html(in_review), "qready": queue_html(ready),
        "qnever": queue_html(never),
        "downstream": downstream_rows, "notdone": not_done_rows,
        "fetched": e(data["fetched"]), "author": AUTHOR, "repo": REPO,
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


if __name__ == "__main__":
    main()
