#!/usr/bin/env python3

# Licensed under the Apache License, Version 2.0 or the MIT License.
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright Jon Hillesheim 2026.

"""Refuse a causal claim that carries nothing anyone could check.

`claim-enum.py` gives a review pass its denominator. This grades one axis of
that list mechanically, the axis that has actually cost something.

An explanation sits in one of three states (global CLAUDE.md):

    executable          it has a referent -- a command, a file:line, a
                        measurement, a test. Stable: it can be re-checked.
    explicitly unknown  "what differs has not been isolated." Stable,
                        because it claims nothing that can rot.
    plausible declarative
                        "probably because X." Unstable forever, and it is
                        the one that reads best.

The third is what this refuses. On tock#5156 every maintainer agreed the
13-line change was fine and four days of thread went on one volunteered
causal sentence with no referent in it -- which had already been refuted
once. lschuermann: *"if we aren't sure we know what's happening, we
shouldn't proclaim we do."*

So the rule is not "is this true". A gauge cannot know that. It is:

    does this sentence assert a MECHANISM while carrying NOTHING
    a reader could check, and without saying it is unestablished?

That is decidable from the text, and it is exactly the shape that rots.

    claim-gauge.py pr-facts.md
    claim-gauge.py --html findings/4770/index.html
    claim-gauge.py --warn-absolutes draft.md

Exit 0 clean, 1 an unreferenced causal claim, 2 could not run.

WHAT IT IS AND IS NOT, measured rather than hoped
-------------------------------------------------
Recall, on a corpus of sentences that actually shipped here and were then
refuted: 6 of 6 causal ones flagged, including the #5156 sentence itself.
On a corpus of sentences that held up: 0 of 12 flagged, absolutes on.

Precision, on a real 318-claim facts document: 22 flagged, and **11 of
them judged real by hand. So about half.** The other half are design
reasoning -- "the channel set is a trait the chip crate implements, so
the package question is answered where it belongs" -- which asserts a
judgement, not a mechanism. No regex separates those two, because the
difference is semantic and both have the same shape.

So a flag means LOOK, not WRONG. That is still worth having: at the size
this is for -- a pull request comment, ten to thirty claims -- half of a
handful is one or two sentences to re-read, and the sentence that cost
#5156 its approvals is in that handful. It is a worklist that happens to
exit non-zero, not a verdict.

Do not tune it against a document until the number looks good. Two rules
were loosened here to kill false positives and one of them silently
un-flagged the headline sentence -- "reconstructs ONE on read" parsed as
a count. Re-run the positive controls after every loosening.
"""

import argparse
import re
import sys

# --- the three signals -------------------------------------------------
# Each list below was built from sentences that actually shipped here, not
# from a style guide. The test corpora are in the repository beside this.

# A sentence asserting WHY or HOW something happens.
CAUSAL = re.compile(
    r"\b(because|since|therefore|thus|hence|due to|owing to|as a result|"
    r"causes?|caused|results? in|resulting in|leads? to|led to|forces?|"
    r"forced|means that|the reason|that is why|which is why|so that)\b"
    r"|,\s+so\b",
    re.I,
)

# Something a reader could go and re-check. A backtick alone is NOT here:
# `BFD` in backticks is a name, not a measurement.
REFERENT = [
    ("a file", re.compile(
        r"\b[\w./-]+\.(?:rs|py|sh|md|toml|ld|c|h|json|js|html)\b|"
        r"\b[\w.-]+/[\w./-]+\b|"          # a path, extension or not
        r"\bMakefile(?:\.\w+)?\b")),      # the one that has none
    ("a line number", re.compile(r"\b[\w./-]+:\d+")),
    ("a number", re.compile(
        r"0x[0-9a-fA-F]+|\b\d+\b|"
        # Spelled-out counts, but "one" ONLY behind a quantifier.
        # Bare "one" is usually a pronoun: counting it as a number
        # silently un-flagged "ELF section headers carry no LMA, so
        # BFD reconstructs ONE on read from file offsets" -- the
        # single sentence this whole gauge exists because of.
        r"\b(?:exactly|only|just|precisely|all|both)\s+(?:zero|one)\b|"
        r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|"
        r"twelve|dozen|hundred|thousand)\b", re.I)),
    (
        "a measurement",
        # PAST TENSE ONLY, and this is load-bearing. A present-tense verb
        # describes behaviour -- "the loop runs once" asserts a mechanism and
        # proves nothing. A past-tense one reports something that was done.
        # Keeping "runs" here let "Because the shell does not word-split,
        # every loop of this shape runs once" pass as referenced.
        re.compile(
            r"\b(measured|measuring|ran|verified|verifying|reproduced|"
            r"observed|tested|exited|printed|matched|returned|built|"
            r"compiled|rebuilt|recorded|passed|failed)\b",
            re.I,
        ),
    ),
]

# Saying plainly that it is not known. This is a STABLE sentence and must
# never be flagged -- refusing it would teach exactly the wrong lesson.
UNKNOWN = re.compile(
    r"\b(not established|not been established|not isolated|not been isolated|"
    r"not verified|not been verified|not determined|undetermined|not known|"
    r"unknown|unclear|do not know|don't know|cannot tell|can't tell|"
    r"no idea|is a guess|suspect|suspicion|hypothesis|remains open|"
    r"unverified|unvalidated|untested|unproven|not reproduced|"
    r"not been reproduced|no data|one data point|"
    r"not claimed|is not claimed)\b",
    re.I,
)

# Confident absolutes are what get refuted in review. Softer rule: warn.
ABSOLUTE = re.compile(
    r"\b(always|never|every|all of them|none of them|only|cannot|can't|"
    r"impossible|no other|the only|nothing else|without exception)\b",
    re.I,
)

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*\[\"'])")
RULE_ONLY = set("- :|")


def from_markdown(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    units = []
    for chunk in text.split("\n\n"):
        block = chunk.strip()
        if not block or block.startswith("#"):
            continue
        if block.lstrip().startswith("|"):
            for line in block.split("\n"):
                for cell in line.strip().strip("|").split("|"):
                    cell = cell.strip()
                    if cell and not set(cell) <= RULE_ONLY:
                        units.append(cell)
        else:
            units.append(" ".join(block.split()))
    return units


def from_html(text):
    for tag in ("script", "style", "svg"):
        text = re.sub(rf"<{tag}.*?</{tag}>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.replace("&nbsp;", " ")
    return [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]


def sentences(units, min_words):
    out = []
    for unit in units:
        for s in SENT_SPLIT.split(unit):
            s = s.strip(" -*")
            if len(s.split()) >= min_words:
                out.append(s)
    return out


QUOTED = re.compile(r"[*_]*[\"\u201c\u2018'][^\"\u201d\u2019]{12,}[\"\u201d\u2019][*_]*")

# A sentence that opens with a bare verb is telling the reader what to do.
# It carries no mechanism claim, so a referent is not the right ask.
IMPERATIVE = re.compile(
    r"^[*_`]*(grep|budget|run|use|check|read|write|measure|do|don't|prefer|"
    r"keep|add|pair|fix|say|treat|make|never|always|avoid|stop|start|give|"
    r"put|drop|cut|name|ask|look|try|build|report|record|assume|remember|"
    r"note|see|skip|leave|take|pick|quote|flag|wire|point)\b",
    re.I,
)


def own_words(sentence):
    """The sentence with quoted material removed.

    Flagging a maintainer's quoted sentence for lacking a referent grades
    the wrong author. Only what the writer asserts in their own voice is
    theirs to support.
    """
    return QUOTED.sub(" ", sentence)


def referents(sentence):
    return [name for name, pat in REFERENT if pat.search(sentence)]


def grade(sentence):
    """('ok'|'bare-causal'|'bare-absolute', why) for one sentence."""
    if UNKNOWN.search(sentence):
        return "ok", "says plainly that it is not established"
    found = referents(sentence)
    if found:
        return "ok", "carries " + ", ".join(found)
    mine = own_words(sentence)
    if len(mine.split()) < 4:
        return "ok", "quoted material, not the writer's own claim"
    if IMPERATIVE.match(sentence.lstrip(" -*")):
        return "ok", "tells the reader what to do, asserts no mechanism"
    sentence = mine
    if CAUSAL.search(sentence):
        return "bare-causal", "asserts a mechanism with nothing to check"
    if ABSOLUTE.search(sentence):
        return "bare-absolute", "an absolute with nothing to check"
    return "ok", "makes no mechanism claim"


def main():
    ap = argparse.ArgumentParser(description="Grade claims for referents.")
    ap.add_argument("path")
    ap.add_argument("--html", action="store_true", help="input is HTML")
    ap.add_argument("--min-words", type=int, default=4)
    ap.add_argument(
        "--warn-absolutes",
        action="store_true",
        help="also report confident absolutes that carry no referent",
    )
    ap.add_argument("--width", type=int, default=110)
    ap.add_argument("--quiet", action="store_true", help="only print findings")
    args = ap.parse_args()

    try:
        text = open(args.path, encoding="utf-8").read()
    except OSError as e:
        print(f"claim-gauge: {e}", file=sys.stderr)
        return 2

    units = from_html(text) if args.html else from_markdown(text)
    found = sentences(units, args.min_words)

    # A document with no sentences is not a clean document. Same rule as
    # sweep.py: a zero that was never shown to be a real zero is BROKEN.
    if not found:
        print(
            f"claim-gauge: no sentences found in {args.path}. That is a fact "
            "about the parse, not the prose.",
            file=sys.stderr,
        )
        return 2

    causal, absolute = [], []
    for i, s in enumerate(found, 1):
        verdict, why = grade(s)
        if verdict == "bare-causal":
            causal.append((i, s, why))
        elif verdict == "bare-absolute":
            absolute.append((i, s, why))

    if causal:
        print(f"UNREFERENCED CAUSAL CLAIM x{len(causal)}", file=sys.stderr)
        for i, s, _why in causal:
            print(f"\n  {i:3}. {s[: args.width]}", file=sys.stderr)
        print(
            "\n  Each asserts why or how something happens and carries nothing\n"
            "  a reader could re-check. Give it a referent -- a file:line, a\n"
            "  command, a number, a test -- or write that it is not\n"
            "  established. Both of those are stable sentences; this is not.\n",
            file=sys.stderr,
        )

    if args.warn_absolutes and absolute:
        print(f"note: {len(absolute)} unreferenced absolute(s)", file=sys.stderr)
        for i, s, _why in absolute:
            print(f"  {i:3}. {s[: args.width]}", file=sys.stderr)
        print(
            "  These are the sentences review refutes. A count makes them\n"
            "  checkable; a superlative usually needs one.\n",
            file=sys.stderr,
        )

    if not args.quiet:
        clean = len(found) - len(causal) - (len(absolute) if args.warn_absolutes else 0)
        print(
            f"{len(found)} claims: {clean} carry a referent or claim no "
            f"mechanism, {len(causal)} are unreferenced causal"
            + (f", {len(absolute)} unreferenced absolute" if args.warn_absolutes else "")
        )

    return 1 if causal else 0


if __name__ == "__main__":
    sys.exit(main())
