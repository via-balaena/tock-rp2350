#!/usr/bin/env python3
"""Break the memory gate on purpose, one way at a time, and put it back.

A check that has never failed has never been tested. Each case edits one file,
runs check-memory.py, restores from a backup taken before anything ran, and
reports whether the gate noticed.
"""
import pathlib, shutil, subprocess, sys, tempfile

MEM = (pathlib.Path.home() / ".claude/projects"
       / str(pathlib.Path.home() / "forge/tock").replace("/", "-") / "memory")
# Taken fresh each run into a temp dir, so this never depends on a backup some
# earlier session happened to leave behind -- restoring from a stale one would
# silently revert whatever the memory has learned since.
BAK = pathlib.Path(tempfile.mkdtemp(prefix="memory-gate-backup-"))
GATE = pathlib.Path(__file__).resolve().parent / "check-memory.py"


def snapshot():
    for f in MEM.glob("*.md"):
        shutil.copy2(f, BAK / f.name)


def restore():
    for f in BAK.glob("*.md"):
        shutil.copy2(f, MEM / f.name)
    for f in MEM.glob("*.md"):
        if not (BAK / f.name).exists():
            f.unlink()


def run(offline):
    cmd = [str(GATE)] + (["--offline"] if offline else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return [l for l in r.stdout.splitlines() if l.startswith("  ")]


def case(label, mutate, offline=True):
    try:
        mutate()
        hits = run(offline)
    finally:
        restore()
    mark = "CAUGHT " if hits else "MISSED "
    print(f"  {mark} {label}")
    for h in hits[:1]:
        print(f"          {h.strip()[:112]}")
    return bool(hits)


def edit(name, old, new):
    def go():
        p = MEM / name
        s = p.read_text()
        assert old in s, f"injection point missing in {name}: {old[:40]!r}"
        p.write_text(s.replace(old, new, 1))
    return go


snapshot()
print(f"backed up {len(list(BAK.glob('*.md')))} memories to {BAK}\n")

results = []
print("=== structure ===")
results.append(case("a memory dropped from the index",
    edit("MEMORY.md", "- [Prose concision](prose-concision.md)",
                      "- [Prose concision](prose-concision-TYPO.md)")))
results.append(case("frontmatter name not matching the filename",
    edit("close-the-loop.md", "name: close-the-loop", "name: close-the-loops")))
results.append(case("a wikilink to a memory that does not exist",
    edit("close-the-loop.md", "\n\n", "\n\nSee [[a-memory-that-never-existed]].\n\n")))
results.append(case("a type outside the four allowed",
    edit("close-the-loop.md", "type: user", "type: notes")))
results.append(case("an index line missing its hook",
    edit("MEMORY.md", "- [Prose concision](prose-concision.md) —",
                      "- [Prose concision](prose-concision.md)")))

print("\n=== claims, against live GitHub ===")
results.append(case("#5156 listed as approved again — today's actual defect",
    edit("work-order.md", "**Approved, waiting on a merge: #5126, #5140.**",
                          "**Approved, waiting on a merge: #5126, #5140, #5156.**"),
    offline=False))
results.append(case("a stale pull request size",
    edit("objcopy-stack-filesz-mechanism.md", "the PR went +21 → **+13**",
                                              "#5156 is +21 -0 today"),
    offline=False))
results.append(case("a merged pull request called open",
    edit("tock-book-facts.md", "---\n\n", "---\n\nThe policy landed in #5118, open right now.\n\n"),
    offline=False))

print("\n=== the guard ===")
clean_off = run(True)
clean_on = run(False)
print(f"  {'MISSED ' if clean_off or clean_on else 'SILENT '} nothing injected"
      f" (offline hits={len(clean_off)}, live hits={len(clean_on)})")

ok = all(results) and not clean_off and not clean_on
print(f"\n{sum(results)}/{len(results)} injections caught; guard "
      f"{'clean' if not (clean_off or clean_on) else 'DIRTY'}")
sys.exit(0 if ok else 1)
