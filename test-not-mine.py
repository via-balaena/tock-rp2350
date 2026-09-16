#!/usr/bin/env python3
"""NOT_MINE exempts two checks. Prove it exempts no others.

`check_intent` and `check_facts` stopped failing on branches in repositories
this session does not write, because their intent and their evidence are not
mine to have written. Four other checks read the same queue rows -- `check_refs`,
`check_claims`, `check_basis` and `check_queue` -- and the worry recorded at
that fix was that one of them would turn red the next time the other session cut
a branch, for a reason that was nobody's defect.

That worry was answerable without waiting for a branch, and this file answers it
both ways. It patches a dict in memory and renders to a string; **it writes
nothing**, so it can run against the live data.json without disturbing it.

The half that matters is the second. A run where nothing goes red proves only
that nothing ran, so every positive control here is applied to a LIBTOCK-RS row:
the question was never whether these four work, it is whether NOT_MINE quietly
excuses a branch of theirs from them the way it does the other two.

    ./test-not-mine.py

Exits 0 when the untouched case is green and every injection is caught.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import build   # noqa: E402
import check   # noqa: E402

DATA = ROOT / "data.json"
NAME = "synthetic-control-probe"
REPO = "libtock-rs"
KEY = f"{REPO}:{NAME}"

# A branch of theirs as it looks the moment it is cut and before any message
# describing it arrives: ahead, pushed, and in no INTENT entry of mine. The
# empty base_sha is deliberate -- check_basis re-derives from the clone, where
# this name does not exist, so any value here would manufacture a red that says
# nothing about a real branch. check_basis gets its own control below, on a
# branch that does exist.
PROBE = {
    "ahead": 1,
    "commits": ["adapter: answer the format the kernel gave back"],
    "stat": "1 file changed, 24 insertions(+), 6 deletions(-)",
    "base": "upstream/master",
    "base_sha": "",
    "behind": 0,
    "pushed": True,
    "on_remote": True,
    "unpushed": 0,
}

failures = []


def load(probe=True):
    d = json.loads(DATA.read_text())
    if probe:
        d["local"][REPO][NAME] = dict(PROBE)
    return d


def report(label, want, problems):
    got = "RED" if problems else "green"
    ok = got == want
    if not ok:
        failures.append(f"{label}: wanted {want}, got {got}")
    print("  %s %-56s %s" % ("ok  " if ok else "FAIL", label, got))
    for p in problems[:3]:
        print("         " + p)


def mine(problems, needle=NAME):
    return [p for p in problems if needle in p]


def case_untouched():
    """Their branch, no intent entry, page rebuilt: every check green."""
    print("the case NOT_MINE created — their branch, no INTENT entry:")
    d = load()
    html = build.render(d)
    for name, extra in (("check_refs", ()), ("check_claims", ()),
                        ("check_basis", ()), ("check_queue", (html,))):
        problems = []
        getattr(check, name)(build, d, *extra, problems)
        report(name, "green", mine(problems))

    # Green is only worth something if the branch reached the code at all. Both
    # halves of the queue must know about it, which is also what keeps
    # check_queue's card/list arm from passing vacuously.
    rows = build.queue_groups(build.queue_rows(d))[1]
    drawn = any(r["branch"] == NAME for r in rows)
    listed = f'<li data-branch="{NAME}"' in html
    if not (drawn and listed):
        failures.append(
            f"the probe never reached the queue (card={drawn} list={listed}), "
            f"so the greens above prove nothing")
    print("  %s the branch is drawn as a card (%s) and listed below it (%s)"
          % ("ok  " if drawn and listed else "FAIL", drawn, listed))


def case_refs():
    d = load()
    build.INTENT[KEY] = ("upstream", "fixes #9999", None)
    try:
        problems = []
        check.check_refs(build, d, problems)
        report("check_refs  <- a bogus #9999 in their intent note", "RED", problems)
    finally:
        build.INTENT.pop(KEY, None)


def case_claims():
    d = load()
    build.INTENT[KEY] = ("upstream", "three files changed", None)
    try:
        problems = []
        check.check_claims(build, d, problems)
        report("check_claims <- note says three files, diff has one", "RED",
               mine(problems))
    finally:
        build.INTENT.pop(KEY, None)


def case_basis():
    """Give a real branch of theirs a basis it cannot contain.

    The pair is found rather than written down: any two of their branches cut
    from different points will do, and which ones exist changes week to week.
    Finding the fixture with git is fine; the assertion is still the check's.
    """
    d = load(probe=False)
    path, _ = build.LOCAL[REPO]
    if not path.exists():
        print("  skip  check_basis — no %s clone on this machine" % REPO)
        return
    rows = d["local"][REPO]
    shas = {i["base_sha"] for i in rows.values() if i.get("base_sha")}
    for branch, info in sorted(rows.items()):
        if info.get("ahead", 0) == 0:
            continue
        for sha in sorted(shas - {info.get("base_sha")}):
            if build.git(path, "merge-base", "--is-ancestor", sha, branch) is None:
                info["base_sha"] = sha
                problems = []
                check.check_basis(build, d, problems)
                report("check_basis <- %s given a basis it cannot contain" % branch,
                       "RED", mine(problems, branch))
                return
    # Skipped, not failed. Which branches they hold is their business, and if
    # they ever sit on one basis there is no pair to inject -- that is a fixture
    # this machine cannot supply, not a defect of mine. Failing on it would put
    # back exactly the coupling NOT_MINE was written to remove.
    print("  skip  check_basis — their branches share one basis, no pair to inject")


def case_queue():
    """Their card drawn against a page built before it existed."""
    problems = []
    check.check_queue(build, load(), build.render(load(probe=False)), problems)
    report("check_queue <- their card drawn, page not rebuilt", "RED", problems)


def main():
    case_untouched()
    print("\npositive controls, every one of them on a branch of theirs:")
    case_refs()
    case_claims()
    case_basis()
    case_queue()
    if failures:
        print("\n%d problem(s):" % len(failures))
        for f in failures:
            print("  " + f)
        return 1
    print("\nNOT_MINE exempts check_intent and check_facts and nothing else: "
          "a branch of theirs reaches all four of these and each can still fail "
          "on one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
