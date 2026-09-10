#!/usr/bin/env python3
"""Check a Claude memory directory for the drift that prose cannot avoid.

Memory is written by hand, about a world that moves. On 2026-09-10 a deliberate
sweep of the Tock memory found nine claims that a pull request was approved,
hours after both its approvals had been dismissed -- plus a stale line count and
two different numbers for the same measured median. Nothing compared any of it
to anything. The oracle site had grown a gate for exactly this class the same
afternoon; memory had none, which is the asymmetry this closes.

    ./check-memory.py [--offline] [PATH]

PATH defaults to the Tock project's memory directory. --offline skips every
check that needs GitHub, so it still runs on a plane.

Two kinds of check.

STRUCTURE is deterministic and cheap: frontmatter, names matching filenames, the
index and the directory agreeing, wikilinks resolving. These caught real drift
before -- an unindexed file is invisible to every future session, which is the
whole failure this directory exists to prevent.

CLAIMS compares what the prose asserts against what GitHub says now. Only two
kinds are checkable: that a numbered pull request is open, approved, merged or
closed, and how large it is. Everything else memory holds -- decisions, quotes,
hardware measurements, reasoning -- has no referent a script can reach, and is
none of this script's business.

The hard part is that memory is mostly *history*, and history does not rot.
"bradjc approved #5156 and asked in the same sentence" stays true forever; "#5156
is approved" does not. So a state claim is only reported when it disagrees with
GitHub AND reads as present tense: no date in the sentence, no past-tense marker,
no named actor doing the approving. That heuristic is stated rather than hidden,
and `--show-skipped` prints what it passed over so the boundary can be audited.

Three matching shapes, arrived at by measuring false positives rather than by
guessing. Adjacency both ways ("#5156 is approved", "merged as #5158"), and a
state word heading a LIST ("Approved and waiting on a merge: #5126, #5140,
#5156") -- which is the shape the real drift took, and the one a first cut
missed. A first cut also took any state word in the same sentence and produced
eleven false positives out of thirteen, because proximity is not attribution:
"#5126 IS FULLY CLEAR AND THE THREAD IS CLOSED" is about the thread.

Proven by breaking it, eight ways, each reverted (the harness lives beside this
file as test-check-memory.py): a memory dropped from the index, a name not
matching its filename, a dangling wikilink, a type outside the four, an index
line with no hook, a pull request listed as approved when its approvals were
dismissed, a stale size, and a merged pull request called open. With nothing
injected it is silent.

What it does NOT check, because the referent is not reachable: anything memory
holds that is a decision, a quote, a hardware measurement, or reasoning. Those
carry their measurement date in the prose instead, and a claim that goes stale
in that class is caught by reading, not by this.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

def default_memory_dir(project=pathlib.Path.home() / "forge/tock"):
    """Where Claude keeps memory for a project directory.

    Derived from the project path rather than written down, so this file
    carries no one's home directory in it and can live in a public repo.
    """
    return (pathlib.Path.home() / ".claude/projects"
            / str(project).replace("/", "-") / "memory")

# Files in the directory that are not memories.
NOT_MEMORIES = {"MEMORY.md", "README.md"}

VALID_TYPES = {"user", "feedback", "project", "reference"}

# Where a numbered pull request is assumed to live. Every #NNNN in this memory
# is tock/tock; a second project would need this to become a mapping.
REPO = "tock/tock"


def strip_code(text):
    """Fenced blocks and inline spans, blanked.

    Without this, `[[bin]]` in a discussion of Cargo.toml reads as a broken
    wikilink, and every `+7 -0` inside a quoted diff reads as a size claim.
    Blanking rather than deleting keeps offsets, so reported line numbers stay
    true to the file.
    """
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"```.*?```", blank, text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", blank, text)
    return text


def line_of(text, index):
    return text[:index].count("\n") + 1


def check_structure(files, index_text, problems):
    """Frontmatter, names, the index, and the links between memories."""
    stems = {p.stem for p in files}

    for path in files:
        text = path.read_text()
        if not text.startswith("---\n"):
            problems.append(f"structure: {path.name} has no frontmatter")
            continue
        front = text.split("---\n")[1]
        for field in ("name:", "description:", "metadata:"):
            if field not in front:
                problems.append(f"structure: {path.name} frontmatter has no {field}")
        name = re.search(r"^name:\s*(\S+)", front, re.M)
        if not name:
            problems.append(f"structure: {path.name} has no name field")
        elif name.group(1) != path.stem:
            problems.append(
                f"structure: {path.name} calls itself {name.group(1)!r}, so a "
                f"[[{name.group(1)}]] link would resolve to nothing")
        kind = re.search(r"^\s*type:\s*(\S+)", front, re.M)
        if not kind:
            problems.append(f"structure: {path.name} has no type")
        elif kind.group(1) not in VALID_TYPES:
            problems.append(
                f"structure: {path.name} has type {kind.group(1)!r}, not one of "
                + "/".join(sorted(VALID_TYPES)))
        if not text.split("---\n", 2)[-1].strip():
            problems.append(f"structure: {path.name} has frontmatter and no body")

    # The index is what a session actually loads. A memory missing from it is
    # invisible; an index line pointing nowhere sends a session looking.
    linked = set(re.findall(r"\]\((\S+?)\.md\)", index_text))
    for orphan in sorted(stems - linked):
        problems.append(
            f"index: {orphan}.md is not in MEMORY.md, so no session will see it")
    for dangling in sorted(linked - stems):
        problems.append(f"index: MEMORY.md links {dangling}.md, which does not exist")

    rows = [l for l in index_text.strip().splitlines() if l.strip()]
    for row in rows:
        if not re.match(r"^- \[[^\]]+\]\(\S+\.md\)\s+—\s+\S", row):
            problems.append(f"index: line is not `- [Title](file.md) — hook`: {row[:60]!r}")

    # Two sections with one heading make a memory ambiguous to navigate and easy
    # to append to twice. Added after doing exactly that: a second "# jrvanwhy"
    # section restating the first, written minutes after the checker that did
    # not look for it.
    for path in files:
        heads = re.findall(r"^#{1,3} .+$", strip_code(path.read_text()), re.M)
        for head in sorted({h for h in heads if heads.count(h) > 1}):
            problems.append(
                f"structure: {path.name} has {heads.count(head)} sections headed "
                f"{head.strip()[:60]!r}")

    # Wikilinks, ignoring anything inside code.
    for path in files:
        body = strip_code(path.read_text())
        for m in re.finditer(r"\[\[([^\]\n]+)\]\]", body):
            if m.group(1) not in stems:
                problems.append(
                    f"links: {path.name}:{line_of(body, m.start())} points at "
                    f"[[{m.group(1)}]], which is not a memory")


# --------------------------------------------------------------------------
# Claims against GitHub
# --------------------------------------------------------------------------

STATE_WORDS = ("approved", "merged", "closed", "open")

# A sentence that dates itself, or names who did the thing, or puts the verb in
# the past, is a record of what happened -- and records do not go stale. These
# are the markers that make a hit historical rather than current.
HISTORICAL = re.compile(
    r"\b(19|20)\d{2}-\d{2}-\d{2}\b"          # an explicit date
    r"|\bwas\b|\bwere\b|\bhad\b|\bhas been\b"
    r"|\bre-approved\b|\bdismissed\b|\buntil\b|\bthen\b|\bafter\b|\bbefore\b"
    r"|\bwhen\b|\bonce\b|\bwould\b|\bcould\b|\bif\b|\bnot\b|\bnever\b"
    r"|\b(bradjc|ppannuto|lschuermann|alevy|jrvanwhy|alexandruradovici)\s+\w*"
    r"(approv|merg|clos|open)",
    re.I)


# Proximity is not attribution, and a first cut that took any state word in the
# same sentence produced eleven false positives out of thirteen: "#5126 IS FULLY
# CLEAR AND THE THREAD IS CLOSED" is about the thread, "its *closed*
# predecessor" is about a different pull request, and "open PRs" in a sentence
# about #5118 is a generic plural. The word has to be bound to the number.
PR_THEN_STATE = re.compile(
    r"#(\d{4})\b[\s*_,(\[-]{0,3}(?:is|are|was|were|remains|still|now)?"
    r"[\s*_,(\[-]{0,3}(approved|merged|closed|open)\b", re.I)
STATE_THEN_PR = re.compile(
    r"\b(approved|merged|closed|open)\b(?:\s+(?:as|in|via))?[\s*_,(\[-]{0,3}"
    r"#(\d{4})\b", re.I)


def sentence_around(text, at):
    start = max(text.rfind(".", 0, at), text.rfind("\n", 0, at)) + 1
    end = text.find(".", at)
    return " ".join(text[start: end if end != -1 else len(text)].split())


# Adjacency alone misses the shape the 2026-09-10 drift actually took: a state
# word heading a LIST of pull requests, "Approved and waiting on a merge: #5126,
# #5140, #5156". The state governs every number in the run. Guarded by refusing
# to cross a sentence end or a second state word, so "closed ... then approved
# #5158" does not smear one verb over both.
DETERMINER_BEFORE = re.compile(r"\b(the|a|an|its|this|that|their|his|her|each|every)\s+$", re.I)

STATE_THEN_LIST = re.compile(
    r"\b(approved|merged|closed|open)\b([^.\n]{0,80}?)"
    r"((?:#\d{4}(?:[\s,+*]|and\b)*){1,6})", re.I)


def state_claims(text):
    """Each (pr number, state word, sentence, offset) the prose binds together."""
    seen = set()
    def emit(number, word, at):
        if (number, word, at) not in seen:
            seen.add((number, word, at))
            return [(number, word, sentence_around(text, at), at)]
        return []

    out = []
    for m in PR_THEN_STATE.finditer(text):
        out += emit(int(m.group(1)), m.group(2).lower(), m.start())
    for m in STATE_THEN_PR.finditer(text):
        out += emit(int(m.group(2)), m.group(1).lower(), m.start())
    for m in STATE_THEN_LIST.finditer(text):
        between = m.group(2)
        if re.search(r"\b(approved|merged|closed|open)\b", between, re.I):
            continue
        # "The merged form is #5141's holding" uses the word as an adjective on
        # the following noun, not as a state of the pull request. A determiner
        # immediately before it is the tell.
        if DETERMINER_BEFORE.search(text[max(0, m.start() - 24):m.start()]):
            continue
        for n in re.findall(r"#(\d{4})", m.group(3)):
            out += emit(int(n), m.group(1).lower(), m.start())
    return out


def github_prs(numbers):
    """State, review decision and size for each pull request, from GitHub."""
    out = {}
    for n in sorted(numbers):
        try:
            raw = subprocess.run(
                ["gh", "pr", "view", str(n), "--repo", REPO, "--json",
                 "number,state,reviewDecision,additions,deletions,changedFiles"],
                capture_output=True, text=True, timeout=60)
            if raw.returncode == 0:
                out[n] = json.loads(raw.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError):
            pass
    return out


def check_claims(files, prs, problems, skipped):
    for path in files:
        body = strip_code(path.read_text())
        for number, word, sentence, at in state_claims(body):
            pr = prs.get(number)
            if pr is None:
                continue
            if word == "approved":
                actual_ok = pr.get("reviewDecision") == "APPROVED"
            else:
                actual_ok = pr["state"] == word.upper()
            if actual_ok:
                continue
            where = f"{path.name}:{line_of(body, at)}"
            if HISTORICAL.search(sentence):
                skipped.append(f"{where}  [reads as history] {sentence[:96]}")
                continue
            problems.append(
                f"claims: {where} says #{number} is {word}, but it is "
                f"{pr['state']}/{pr.get('reviewDecision') or 'no decision'} — "
                f"{sentence[:90]}")

        # Size claims: a +N -N adjacent to a pull request number.
        for m in re.finditer(r"#(\d{4})[^.\n]{0,80}?\+(\d[\d,]*)\s*[-−–]\s*(\d[\d,]*)",
                             body):
            pr = prs.get(int(m.group(1)))
            if pr is None:
                continue
            add, dele = (int(g.replace(",", "")) for g in (m.group(2), m.group(3)))
            if (add, dele) != (pr["additions"], pr["deletions"]):
                problems.append(
                    f"claims: {path.name}:{line_of(body, m.start())} says #{m.group(1)} "
                    f"is +{add} -{dele}, but it is +{pr['additions']} "
                    f"-{pr['deletions']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=None,
                    help="memory directory (default: derived from ~/forge/tock)")
    ap.add_argument("--offline", action="store_true",
                    help="skip everything that needs GitHub")
    ap.add_argument("--show-skipped", action="store_true",
                    help="print the claims judged historical, to audit the heuristic")
    args = ap.parse_args()

    root = pathlib.Path(args.path) if args.path else default_memory_dir()
    if not root.is_dir():
        sys.exit(f"check-memory: {root} is not a directory")
    index_file = root / "MEMORY.md"
    if not index_file.exists():
        sys.exit(f"check-memory: {root}/MEMORY.md is missing")

    files = sorted(p for p in root.glob("*.md") if p.name not in NOT_MEMORIES)
    problems, skipped = [], []
    ran = 1
    check_structure(files, index_file.read_text(), problems)

    if not args.offline:
        numbers = set()
        for path in files:
            numbers |= {int(n) for n in re.findall(r"#(\d{4})\b",
                                                   strip_code(path.read_text()))}
        prs = github_prs(numbers)
        check_claims(files, prs, problems, skipped)
        ran += 1

    if args.show_skipped and skipped:
        print(f"{len(skipped)} claim(s) judged historical and passed over:\n")
        for s in skipped:
            print("  " + s)
        print()

    if problems:
        print(f"{len(problems)} problem(s) across {len(files)} memories:\n")
        for p in problems:
            print("  " + p)
        return 1

    scope = "structure only" if args.offline else "structure and claims against GitHub"
    print(f"{len(files)} memories clean — {scope}."
          + ("" if args.offline else f" {len(skipped)} claim(s) read as history."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
