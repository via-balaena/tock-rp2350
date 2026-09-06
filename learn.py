#!/usr/bin/env python3
"""Publish the series as pages a browser can open.

    ./learn.py        # write read/ from learning/

The chapters carry no doctype, no `<head>` and no `<meta charset>`. That is
deliberate: they were written as artifacts, where the host supplies the
skeleton at publish time. Read straight off disk a browser falls into quirks
mode, so the margins and line heights are not the ones the pages were designed
against, and any non-ASCII byte is at the mercy of whatever the server guesses.

So this supplies the same skeleton, and it takes it from `serve.py` rather than
writing a second copy: `serve.py` reproduces what the artifact host injected so
that a local read and a published read are the same document, and a second
skeleton here would be a third thing to keep in step. The only part removed is
its live-reload script, which polls an endpoint that exists only locally.

The sources are not touched and do not become a build product. `learning/` is
still what `check.py`, `mkbook.py` and `serve.py` read; `read/` is what the
site serves, and `check.py` at the repository root fails if the two disagree.
"""

import argparse
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent
SOURCE = ROOT / "learning"
OUT = ROOT / "read"

# A strip at the top of the cover only, not on every chapter. The chapters
# carry their own headers and their own sticky elements, and dropping site
# chrome above them is how a page ends up with two bars fighting for the same
# forty pixels. A chapter already links back to the cover; the cover links on
# to the map from here.
BAR = """<nav class="sitebar"><a href="../">&larr; The work map</a>
<span>Tock on the RP2350 &mdash; what is done, what it runs on, what is left</span></nav>
<style>
.sitebar{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;
padding:11px 20px;border-bottom:1px solid #e4e2dd;background:#fff;
font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.sitebar a{color:#7a4b1e;font-weight:600;text-decoration:none}
.sitebar a:hover{text-decoration:underline}
.sitebar span{color:#6f7278}
@media (prefers-color-scheme:dark){
.sitebar{background:#1b1c20;border-bottom-color:#2c2d33}
.sitebar a{color:#d9a273}
.sitebar span{color:#8e8f95}
}
</style>
"""


def skeleton():
    """`serve.py`'s shell, with the part that only works locally taken out."""
    spec = importlib.util.spec_from_file_location(
        "serve", SOURCE / "tools" / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    shell, count = re.subn(r"<script>.*?</script>\n?", "", serve.SHELL, flags=re.S)
    if count != 1:
        sys.exit("error: expected one script block in serve.py's SHELL, "
                 "found %d — the skeleton has changed shape" % count)
    return shell


def pages():
    """The cover, then every chapter in reading order."""
    yield "", SOURCE / "index.html"
    for chapter in sorted(SOURCE.glob("ch*/index.html")):
        yield chapter.parent.name, chapter


def render(shell, body, bar):
    return shell % {"theme": "", "body": (BAR if bar else "") + body}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what would change instead of writing")
    args = parser.parse_args()

    shell = skeleton()
    stale = []
    for name, source in pages():
        target = OUT / name / "index.html" if name else OUT / "index.html"
        page = render(shell, source.read_text(), bar=not name)
        if args.check:
            if not target.exists() or target.read_text() != page:
                stale.append(str(target.relative_to(ROOT)))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page)

    if args.check:
        if stale:
            print("out of date, run ./learn.py:")
            for path in stale:
                print("  " + path)
            return 1
        print("read/ matches learning/")
        return 0
    print("wrote read/ — the cover and %d chapters"
          % (len(list(pages())) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
