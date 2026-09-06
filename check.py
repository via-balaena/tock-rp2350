#!/usr/bin/env python3
"""Check that the published page is still true, still current and still legible.

Eighteen checks, and a nineteenth that runs when node and jsdom are there. Each one exists because it has already caught something, or because
it guards a mistake that was actually made here:

  drift       index.html is not what build.py would produce from data.json,
              so either it was hand-edited or somebody forgot to rebuild.
  fresh       the cached data disagrees with GitHub right now. This is the one
              that matters: a merged pull request still shown as open is the
              page lying.
  annotated   a commit is on the page with no label or verification badge.
  intent      a local branch is in the queue with no recorded intent, so a
              reader cannot tell whether it is waiting to be proposed.
  facts       a branch is finished and unsent with no evidence recorded, so
              the dropdown a reviewer opens would be empty.
  refs        a "#1234" written by hand in the prose names a pull request or
              issue that does not exist. A typo here is invisible on the page.
  private     an address, MAC, serial path or home directory reached the HTML.
  contrast    a text-on-surface pair fell below 4.5:1. Two colours have already
              shipped below it, both found this way and neither by looking.
  blocks      a hardware block or a driver module reached the tree and did not
              reach the page. The quiet half: a module in neither table is
              simply absent from the coverage grid, so a port could land and
              the page would go on reporting the old number.
  nav         a rail link points at a section that is not there, or a section
              is not in the rail. Invisible to everything else: the page still
              builds and the link just does nothing.
  grid        a coverage row carries the wrong number of cells. It does not
              look broken; it shifts every later cell one column left.
  trace       a block has no trace panel, or more than one is visible at rest,
              which is what a reader with no JavaScript would be shown.
  styles      a class in the markup that no rule matches, or a rule no markup
              uses. Both have shipped here: the first renders a page that is
              not the designed one, the second is a highlight that was never
              once drawn.
  pins        a pin used for something PIN_ROLE cannot name, or a name no
              board uses any more; and the tabs and maps agreeing.
  header      the forty-pin table is internally consistent. A typo, not a
              pinout: nothing here can tell you the pinout is right.
  bits        a register drawn as bits that does not add up to the register's
              width. The strips stretch to fill the row, so a mis-read field
              still looks like a register -- only the sum shows it.
  queue       the drawn queue and the written queue disagreeing: a stage
              heading counting something other than what is under it, a card
              matching nothing on the page, or a QUEUE_DEPS end that names
              nothing so its arrow is silently not drawn.
  interactions  the page driven in a real DOM: every block opening its own
              trace, the keys, the search, the pull request filter. Optional,
              and skipped rather than failed when node or jsdom is missing.

    ./check.py            # everything, including a live fetch
    ./check.py --offline  # skip the live fetch

Exit 0 clean, 1 problems found, 2 could not run.
"""

import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent

# Text colour and the surfaces it is drawn on. Semantic pairing cannot be
# inferred from CSS, so it is stated here and checked against the real values.
PAIRS = [
    ("ink", ["bg", "panel"]),
    ("ink-soft", ["bg", "panel"]),
    ("ink-faint", ["bg", "panel"]),
    ("accent", ["bg", "panel"]),
    ("merged-ink", ["merged-bg"]),
    ("review-ink", ["review-bg"]),
    ("approved-ink", ["approved-bg"]),
    ("draft-ink", ["draft-bg"]),
    ("closed-ink", ["closed-bg"]),
    ("unfiled-ink", ["unfiled-bg"]),
    ("ink", ["draft-bg"]),          # the branch chip on defect rows
    # Stage headings on the queue graph and lane headings on the stack graph,
    # both drawn straight onto the panel the canvas sits on.
    ("merged-ink", ["panel"]), ("review-ink", ["panel"]),
    ("approved-ink", ["panel"]), ("draft-ink", ["panel"]),
    ("closed-ink", ["panel"]),
    # The coverage grid's three cell states, drawn on the panel the grid sits on.
    ("driven", ["panel", "bg"]),
    ("undriven", ["panel", "bg"]),
    ("absent", ["panel", "bg"]),
    # Verification badges sit on whichever node fill the commit's state gives it.
    ("host", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("silicon", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("sections", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("build", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
    ("none", ["merged-bg", "review-bg", "approved-bg", "draft-bg", "closed-bg", "panel"]),
]
MIN_RATIO = 4.5

PRIVATE = [
    (r"\b192\.168\.\d+\.\d+\b", "a private IP address"),
    (r"\b10\.\d+\.\d+\.\d+\b", "a private IP address"),
    (r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", "a MAC address"),
    (r"/dev/tty\w+", "a serial device path"),
    (r"/dev/serial\d", "a serial device path"),
    (r"/(?:home|Users)/\w+", "a home directory"),
    (r"\braspberrypi\b", "the bench hostname"),
]


def load_build():
    spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def luminance(hexcolor):
    h = hexcolor.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def palettes(css):
    """Return {theme: {var: hex}} for the light root and the dark override."""
    blocks = re.findall(r":root\{(.*?)\}", css, re.S)
    if len(blocks) < 2:
        return {}
    def parse(block):
        found = {}
        for name, value in re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{3,6})\b", block):
            if len(value) == 4:                 # #fff is #ffffff
                value = "#" + "".join(ch * 2 for ch in value[1:])
            if len(value) == 7:
                found[name] = value
        return found
    light = parse(blocks[0])
    dark = dict(light)
    dark.update(parse(blocks[1]))
    return {"light": light, "dark": dark}


def check_contrast(build, problems):
    css_palettes = palettes(build.CSS)
    if not css_palettes:
        problems.append("contrast: could not parse the palette out of CSS")
        return
    for theme, colors in css_palettes.items():
        for ink, surfaces in PAIRS:
            if ink not in colors:
                problems.append(f"contrast: --{ink} is not defined")
                continue
            for surface in surfaces:
                if surface not in colors:
                    problems.append(
                        f"contrast: {theme}, --{surface} could not be read out of "
                        f"the palette, so --{ink} on it was never checked")
                    continue
                ratio = contrast(colors[ink], colors[surface])
                if ratio < MIN_RATIO:
                    problems.append(
                        f"contrast: {theme}, --{ink} on --{surface} is "
                        f"{ratio:.2f}:1, below {MIN_RATIO}"
                    )


def check_private(html, problems):
    for pattern, what in PRIVATE:
        for hit in set(re.findall(pattern, html)):
            problems.append(f"private: the page contains {what}: {hit!r}")


def check_refs(build, data, problems):
    known = {p["number"] for p in data["prs"]} | {i["number"] for i in data["issues"]}
    prose = [build.PROVOCATION["answer"], build.PROVOCATION["where"]]
    prose += [v.get("note", "") for v in build.WORK.values()]
    prose += [d[3] for d in build.DEFECTS] + [d[2] for d in build.DOWNSTREAM]
    prose += [n[1] for n in build.NOT_DONE] + [s[1] for s in build.SILICON]
    prose += [body for bullets in build.FACTS.values() for _, body in bullets]
    prose += [text for text, _ in build.BLOCK_CAVEAT.values()]
    prose += [ref for _, ref in build.BLOCK_CAVEAT.values() if isinstance(ref, int)]
    prose += [what for _, _, _, what in build.BLOCKS.values()]
    for text in prose:
        for num in re.findall(r"#(\d{4,5})", str(text)):
            if int(num) not in known:
                problems.append(
                    f"refs: prose mentions #{num}, which is not a pull request "
                    f"or issue in the fetched data"
                )


def check_annotated(build, data, problems):
    _, order, _ = build.build_graph(data)
    for head in order:
        if head not in build.WORK:
            problems.append(f"annotated: no label or badge for {head!r}")


def check_intent(build, data, problems):
    for repo, branches in data.get("local", {}).items():
        for branch, info in branches.items():
            key = f"{repo}:{branch}"
            if key not in build.INTENT:
                problems.append(
                    f"intent: {key} is {info['ahead']} commits ahead and has no "
                    f"entry in INTENT, so the queue cannot say what it is for"
                )


def check_facts(build, data, problems):
    _, ready, _ = build.queue_groups(build.queue_rows(data))
    for r in ready:
        key = f"{r['repo']}:{r['branch']}"
        if key not in build.FACTS:
            problems.append(
                f"facts: {key} is finished and unsent with no entry in FACTS, "
                f"so its evidence dropdown would be empty"
            )



def check_blocks(build, data, problems):
    """Nothing in the chip crates may reach the tree without reaching the page.

    Two ways it could: a reset controller naming a block this table has never
    heard of, and a driver module belonging to no block and not listed as
    plumbing. The second is the quiet one -- such a module is simply absent
    from the coverage grid, so a port could land upstream and the page would go
    on reporting the old number.
    """
    for name in sorted(build.unannotated_blocks(data)):
        problems.append(
            f"blocks: a reset controller names {name!r} and BLOCKS does not "
            f"say what it is, so it renders unlabelled")
    for name in sorted(build.unplaced_modules(data)):
        problems.append(
            f"blocks: the driver module {name!r} is in neither MODULE_BLOCK nor "
            f"PLUMBING, so it appears nowhere on the page")


def check_nav(build, html, problems):
    """Every rail link lands somewhere, and every section is reachable from it.

    A dead nav link is invisible to every other check here: the page builds,
    the HTML is well formed, and the link simply does nothing.
    """
    ids = set(re.findall(r'id="([^"]+)"', html))
    rail = re.search(r'<nav class="rail".*?</nav>', html, re.S)
    if not rail:
        problems.append("nav: the page has no rail")
        return
    targets = set(re.findall(r'href="#([^"]+)"', rail.group(0)))
    for target in sorted(targets):
        if target not in ids:
            problems.append(f"nav: the rail links to #{target}, which is not on the page")
    for section in sorted(re.findall(r'<section id="([^"]+)"', html)):
        if section not in targets:
            problems.append(f"nav: section #{section} is on the page and not in the rail")


def check_grid(build, html, problems):
    """The coverage grid's shape, which is the one thing here nobody can see.

    Both grids are laid out by a CSS `grid-template-columns` with a fixed
    number of tracks. A row carrying the wrong number of cells does not fail
    to render -- it silently shifts every cell after it into the wrong column,
    which is a page that lies rather than a page that looks broken.
    """
    heads = re.findall(r'<div class="covhead">(.*?)</div>', html, re.S)
    if not heads:
        problems.append("grid: no coverage grid on the page")
        return
    for i, head in enumerate(heads):
        n = head.count('class="chead"')
        if n != 3:
            problems.append(f"grid: grid {i} has {n} column headings, expected 3")
    # To the end of the list item, not to the first closing tag: a row's own
    # spans are nested inside it, so a non-greedy match on </span> stops at the
    # block name and reports every row as carrying no cells at all.
    for row in re.findall(r'class="brow[^"]*"(.*?)</li>', html, re.S):
        n = row.count('class="cell')
        if n != 3:
            problems.append(f"grid: a row carries {n} cells, expected 3")
            break


def check_trace(build, html, problems):
    """Every block has a trace, and exactly one of them is showing.

    The panels are rendered into the markup and hidden with the `hidden`
    attribute, so with scripting off the page shows whichever is left visible.
    Two visible is a stack of overlapping panels; none is a section that
    silently renders empty for a reader with no JavaScript.
    """
    blocks = set(re.findall(r'data-block="([^"]+)"', html))
    traces = dict(re.findall(r'<article class="trace" id="tr-([^"]+)"( hidden)?>', html))
    for name in sorted(blocks - set(traces)):
        problems.append(f"trace: block {name!r} has a row and no trace panel")
    for name in sorted(set(traces) - blocks):
        problems.append(f"trace: trace panel {name!r} has no row to open it")
    shown = [n for n, h in traces.items() if not h]
    if traces and len(shown) != 1:
        problems.append(
            f"trace: {len(shown)} trace panels are visible at rest, expected 1")


# Classes the script adds or removes at runtime, so they are legitimately in
# the stylesheet and absent from the built HTML.
RUNTIME_CLASSES = {"on", "here", "rel", "lit", "filtered", "kind"}

# Grouping wrappers in the generated SVG. They organise the markup and are
# deliberately not styling hooks, so they have no rules and are not dead.
STRUCTURAL_CLASSES = {"lanes", "laneheads", "edges", "qheads", "qedges"}


def check_styles(build, html, problems):
    """Every class in the markup has a rule, and every rule has markup.

    Both halves have already shipped here. A class with no rule is invisible
    to every other check -- the page renders, just not as designed. A rule with
    no class is a figure that was meant to mark something and never did: the
    race diagram carried a `.step.lost` rule for weeks and nothing ever set it,
    so the failure it existed to show was never once drawn.
    """
    used = set()
    for attr in re.findall(r'class="([^"]*)"', html):
        used |= set(attr.split())
    defined = set()
    for selector in re.findall(r"([^{}]+)\{[^{}]*\}", build.CSS):
        if selector.lstrip().startswith("@"):
            continue
        defined |= set(re.findall(r"\.(-?[A-Za-z_][\w-]*)", selector))
    for name in sorted(used - defined - RUNTIME_CLASSES - STRUCTURAL_CLASSES):
        problems.append(f"styles: the markup uses class {name!r} and no rule matches it")
    for name in sorted(defined - used - RUNTIME_CLASSES - STRUCTURAL_CLASSES):
        problems.append(f"styles: the stylesheet has a rule for {name!r} and no markup uses it")


def check_interactions(problems):
    """Run the page in a DOM and assert its interactions actually work.

    Everything else here reads the HTML as text. This runs the script the way
    a browser would. It is optional because it needs node and jsdom, and it is
    reported as skipped rather than failed when they are absent -- but it has
    already caught what nothing else could: the scrollspy threw where
    IntersectionObserver was missing, and because the page ships one script,
    that one throw took the search, the key bindings and the palette with it.
    """
    driver = ROOT / "drive.js"
    if not driver.exists():
        return "interactions: drive.js is missing"
    try:
        run = subprocess.run(["node", str(driver), str(ROOT / "index.html")],
                             capture_output=True, text=True, cwd=ROOT)
    except FileNotFoundError:
        return "node is not installed"
    if run.returncode == 2:
        return "jsdom is not installed (npm install jsdom)"
    if run.returncode != 0:
        for line in (run.stdout + run.stderr).splitlines():
            if line.strip():
                problems.append("interactions: " + line.strip())
        if not run.stdout.strip():
            problems.append("interactions: the driver failed with no output")
    return None


def check_pins(build, data, problems):
    """Every role beside a pin has a name, and every name is used.

    The pin map's labels come from the board's own source -- a binding name or
    the component being built next to the pin -- and PIN_ROLE says what such a
    name means. A board that starts using a pin for something new shows up here
    as an identifier with no translation, rather than as a raw `into_cs` on the
    page or, worse, as a pin that quietly looks unused.
    """
    for label in sorted(build.unnamed_pin_roles(data)):
        problems.append(
            f"pins: a pin is used by {label!r} and PIN_ROLE does not say what "
            f"that is, so the map renders the identifier raw")
    used = build.pin_labels(data)
    if used:
        for name in sorted(set(build.PIN_ROLE) - used):
            problems.append(
                f"pins: PIN_ROLE describes {name!r} and no board's source "
                f"names it any more")


def check_header(build, problems):
    """The header table is internally consistent.

    This checks a typo, not a pinout. The forty pins are the board's form
    factor and are not derived from anything -- nothing here can tell you they
    are right, only that they are not obviously wrong: forty entries numbered
    once each, and every one of the chip's thirty GPIOs accounted for exactly
    once between the header and the four that are not brought out.
    """
    header = build.HEADER
    if len(header) != 40:
        problems.append(f"header: {len(header)} pins, expected 40")
    numbers = [p for p, _, _ in header]
    if sorted(numbers) != list(range(1, 41)):
        problems.append("header: the physical pin numbers are not 1 to 40 exactly once")
    for _, kind, _ in header:
        if kind not in ("gpio", "gnd", "power", "ctrl"):
            problems.append(f"header: {kind!r} is not a kind of pin")
    on = [int(name[2:]) for _, kind, name in header if kind == "gpio"]
    if len(on) != len(set(on)):
        problems.append("header: a GPIO appears on the header twice")
    both = set(on) & set(build.OFF_HEADER)
    if both:
        problems.append(f"header: {sorted(both)} are both on the header and not")
    missing = set(range(30)) - set(on) - set(build.OFF_HEADER)
    if missing:
        problems.append(f"header: GPIOs {sorted(missing)} are on neither list")


def check_pinmaps(build, html, problems):
    """One pin map showing at rest, and a tab for each."""
    maps = dict(re.findall(r'<div class="pinmap" id="pm-([^"]+)"( hidden)?>', html))
    tabs = set(re.findall(r'<button class="ptab[^"]*" data-board="([^"]+)"', html))
    for name in sorted(set(maps) - tabs):
        problems.append(f"pins: the map for {name!r} has no tab to reach it")
    for name in sorted(tabs - set(maps)):
        problems.append(f"pins: a tab points at {name!r}, which has no map")
    shown = [n for n, hidden in maps.items() if not hidden]
    if maps and len(shown) != 1:
        problems.append(f"pins: {len(shown)} pin maps are visible at rest, expected 1")


def check_bits(html, problems):
    """Every register drawn as bits accounts for all of them.

    The strips are drawn with proportional widths, so a field the parser
    mis-read does not leave a hole -- the remaining pieces stretch to fill the
    row and the picture still looks like a register. Summing the widths against
    the width the register actually is, is the only way to see it.
    """
    for ident, label, body in re.findall(
            r'<div class="bits" id="([^"]+)"[^>]*aria-label="([^"]+)"[^>]*>(.*?)</div>',
            html, re.S):
        width = re.search(r"(\d+) bits", label)
        if not width:
            problems.append(f"bits: {ident} does not say how wide the register is")
            continue
        drawn = sum(int(n) for n in re.findall(r'style="flex:(\d+)"', body))
        if drawn != int(width.group(1)):
            problems.append(
                f"bits: {ident} draws {drawn} bits of a {width.group(1)}-bit register")


def check_queue(build, data, html, problems):
    """The drawn queue and the written queue are the same queue.

    Two ways they could stop being: a stage heading counting something other
    than what is under it, and a card that names a branch or pull request the
    page does not have anywhere else. Both would leave a picture that reads
    perfectly well and is not true.
    """
    for name in sorted(build.dangling_queue_deps(data)):
        problems.append(
            f"queue: QUEUE_DEPS names {name!r}, which is nothing in the queue, "
            f"so its arrow is silently not drawn")

    in_review, ready, _ = build.queue_groups(build.queue_rows(data))
    cards = build.queue_cards(data, ready, in_review)
    drawn = dict((label, int(n)) for label, n in re.findall(
        r'<text class="qhname[^>]*>([^<]+)</text>'
        r'<text class="qhsub"[^>]*>(\d+) ', html))
    for stage, label, _ in build.STAGES:
        if drawn.get(label) != len(cards[stage]):
            problems.append(
                f"queue: the {label!r} column is headed {drawn.get(label)} and "
                f"holds {len(cards[stage])} cards")

    listed = set(re.findall(r'<li data-branch="([^"]+)"', html))
    priced = set(re.findall(r'<article class="prcard" data-pr="(\d+)"', html))
    for group in cards.values():
        for card in group:
            if card["pr"] and str(card["pr"]) not in priced:
                problems.append(
                    f"queue: card #{card['pr']} has no pull request card to match it")
            elif not card["pr"] and card["branch"] not in listed:
                problems.append(
                    f"queue: card {card['branch']!r} is drawn and is not in the "
                    f"list below it")

def check_drift(build, data, html, problems):
    if build.render(data) != html:
        problems.append(
            "drift: index.html differs from what build.py produces from "
            "data.json — it was hand-edited, or a rebuild is pending"
        )


def check_fresh(build, data, problems):
    live = build.fetch()
    was = {p["number"]: p for p in data["prs"]}
    now = {p["number"]: p for p in live["prs"]}
    for num in sorted(set(now) - set(was)):
        problems.append(f"fresh: #{num} is new since the page was built — "
                        f"{now[num]['title']!r}")
    for num in sorted(set(was) - set(now)):
        problems.append(f"fresh: #{num} is in the page but not on GitHub")
    for num in sorted(set(was) & set(now)):
        old_state = build.pr_state(was[num])[1]
        new_state = build.pr_state(now[num])[1]
        if old_state != new_state:
            problems.append(f"fresh: #{num} went from {old_state} to {new_state}")
        old_commits = [c["messageHeadline"] for c in was[num]["commits"]]
        new_commits = [c["messageHeadline"] for c in now[num]["commits"]]
        if old_commits != new_commits:
            problems.append(f"fresh: #{num}'s commits changed since the build")
    for num in sorted(set(was) & set(now)):
        if was[num].get("files") != now[num].get("files"):
            problems.append(f"fresh: #{num}'s file list changed, so the "
                            f"branch collisions may be wrong")
    live_issues = {i["number"] for i in live["issues"]}
    for num in sorted(live_issues - {i["number"] for i in data["issues"]}):
        problems.append(f"fresh: issue #{num} is new since the page was built")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="skip the live fetch")
    args = parser.parse_args()

    for name in ("build.py", "data.json", "index.html"):
        if not (ROOT / name).exists():
            sys.exit(f"error: {name} is missing; run ./build.py first")

    build = load_build()
    data = json.loads((ROOT / "data.json").read_text())
    html = (ROOT / "index.html").read_text()

    problems = []
    check_drift(build, data, html, problems)
    check_annotated(build, data, problems)
    check_intent(build, data, problems)
    check_facts(build, data, problems)
    check_refs(build, data, problems)
    check_private(html, problems)
    check_contrast(build, problems)
    check_blocks(build, data, problems)
    check_nav(build, html, problems)
    check_grid(build, html, problems)
    check_trace(build, html, problems)
    check_styles(build, html, problems)
    check_pins(build, data, problems)
    check_header(build, problems)
    check_pinmaps(build, html, problems)
    check_bits(html, problems)
    check_queue(build, data, html, problems)
    skipped = check_interactions(problems)
    if not args.offline:
        check_fresh(build, data, problems)

    ran = (17 if args.offline else 18) + (0 if skipped else 1)
    if skipped:
        print(f"note: the interaction check did not run — {skipped}\n")
    if problems:
        print(f"{len(problems)} problem(s) across {ran} checks:\n")
        for p in problems:
            print(f"  {p}")
        print("\nMost of these are fixed by running ./build.py.")
        return 1
    clean = ("the page matches its data, every commit and branch is accounted "
             "for, every reference resolves, nothing private is in the HTML and "
             "nothing is unreadable")
    if args.offline:
        print(f"{ran} checks clean — {clean}. GitHub was NOT contacted, so "
              f"whether the data is current is unknown.")
    else:
        print(f"{ran} checks clean — {clean}, and the data still matches GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
