#!/usr/bin/env python3
"""Build index.html for the Tock/RP2350 work map.

Every number on the page comes from the GitHub API at build time rather than
from a hand-kept list, because a hand-kept list goes stale silently and this
page exists to be trusted. Prose lives in CONTENT below; status, sizes, dates
and review state are fetched.

    ./build.py            # fetch and write index.html
    ./build.py --offline  # rebuild from the cached data.json, no network

Requires the `gh` CLI, authenticated.
"""

import argparse
import html
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).parent
REPO = "tock/tock"
AUTHOR = "bigmark222"

# --------------------------------------------------------------------------
# Prose. Everything here is written by hand; everything else is fetched.
# --------------------------------------------------------------------------

SITE = {
    "title": "Tock on the RP2350",
    "tagline": "Bringing the Raspberry Pi Pico 2 and Pico 2 W up on the Tock embedded kernel — what has landed, what is open, what is broken.",
    "intro": """
The RP2350 is the chip in the Raspberry Pi Pico 2. Tock has booted on it since
April 2025, but booting was most of what it did: the chip had no SPI, no PIO
and no DMA driver, the Pico 2 W's radio had no support at all, and several
things that looked finished turned out not to work when a board was put in
front of them.

This page maps the work closing that gap. It is one contributor's queue, not a
roadmap for the project, and it is deliberately honest about the parts that are
unfinished, unfiled or wrong — a map that only showed the wins would not be
worth reading.
""",
    "method": """
Two rules produce most of what is here. Every claim about hardware is made
against hardware, on a bench where a Raspberry Pi flashes the board and holds
its serial line so the development machine never touches it. And every defect
is demonstrated before it is reported — by a failing test where a test can
reach it, and by an instrumented kernel on silicon where it cannot.
""",
}

# Per-PR prose, keyed by number. `what` is the change; `why` is the reason it
# matters to somebody who does not already know the codebase.
PR_NOTES = {
    5086: {
        "what": "The Pico 2 board declared a fraction of the RAM the chip has.",
        "why": "One constant, and the smallest possible first contribution — which is the point. It established that the patches were real before anything large was proposed.",
    },
    5109: {
        "what": "Gave the board's boot-from-RAM memory layout addresses that actually link.",
        "why": "Booting a kernel into RAM instead of flash saves the flash write on every iteration. The layout had been in the tree for a while and could not have worked.",
    },
    5104: {
        "what": "Proposed deleting the boot-from-RAM layout as dead code.",
        "why": "Closed, and correctly. A maintainer pointed out that the Pico can boot from RAM and the addresses should be fixed rather than the feature removed. That became #5109, which merged. Worth leaving on the map: the first instinct was wrong and the review caught it.",
    },
    5112: {
        "what": "Moved the RP2040's PL022 SPI driver into a crate both chips share, then added SPI to the RP2350.",
        "why": "The two chips carry the same SPI block. Sharing the driver rather than copying it is the pattern the rest of this work follows — and the shared crate it created, rp2xxx, is where PIO and DMA later went.",
    },
    5126: {
        "what": "Removed a module of PIO example programs that nothing called.",
        "why": "Dead API in a driver is a liability: it constrains every later change while proving nothing. Clearing it first made the PIO work that follows much smaller.",
    },
    5140: {
        "what": "Shared the GPIO pad-control enums between the chips and gave the RP2350 the pad controls the RP2040 already had.",
        "why": "Drive strength, slew rate and Schmitt trigger. The radio's SPI bus needs them, and the RP2350 side simply did not exist.",
    },
    5141: {
        "what": "The Pico 2 W: PIO and DMA for the RP2350, the gSPI driver moved into the shared crate, the board split into a library and a binary, and the CYW43439 radio brought up on top.",
        "why": "The largest piece of the work and the one everything else was for. On silicon the board reads its MAC out of the radio's OTP and completes a scan — which means the firmware uploaded over a PIO state machine and a DMA channel, on a chip that had neither before this series.",
    },
    5150: {
        "what": "Five defects in the RP2040 PIO driver, and the first host tests that driver has ever had.",
        "why": "Each fix ships with a test that fails without it. The driver had no tests at all, so the bugs below had nothing to catch them.",
    },
}

ISSUE_NOTES = {
    5152: {
        "what": "A test plan for the RP2 PIO driver, in three tiers.",
        "why": "Answering a maintainer's question about how this code gets tested. Tier one is host tests and is done; tier two is six hardware tests, each of which stands alone; tier three is the project's hardware CI, named as a dependency rather than promised.",
    },
}

# Defects found. `status` is one of: fixed-pr, unfiled, reported.
DEFECTS = [
    {
        "name": "PIO: the RX FIFO join never happened",
        "status": "fixed-pr",
        "where": "chips/rp2040/src/pio.rs",
        "detail": "Joining the two four-word FIFOs into one eight-word RX FIFO silently did nothing, so a program that relied on the depth would drop words.",
        "evidence": "Host test that fails without the fix.",
        "ref": 5150,
    },
    {
        "name": "PIO: add_program panicked on half its own range",
        "status": "fixed-pr",
        "where": "chips/rp2040/src/pio.rs",
        "detail": "Loading a program into the upper half of instruction memory panicked the kernel rather than returning an error.",
        "evidence": "Host test that fails without the fix.",
        "ref": 5150,
    },
    {
        "name": "PIO: only one interrupt line of four was serviced",
        "status": "fixed-pr",
        "where": "chips/rp2040/src/pio.rs",
        "detail": "Three of the four state machines could raise an interrupt that nothing handled.",
        "evidence": "Host test that fails without the fix.",
        "ref": 5150,
    },
    {
        "name": "PIO: an interrupt flag was scoped to a state machine, not the block",
        "status": "fixed-pr",
        "where": "chips/rp2040/src/pio.rs",
        "detail": "The hardware flag belongs to the PIO block; treating it as per-state-machine mis-attributes interrupts.",
        "evidence": "Host test that fails without the fix.",
        "ref": 5150,
    },
    {
        "name": "PIO: arithmetic with no other check",
        "status": "fixed-pr",
        "where": "chips/rp2040/src/pio.rs",
        "detail": "Clock divider and FIFO address arithmetic that nothing in the tree exercised.",
        "evidence": "Tests added; no behaviour change.",
        "ref": 5150,
    },
    {
        "name": "UART: an aborted receive tears down every other receive on the mux",
        "status": "unfiled",
        "where": "chips/rp2040, chips/rp2350, chips/sifive — uart.rs",
        "detail": (
            "The abort completion calls the client back and only then marks the "
            "receiver idle. The UART multiplexer always restarts its read from "
            "inside that callback, so the restart is refused as BUSY and the mux "
            "responds by ending every device's receive. The three chip drivers "
            "carry the block character for character."
        ),
        "evidence": "Demonstrated on silicon with an instrumented kernel, September 2026.",
        "ref": None,
    },
    {
        "name": "UART: a failed receive hands back the wrong static buffer",
        "status": "unfiled",
        "where": "capsules/core/src/virtualizers/virtual_uart.rs",
        "detail": (
            "A virtual device propagates the multiplexer's error with `?`, and that "
            "error carries a buffer — the multiplexer's, not the caller's. The device "
            "keeps the caller's buffer and the caller is handed the multiplexer's. "
            "Two static buffers change owners silently, and the multiplexer's slot is "
            "left empty for the life of the board. No process memory is involved, but "
            "the console is wedged from then on."
        ),
        "evidence": "Demonstrated on silicon; the swapped buffer is visible in the trace.",
        "ref": None,
    },
    {
        "name": "A stopped process never gets its GPIO reclaimed",
        "status": "unfiled",
        "where": "capsules/extra/src/pwm.rs and four others",
        "detail": (
            "When a process dies, the capsule does not release the pin it was driving, "
            "so the pin stays driven for the life of the board. A sibling capsule, "
            "adc.rs, already has the fix, which makes this a consistency bug rather "
            "than a design question. Five of forty-five capsules are affected."
        ),
        "evidence": "Demonstrated on silicon.",
        "ref": None,
    },
    {
        "name": "`make program` cannot flash an app on the Pico 2 boards",
        "status": "unfiled",
        "where": "boards/raspberry_pi_pico_2/Makefile",
        "detail": (
            "The objcopy step marks the app section loadable, which rewrites the "
            "program headers and gives the stack segment a file size it should not "
            "have. picotool then refuses the image, exits non-zero and leaves a "
            "zero-byte UF2 behind."
        ),
        "evidence": "Reproducible on a laptop with no board attached.",
        "ref": None,
    },
]

# Hardware results — things that have run on real silicon.
SILICON = [
    ("Pico 2 W scans WiFi", "The radio's firmware uploads over a PIO state machine and a DMA channel, the MAC reads out of the radio's OTP, and a scan completes. End-to-end validation of the whole #5141 stack."),
    ("SPI loopback", "The RP2350 SPI driver added in #5112, driven from a test app and read back over the bench."),
    ("Two co-resident apps", "Applications load, run and print on a Pico 2 W, which is what makes any userspace claim below checkable."),
    ("Async sleep and cancellation", "A 500 ms await measures within a few hundred microseconds of its deadline across every run, including immediately after a cancelled five-second sleep — which distinguishes a working cancellation from both a leaked callback and a timer left armed."),
    ("PIO and DMA register readback", "The one chip-specific constant in the series that no unit test can reach — the PIO interrupt block's offset — checked by reading the registers over the debug port."),
]

USERSPACE = {
    "summary": (
        "A Future and executor layer over Tock's syscalls, built in libtock-rs so an "
        "application can await a sleep or a console read instead of hand-rolling a "
        "callback. Validated on a Pico 2 W running the Pico 2 W kernel. Not yet "
        "proposed upstream."
    ),
    "items": [
        ("Async stack", "done", "Futures over the alarm and console drivers, a single-task executor with block_on, and select. Alarm side validated on silicon."),
        ("Platform rows for Pico 2 and Pico 2 W", "done", "libtock-rs hardcodes each board's app load addresses; neither board had an entry. The Pico 2 W's differ because the radio's firmware blobs push the app region up."),
        ("A build error that named nothing", "done", "Registering a platform requires three files that do not know about each other, and missing the third failed with a message that named neither the platform nor the file. It names both now."),
        ("Console concurrency", "blocked", "Cannot be tested until the UART receive defect above is fixed. The failure is in the kernel, not in the futures."),
        ("embedded-hal-async implementations", "planned", "The reason to do any of this: drivers written against those traits — hundreds of sensor, display and radio crates — would run unmodified inside a Tock process."),
    ],
}

DOCS = {
    "summary": (
        "Tock's book has no Pico coverage at all, which is a strange gap for one of "
        "the cheapest boards it supports."
    ),
    "items": [
        ("A Pico 2 getting-started page for the Tock book", "ready", "Written and pushed; the pull request is not open yet."),
        ("A nine-chapter series on how the kernel works", "drafted", "From what a register is through grants and the memory protection unit, each chapter interactive rather than prose. Written while learning the codebase, on the theory that the questions a newcomer has are only legible while they still have them."),
    ],
}

NOT_DONE = [
    ("Report the four unfiled defects", "Each is demonstrated and none is filed. The constraint is review throughput, not the work — an open pull request that nobody has time to read helps no one."),
    ("Fix the reclaim leak in pwm.rs", "The sibling capsule already shows what the fix looks like."),
    ("A userspace driver for PIO", "PIO is the RP2's most distinctive peripheral and no process can reach it."),
    ("Hardware CI for the RP2 boards", "The project's testbed runs one board and never on pull requests. Named as a dependency in the test plan rather than promised."),
    ("Get the Pico 2 W board reviewed", "38 files and 4,400 added lines is a large thing to ask anyone to read, which is the price of shipping a board and its radio together."),
]


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def gh_json(args):
    try:
        out = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=True
        ).stdout
    except FileNotFoundError:
        sys.exit("error: the gh CLI is not installed")
    except subprocess.CalledProcessError as err:
        sys.exit(f"error: gh failed: {err.stderr.strip()}")
    return json.loads(out)


def fetch():
    # Commits are fetched per pull request rather than in the list query: asking
    # for them across a 100-item list exceeds GitHub's GraphQL node budget and
    # the whole query is refused.
    prs = gh_json([
        "pr", "list", "--repo", REPO, "--author", AUTHOR, "--state", "all",
        "--limit", "100", "--json",
        "number,title,state,isDraft,createdAt,mergedAt,closedAt,additions,"
        "deletions,changedFiles,url,reviewDecision",
    ])
    for pr in prs:
        detail = gh_json([
            "pr", "view", str(pr["number"]), "--repo", REPO, "--json", "commits",
        ])
        pr["commits"] = [
            {"messageHeadline": c["messageHeadline"]} for c in detail["commits"]
        ]
    issues = gh_json([
        "issue", "list", "--repo", REPO, "--author", AUTHOR, "--state", "all",
        "--limit", "100", "--json", "number,title,state,createdAt,url",
    ])
    return {
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "prs": sorted(prs, key=lambda p: p["number"]),
        "issues": sorted(issues, key=lambda i: i["number"]),
    }


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

def pr_status(pr):
    """Return (slug, label) for a pull request's real state."""
    if pr["mergedAt"]:
        return "merged", "merged"
    if pr["state"] == "CLOSED":
        return "closed", "closed"
    if pr["isDraft"]:
        return "draft", "draft"
    if pr.get("reviewDecision") == "APPROVED":
        return "approved", "approved"
    return "open", "in review"


def e(text):
    return html.escape(str(text))


def para(text):
    """Turn a blank-line-separated block into paragraphs."""
    blocks = [b.strip().replace("\n", " ") for b in text.strip().split("\n\n")]
    return "\n".join(f"<p>{e(b)}</p>" for b in blocks if b)


def render_pr(pr):
    slug, label = pr_status(pr)
    note = PR_NOTES.get(pr["number"], {})
    date = (pr["mergedAt"] or pr["closedAt"] or pr["createdAt"])[:10]
    commits = "".join(
        f"<li>{e(c['messageHeadline'])}</li>" for c in pr.get("commits", [])
    )
    commit_block = (
        f"<details><summary>{len(pr.get('commits', []))} commits</summary>"
        f"<ul class='commits'>{commits}</ul></details>"
        if len(pr.get("commits", [])) > 1
        else ""
    )
    return f"""
    <article class="card">
      <div class="card-head">
        <a class="ref" href="{e(pr['url'])}">#{pr['number']}</a>
        <span class="pill {slug}">{e(label)}</span>
      </div>
      <h3>{e(pr['title'])}</h3>
      {f"<p>{e(note['what'])}</p>" if note.get('what') else ''}
      {f"<p class='why'>{e(note['why'])}</p>" if note.get('why') else ''}
      <div class="meta">
        <span>+{pr['additions']} / &minus;{pr['deletions']}</span>
        <span>{pr['changedFiles']} files</span>
        <span>{e(date)}</span>
      </div>
      {commit_block}
    </article>"""


def render_issue(issue):
    note = ISSUE_NOTES.get(issue["number"], {})
    slug = "merged" if issue["state"] == "CLOSED" else "open"
    label = "closed" if issue["state"] == "CLOSED" else "open"
    return f"""
    <article class="card">
      <div class="card-head">
        <a class="ref" href="{e(issue['url'])}">#{issue['number']}</a>
        <span class="pill {slug}">{e(label)}</span>
      </div>
      <h3>{e(issue['title'])}</h3>
      {f"<p>{e(note['what'])}</p>" if note.get('what') else ''}
      {f"<p class='why'>{e(note['why'])}</p>" if note.get('why') else ''}
      <div class="meta"><span>{e(issue['createdAt'][:10])}</span></div>
    </article>"""


DEFECT_LABEL = {
    "fixed-pr": ("fixed", "fix proposed"),
    "unfiled": ("unfiled", "not filed"),
    "reported": ("open", "reported"),
}


def render_defect(d):
    slug, label = DEFECT_LABEL[d["status"]]
    ref = (
        f"<a class='ref' href='https://github.com/{REPO}/pull/{d['ref']}'>#{d['ref']}</a>"
        if d["ref"]
        else "<span class='ref muted'>—</span>"
    )
    return f"""
    <article class="card">
      <div class="card-head">{ref}<span class="pill {slug}">{e(label)}</span></div>
      <h3>{e(d['name'])}</h3>
      <p>{e(d['detail'])}</p>
      <div class="meta">
        <span class="mono">{e(d['where'])}</span>
        <span>{e(d['evidence'])}</span>
      </div>
    </article>"""


STATE_LABEL = {
    "done": ("merged", "working"),
    "blocked": ("closed", "blocked"),
    "planned": ("draft", "planned"),
    "ready": ("approved", "ready"),
    "drafted": ("draft", "drafted"),
}


def render_item(name, state, detail):
    slug, label = STATE_LABEL[state]
    return f"""
    <article class="card">
      <div class="card-head"><span class="pill {slug}">{e(label)}</span></div>
      <h3>{e(name)}</h3>
      <p>{e(detail)}</p>
    </article>"""


def render(data):
    prs = data["prs"]
    issues = data["issues"]
    merged = [p for p in prs if p["mergedAt"]]
    open_prs = [p for p in prs if p["state"] == "OPEN"]
    closed = [p for p in prs if p["state"] == "CLOSED" and not p["mergedAt"]]
    added = sum(p["additions"] for p in prs)
    removed = sum(p["deletions"] for p in prs)
    unfiled = len([d for d in DEFECTS if d["status"] == "unfiled"])

    pr_cards = "".join(render_pr(p) for p in sorted(prs, key=lambda p: -p["number"]))
    issue_cards = "".join(render_issue(i) for i in issues)
    defect_cards = "".join(render_defect(d) for d in DEFECTS)
    userspace_cards = "".join(render_item(*i) for i in USERSPACE["items"])
    docs_cards = "".join(render_item(n, s, d) for n, s, d in DOCS["items"])
    silicon_rows = "".join(
        f"<li><strong>{e(n)}</strong> {e(d)}</li>" for n, d in SILICON
    )
    not_done_rows = "".join(
        f"<li><strong>{e(n)}</strong> {e(d)}</li>" for n, d in NOT_DONE
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(SITE['title'])}</title>
<meta name="description" content="{e(SITE['tagline'])}">
<style>
:root {{
  --bg: #fbfaf8;
  --panel: #ffffff;
  --ink: #16171a;
  --ink-soft: #56585e;
  --ink-faint: #6f7278;  /* 4.82:1 on the card, 4.62:1 on the page ground */
  --line: #e4e2dd;
  --accent: #7a4b1e;
  --merged-bg: #e3f0e4; --merged-ink: #1f5b2b;
  --open-bg: #e2ecf7; --open-ink: #1d4b7a;
  --draft-bg: #eceaea; --draft-ink: #55565b;
  --closed-bg: #f6e3e3; --closed-ink: #86282a;
  --unfiled-bg: #f8ecd8; --unfiled-ink: #7c5310;
  --approved-bg: #e7ecda; --approved-ink: #4a5c23;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #131316;
    --panel: #1b1c20;
    --ink: #edecea;
    --ink-soft: #b0b0b4;
    --ink-faint: #85868b;
    --line: #2c2d33;
    --accent: #d9a273;
    --merged-bg: #1d3324; --merged-ink: #8fd3a0;
    --open-bg: #1b2c3f; --open-ink: #8fbde8;
    --draft-bg: #26272c; --draft-ink: #a9aab0;
    --closed-bg: #3a2222; --closed-ink: #e29a9a;
    --unfiled-bg: #3a2f1a; --unfiled-ink: #e3bd7c;
    --approved-bg: #2a3119; --approved-ink: #b9cd88;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 1080px; margin: 0 auto; padding: 0 24px 96px; }}
header {{ padding: 72px 0 40px; border-bottom: 1px solid var(--line); }}
h1 {{ font-size: 2.6rem; line-height: 1.1; margin: 0 0 12px; letter-spacing: -0.02em; }}
.tagline {{ font-size: 1.15rem; color: var(--ink-soft); margin: 0 0 28px; max-width: 62ch; }}
header p {{ max-width: 68ch; color: var(--ink-soft); }}
header p:first-of-type {{ color: var(--ink); }}
.stats {{ display: flex; flex-wrap: wrap; gap: 28px; margin: 32px 0 0; padding: 0; list-style: none; }}
.stats li {{ min-width: 84px; }}
.stats .n {{ display: block; font-size: 1.9rem; font-weight: 600; letter-spacing: -0.02em; }}
.stats .k {{ display: block; font-size: 0.78rem; text-transform: uppercase;
  letter-spacing: 0.07em; color: var(--ink-faint); }}
section {{ padding: 56px 0 0; }}
h2 {{ font-size: 1.5rem; margin: 0 0 6px; letter-spacing: -0.01em; }}
.lede {{ color: var(--ink-soft); max-width: 68ch; margin: 0 0 24px; }}
.grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }}
.card {{
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 18px 18px 16px;
}}
.card-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }}
.card h3 {{ font-size: 1rem; margin: 0 0 8px; line-height: 1.4; }}
.card p {{ margin: 0 0 8px; font-size: 0.92rem; color: var(--ink-soft); }}
.card p.why {{ color: var(--ink-faint); }}
.ref {{ font: 600 0.85rem/1 ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--accent); text-decoration: none; }}
.ref:hover {{ text-decoration: underline; }}
.ref.muted {{ color: var(--ink-faint); }}
.pill {{
  font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; padding: 3px 9px; border-radius: 999px; white-space: nowrap;
}}
.pill.merged {{ background: var(--merged-bg); color: var(--merged-ink); }}
.pill.open {{ background: var(--open-bg); color: var(--open-ink); }}
.pill.approved {{ background: var(--approved-bg); color: var(--approved-ink); }}
.pill.draft {{ background: var(--draft-bg); color: var(--draft-ink); }}
.pill.closed {{ background: var(--closed-bg); color: var(--closed-ink); }}
.pill.unfiled {{ background: var(--unfiled-bg); color: var(--unfiled-ink); }}
.pill.fixed {{ background: var(--merged-bg); color: var(--merged-ink); }}
.meta {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.78rem; color: var(--ink-faint); margin-top: 10px; }}
.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.74rem; }}
details {{ margin-top: 10px; }}
summary {{ cursor: pointer; font-size: 0.8rem; color: var(--ink-faint); }}
ul.commits {{ margin: 8px 0 0; padding-left: 18px; font-size: 0.82rem; color: var(--ink-soft); }}
ul.commits li {{ margin: 3px 0; }}
ul.plain {{ list-style: none; padding: 0; margin: 0; }}
ul.plain li {{
  padding: 14px 0; border-top: 1px solid var(--line); color: var(--ink-soft);
  font-size: 0.94rem; max-width: 76ch;
}}
ul.plain li strong {{ color: var(--ink); display: block; margin-bottom: 2px; font-weight: 600; }}
h3.sub {{ margin: 32px 0 4px; font-size: 1.05rem; }}
footer {{ margin-top: 72px; padding-top: 24px; border-top: 1px solid var(--line);
  color: var(--ink-faint); font-size: 0.85rem; }}
footer a {{ color: var(--accent); }}
@media (max-width: 640px) {{
  h1 {{ font-size: 2rem; }}
  header {{ padding-top: 48px; }}
  .grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>{e(SITE['title'])}</h1>
  <p class="tagline">{e(SITE['tagline'])}</p>
  {para(SITE['intro'])}
  {para(SITE['method'])}
  <ul class="stats">
    <li><span class="n">{len(merged)}</span><span class="k">merged</span></li>
    <li><span class="n">{len(open_prs)}</span><span class="k">open</span></li>
    <li><span class="n">{len(closed)}</span><span class="k">closed</span></li>
    <li><span class="n">{added:,}</span><span class="k">lines added</span></li>
    <li><span class="n">{removed:,}</span><span class="k">lines removed</span></li>
    <li><span class="n">{len(DEFECTS)}</span><span class="k">defects found</span></li>
  </ul>
</header>

<section id="kernel">
  <h2>Kernel: chip and board support</h2>
  <p class="lede">Pull requests against tock/tock, newest first.</p>
  <div class="grid">{pr_cards}</div>
</section>

<section id="defects">
  <h2>Defects found</h2>
  <p class="lede">Every one of these was demonstrated before it was written down —
  by a test that fails without the fix, or by an instrumented kernel on real
  silicon. {unfiled} are not yet filed upstream.</p>
  <div class="grid">{defect_cards}</div>
</section>

<section id="testing">
  <h2>Testing</h2>
  <p class="lede">The RP2 drivers had no tests. Adding them is most of why the
  defects above were findable.</p>
  <div class="grid">{issue_cards}</div>
  <h3 class="sub">What has run on hardware</h3>
  <ul class="plain">{silicon_rows}</ul>
</section>

<section id="userspace">
  <h2>Userspace: async applications</h2>
  <p class="lede">{e(USERSPACE['summary'])}</p>
  <div class="grid">{userspace_cards}</div>
</section>

<section id="docs">
  <h2>Documentation</h2>
  <p class="lede">{e(DOCS['summary'])}</p>
  <div class="grid">{docs_cards}</div>
</section>

<section id="next">
  <h2>Not done</h2>
  <p class="lede">The honest half of the map.</p>
  <ul class="plain">{not_done_rows}</ul>
</section>

<footer>
  <p>Status, sizes and dates on this page are read from the GitHub API when it is
  built, so they are current as of {e(data['fetched'])}. Everything else is
  written by hand.</p>
  <p>Work by <a href="https://github.com/{AUTHOR}">{AUTHOR}</a> ·
  <a href="https://github.com/{REPO}">tock/tock</a> ·
  <a href="https://github.com/tock/libtock-rs">tock/libtock-rs</a></p>
</footer>

</div>
</body>
</html>
"""


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

    (ROOT / "index.html").write_text(render(data))
    print(f"wrote index.html — {len(data['prs'])} pull requests, "
          f"{len(data['issues'])} issues, data from {data['fetched']}")


if __name__ == "__main__":
    main()
