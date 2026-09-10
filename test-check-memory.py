#!/usr/bin/env python3
"""Break check-memory.py on purpose, one way at a time.

A check that has never failed has never been tested. Each case builds a small
memory directory in a temp dir, plants exactly one defect, runs the checker
against it, and reports whether the checker noticed.

**It never touches a real memory directory.** The first version of this file
mutated the live one and restored from a backup, which was wrong twice over. A
stale backup silently reverts whatever memory has learned since -- it did, once,
within an hour of that version being written. And the injection points it needed
were filenames and verbatim lines out of private notes, which is not something
to keep in a public repository. Fixtures are written here instead; the only
outside facts are pull request numbers, which are public.

    ./test-check-memory.py

Exits 0 when every injection is caught and a clean fixture is silent.
"""

import pathlib
import subprocess
import sys
import tempfile

GATE = pathlib.Path(__file__).resolve().parent / "check-memory.py"

# Two real pull requests whose states are settled, so the claim checks have
# something true to disagree with.
MERGED_PR = 5118      # the AI policy; merged and staying merged
OPEN_PR = 5156        # open, its approvals dismissed 2026-09-10


def memory(name, kind, body):
    return (f'---\nname: {name}\ndescription: "A fixture."\n'
            f"metadata:\n  type: {kind}\n---\n\n{body}\n")


def build(root):
    """A minimal but valid memory directory."""
    files = {
        "alpha-note": ("project", "Alpha. It links to [[beta-note]]."),
        "beta-note": ("feedback", "Beta, which exists so that link resolves."),
        "gamma-note": ("reference", f"Gamma mentions #{MERGED_PR} in passing."),
    }
    for name, (kind, body) in files.items():
        (root / f"{name}.md").write_text(memory(name, kind, body))
    (root / "MEMORY.md").write_text(
        "\n".join(f"- [{n}]({n}.md) — a fixture hook" for n in files) + "\n")
    return root


def run(root, offline):
    cmd = [sys.executable, str(GATE), str(root)] + (["--offline"] if offline else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return [l.strip() for l in r.stdout.splitlines() if l.startswith("  ")]


def case(label, plant, offline=True):
    with tempfile.TemporaryDirectory(prefix="memory-gate-") as tmp:
        root = build(pathlib.Path(tmp))
        plant(root)
        hits = run(root, offline)
    print(f"  {'CAUGHT ' if hits else 'MISSED '} {label}")
    if hits:
        print(f"          {hits[0][:110]}")
    return bool(hits)


def edit(name, old, new):
    def go(root):
        p = root / name
        s = p.read_text()
        assert old in s, f"fixture missing {old!r}"
        p.write_text(s.replace(old, new, 1))
    return go


def append(name, text):
    def go(root):
        p = root / name
        p.write_text(p.read_text().rstrip() + "\n\n" + text + "\n")
    return go


results = []

print("=== structure ===")
results.append(case("a memory dropped from the index",
                    edit("MEMORY.md", "- [alpha-note](alpha-note.md)",
                         "- [alpha-note](alpha-note-TYPO.md)")))
results.append(case("an index line pointing at nothing",
                    append("MEMORY.md", "- [ghost](ghost.md) — never existed")))
results.append(case("a name not matching its filename",
                    edit("alpha-note.md", "name: alpha-note", "name: alpha-notes")))
results.append(case("a dangling wikilink",
                    edit("alpha-note.md", "[[beta-note]]",
                         "[[a-memory-that-never-was]]")))
results.append(case("a type outside the four",
                    edit("alpha-note.md", "type: project", "type: notes")))
results.append(case("an index line with no hook",
                    edit("MEMORY.md", "- [alpha-note](alpha-note.md) — a fixture hook",
                         "- [alpha-note](alpha-note.md)")))
results.append(case("two sections under one heading",
                    append("alpha-note.md",
                           "## A heading\n\nOne.\n\n## A heading\n\nTwo.")))
results.append(case("frontmatter with no body",
                    lambda root: (root / "beta-note.md").write_text(
                        memory("beta-note", "feedback", ""))))

print("\n=== claims, against live GitHub ===")
results.append(case("a merged pull request called open",
                    append("alpha-note.md", f"#{MERGED_PR} is open."),
                    offline=False))
results.append(case("a list under a state word — the shape the real drift took",
                    append("alpha-note.md",
                           f"Approved and waiting on a merge: #{OPEN_PR}."),
                    offline=False))
results.append(case("a stale pull request size",
                    append("alpha-note.md", f"#{OPEN_PR} is +9999 -8888 today."),
                    offline=False))

print("\n=== the guard: a clean fixture must be silent ===")
with tempfile.TemporaryDirectory(prefix="memory-gate-") as tmp:
    fixture = build(pathlib.Path(tmp))
    off, live = run(fixture, True), run(fixture, False)
clean = not off and not live
print(f"  {'SILENT ' if clean else 'NOISY  '} nothing injected "
      f"(offline hits={len(off)}, live hits={len(live)})")

print(f"\n{sum(results)}/{len(results)} injections caught; "
      f"guard {'clean' if clean else 'DIRTY'}")
sys.exit(0 if all(results) and clean else 1)
