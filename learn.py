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
import html
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent
SOURCE = ROOT / "learning"
OUT = ROOT / "read"

# The chrome belongs to the site, not to the chapters. Everything below is
# added at publish time: the sources keep no site navigation, so the series'
# own gate, mkbook.py and serve.py go on reading exactly what they always read.
#
# Nothing here relies on a chapter's own CSS tokens, and nothing here styles a
# chapter's own elements. The rail is fixed and the page is pushed by a wrapper
# the chapters know nothing about, because a chapter's stylesheet is loaded
# after this one and would win any argument about `body`.

CHROME_CSS = """
.dc-rail{position:fixed;top:0;left:0;width:244px;height:100vh;overflow-y:auto;
box-sizing:border-box;padding:22px 14px 20px;background:#fff;
border-right:1px solid #e4e2dd;z-index:40;
font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.dc-main{margin-left:244px}
.dc-mark{display:block;color:#16171a;text-decoration:none;font-weight:600;
padding:0 8px;margin-bottom:3px;letter-spacing:-.01em}
.dc-back{display:block;color:#7a4b1e;text-decoration:none;font-size:12px;
padding:0 8px;margin-bottom:18px}
.dc-back:hover{text-decoration:underline}
.dc-group{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;
color:#6f7278;padding:0 8px;margin:0 0 6px}
.dc-rail ol,.dc-rail ul{list-style:none;margin:0;padding:0}
.dc-ch{display:flex;gap:9px;align-items:baseline;color:#4f5157;text-decoration:none;
padding:4px 8px;border-radius:6px}
.dc-ch:hover{background:#fbfaf8;color:#16171a}
.dc-ch .dc-n{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
color:#8e8f95;flex:none;width:12px}
.dc-ch.dc-here{background:#fbfaf8;color:#16171a;font-weight:600;
box-shadow:inset 2px 0 0 #7a4b1e}
.dc-secs{margin:2px 0 8px 29px;border-left:1px solid #e4e2dd}
.dc-sec{display:block;color:#6f7278;text-decoration:none;font-size:12px;
padding:3px 0 3px 11px;margin-left:-1px;border-left:2px solid transparent}
.dc-sec:hover{color:#16171a}
.dc-sec.dc-on{color:#16171a;border-left-color:#7a4b1e}
.dc-cite{color:#7a4b1e;text-decoration:none;border-bottom:1px solid rgba(122,75,30,.35)}
.dc-cite:hover{border-bottom-color:#7a4b1e}
.dc-pin{font-size:12px;color:#6f7278;margin:10px 0 0}
.dc-keys{margin:18px 8px 0;font-size:11px;color:#8e8f95}
.dc-keys kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10.5px;
border:1px solid #e4e2dd;border-bottom-width:2px;border-radius:4px;padding:0 4px;color:#4f5157}
.dc-bar{position:fixed;top:0;left:244px;right:0;height:2px;background:transparent;z-index:41}
.dc-bar i{display:block;height:100%;width:0;background:#7a4b1e}
.dc-sheet{position:fixed;inset:0;z-index:60;display:flex;justify-content:center;
align-items:flex-start;padding-top:11vh;background:rgba(12,12,14,.45);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.dc-sheet[hidden]{display:none}
.dc-box{background:#fff;border:1px solid #e4e2dd;border-radius:12px;
width:min(620px,92vw);padding:16px;box-shadow:0 20px 64px rgba(0,0,0,.3)}
.dc-box h2{margin:0 0 12px;font-size:16px;color:#16171a}
#dc-q{width:100%;box-sizing:border-box;font:inherit;font-size:15px;padding:10px 12px;
border-radius:8px;border:1px solid #e4e2dd;background:#fbfaf8;color:#16171a}
#dc-hits{list-style:none;margin:8px 0 0;padding:0;max-height:46vh;overflow-y:auto}
#dc-hits li{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
padding:7px 9px;border-radius:7px;color:#4f5157;cursor:pointer;font-size:13px}
.dc-l{display:flex;flex-direction:column;gap:2px;min-width:0}
.dc-term{font-weight:600;color:#16171a}
.dc-def{font-size:12px;color:#6f7278;overflow:hidden;text-overflow:ellipsis;
white-space:nowrap;max-width:44ch}
#dc-hits li.dc-on{background:#fbfaf8;color:#16171a}
#dc-hits .dc-where{font-size:11px;color:#8e8f95;white-space:nowrap}
.dc-kl{display:grid;grid-template-columns:110px 1fr;gap:8px 14px;margin:0;
font-size:13px;color:#4f5157}
.dc-kl dt,.dc-kl dd{margin:0}
@media (prefers-color-scheme:dark){
.dc-rail{background:#1b1c20;border-right-color:#2c2d33}
.dc-mark{color:#edecea}.dc-back{color:#d9a273}.dc-group{color:#8e8f95}
.dc-ch{color:#b6b6ba}.dc-ch:hover{background:#131316;color:#edecea}
.dc-ch.dc-here{background:#131316;color:#edecea;box-shadow:inset 2px 0 0 #d9a273}
.dc-ch .dc-n{color:#8e8f95}
.dc-secs{border-left-color:#2c2d33}.dc-sec{color:#8e8f95}
.dc-sec:hover{color:#edecea}.dc-sec.dc-on{color:#edecea;border-left-color:#d9a273}
.dc-keys{color:#8e8f95}.dc-keys kbd{border-color:#2c2d33;color:#b6b6ba}
.dc-cite{color:#d9a273;border-bottom-color:rgba(217,162,115,.35)}
.dc-pin{color:#8e8f95}
.dc-bar i{background:#d9a273}
.dc-box{background:#1b1c20;border-color:#2c2d33}
.dc-box h2{color:#edecea}
#dc-q{background:#131316;border-color:#2c2d33;color:#edecea}
#dc-hits li{color:#b6b6ba}#dc-hits li.dc-on{background:#131316;color:#edecea}
#dc-hits .dc-where{color:#8e8f95}.dc-kl{color:#b6b6ba}
.dc-term{color:#edecea}.dc-def{color:#8e8f95}
}
@media (max-width:1000px){
.dc-rail{position:static;width:auto;height:auto;border-right:0;
border-bottom:1px solid #e4e2dd}
.dc-main{margin-left:0}.dc-bar{left:0}.dc-secs{display:none}
.dc-rail ol{display:flex;flex-wrap:wrap;gap:2px}
}
"""

CHROME_JS = """
(function () {
  "use strict";
  var INDEX = __INDEX__, HERE = __HERE__;

  /* --- which section you are in, and how far through --- */
  var links = [].slice.call(document.querySelectorAll(".dc-sec"));
  var heads = links.map(function (a) {
    return document.getElementById(a.getAttribute("href").slice(1));
  });
  var fill = document.querySelector(".dc-bar i");
  function onScroll() {
    var y = window.scrollY + 90, at = -1;
    for (var i = 0; i < heads.length; i++) {
      if (heads[i] && heads[i].offsetTop <= y) { at = i; }
    }
    links.forEach(function (a, i) { a.classList.toggle("dc-on", i === at); });
    if (fill) {
      var run = document.body.scrollHeight - window.innerHeight;
      fill.style.width = (run > 0 ? (window.scrollY / run) * 100 : 0) + "%";
    }
  }
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", onScroll);
  onScroll();

  /* --- search, over every heading in the series --- */
  var sheet = document.getElementById("dc-search");
  var keys = document.getElementById("dc-keysheet");
  var box = document.getElementById("dc-q");
  var list = document.getElementById("dc-hits");
  var hits = [], at = 0;

  function score(text, q) {
    var t = text.toLowerCase(), i = t.indexOf(q);
    if (i === 0) { return 0; }
    if (i > 0) { return 1; }
    var k = 0;
    for (var c = 0; c < q.length; c++) {
      k = t.indexOf(q[c], k) + 1;
      if (!k) { return -1; }
    }
    return 2;
  }
  function draw() {
    var q = box.value.trim().toLowerCase();
    hits = !q ? INDEX.filter(function (e) { return e.c === "chapter"; })
              : INDEX.map(function (e) { return [score(e.t, q), e]; })
                     .filter(function (p) { return p[0] >= 0; })
                     .sort(function (a, b) { return a[0] - b[0]; })
                     .slice(0, 12).map(function (p) { return p[1]; });
    at = 0;
    list.replaceChildren.apply(list, hits.map(function (e, i) {
      var li = document.createElement("li");
      li.setAttribute("role", "option");
      if (i === 0) { li.className = "dc-on"; }
      var left = document.createElement("span");
      left.className = "dc-l";
      var a = document.createElement("span");
      a.className = e.d ? "dc-term" : "";
      a.textContent = e.t;
      left.append(a);
      if (e.d) {
        var say = document.createElement("span");
        say.className = "dc-def";
        say.textContent = e.d;
        left.append(say);
      }
      var b = document.createElement("span"); b.className = "dc-where"; b.textContent = e.c;
      li.append(left, b);
      li.addEventListener("click", function () { go(e); });
      return li;
    }));
  }
  function mark() {
    [].slice.call(list.children).forEach(function (li, i) {
      li.classList.toggle("dc-on", i === at);
    });
  }
  function go(e) {
    close();
    if (e.p === HERE) {
      var el = e.h && document.getElementById(e.h);
      if (el) { el.scrollIntoView({ block: "start", behavior: "smooth" }); return; }
    }
    location.href = (HERE ? "../" : "") + e.p + (e.h ? "#" + e.h : "");
  }
  function open() { keys.hidden = true; sheet.hidden = false; box.value = ""; draw(); box.focus(); }
  function close() { sheet.hidden = true; keys.hidden = true; }

  [sheet, keys].forEach(function (el) {
    el.addEventListener("click", function (ev) { if (ev.target === el) { close(); } });
  });
  box.addEventListener("input", draw);
  box.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown") { ev.preventDefault(); at = Math.min(at + 1, hits.length - 1); mark(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); at = Math.max(at - 1, 0); mark(); }
    else if (ev.key === "Enter" && hits[at]) { ev.preventDefault(); go(hits[at]); }
  });
  addEventListener("keydown", function (ev) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)
                 || ev.target.isContentEditable;
    if (ev.key === "Escape") { close(); return; }
    if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) { return; }
    if (ev.key === "/") { ev.preventDefault(); open(); }
    else if (ev.key === "?") { ev.preventDefault(); sheet.hidden = true; keys.hidden = !keys.hidden; }
    else if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
      var step = document.querySelector(ev.key === "ArrowLeft" ? ".dc-prev" : ".dc-next");
      if (step) { location.href = step.getAttribute("href"); }
    }
  });
}());
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
    out = [("", SOURCE / "index.html")]
    for chapter in sorted(SOURCE.glob("ch*/index.html")):
        out.append((chapter.parent.name, chapter))
    return out


HEADING = re.compile(r"<h2(?![a-zA-Z])([^>]*)>(.*?)</h2>", re.S)
TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)


def plain(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", markup))).strip()


def outline(body):
    """Give every section heading an id, and report them in order.

    The chapters carry no ids of their own -- they were written as one column
    to be read, not navigated -- so the anchors are added here rather than in
    the sources, where they would be one more thing for the series' own gate
    to have an opinion about.
    """
    found = []

    def anchor(match):
        attrs, inner = match.group(1), match.group(2)
        existing = re.search(r'id="([^"]+)"', attrs)
        ident = existing.group(1) if existing else "s%d" % (len(found) + 1)
        found.append((ident, plain(inner)))
        if existing:
            return match.group(0)
        return "<h2%s id=\"%s\">%s</h2>" % (attrs, ident, inner)

    return HEADING.sub(anchor, body), found


TERM = re.compile(r"<dt(?![a-zA-Z])([^>]*)>(.*?)</dt>\s*<dd(?![a-zA-Z])[^>]*>(.*?)</dd>", re.S)


def vocabulary(body):
    """Give every defined term an id, and report the term and its definition.

    The series defines 137 words across nine pages and each one is already
    marked up as a dt with its dd -- a glossary in every chapter, reachable
    only by scrolling to the end of the right one. Nothing here writes a
    definition; it collects the ones that are already written.
    """
    found = []

    def anchor(match):
        attrs, term, meaning = match.groups()
        existing = re.search(r'id="([^"]+)"', attrs)
        ident = existing.group(1) if existing else "t%d" % (len(found) + 1)
        found.append((ident, plain(term), plain(meaning)))
        if existing:
            return match.group(0)
        return match.group(0).replace("<dt" + attrs + ">",
                                      "<dt%s id=\"%s\">" % (attrs, ident), 1)

    return TERM.sub(anchor, body), found


# Where the tree the chapters cite actually lives. The pages name a commit and
# nothing else, so a reader meets a bare hex string with no way to know it is
# reachable at all. It is: the fork is public, and GitHub takes a line range as
# an anchor, so every citation can be one click onto the exact lines it names.
FORK = "https://github.com/via-balaena/tock/blob/%s/%s"

SOURCES_BLOCK = re.compile(
    r'(<(?:section|div)[^>]*class="[^"]*\bsources\b[^"]*">)(.*?)(</(?:section|div)>)', re.S)
PIN_CODE = re.compile(r"commit <code>([0-9a-f]{7,40})</code>")
CITE_TOKEN = re.compile(
    r"<(?:code|a)\b[^>]*>([A-Za-z0-9_./-]+\.(?:rs|md|s|toml|cfg|ld|json|ya?ml)"
    r"|(?:[A-Za-z0-9_./-]*/)?Makefile(?:\.common)?)</(?:code|a)>"
    r"|:([1-9]\d*)(?:\s*(?:-|&ndash;|&#8211;|\u2013)\s*(\d+))?(?![\w])")


def link_citations(body):
    """Turn every line reference in a sources list into a link to those lines.

    The path context carries across bullets exactly as the gate resolves it, so
    "the same file, :17-27" links to the same file the gate checks -- one
    grammar, one answer. Nothing is added to the sources; the numbers that were
    already there become clickable.
    """
    def rewrite(match):
        head, block, tail = match.groups()
        found = PIN_CODE.search(block)
        if not found:
            return match.group(0)
        pin = found.group(1)
        current = {"path": None}

        def one(token):
            if token.group(1):
                current["path"] = token.group(1)
                return token.group(0)
            if current["path"] is None:
                return token.group(0)
            first, last = token.group(2), token.group(3)
            anchor = "#L" + first + ("-L" + last if last else "")
            return '<a class="dc-cite" href="%s%s">%s</a>' % (
                FORK % (pin, current["path"]), anchor, token.group(0))

        note = ('<p class="dc-pin">Every line reference below links to that '
                'commit on the fork it was read from, at the lines it names.</p>')
        return head + CITE_TOKEN.sub(one, block) + note + tail

    return SOURCES_BLOCK.sub(rewrite, body)


def rail(meta, here):
    """The fixed rail: the series, the chapter you are in, and its sections."""
    up = "../../" if here else "../"
    rows = []
    for name, number, title, _, _defined in meta:
        if not name:
            continue
        current = name == here
        href = ("../" + name + "/") if here else (name + "/")
        rows.append('<li><a class="dc-ch%s" href="%s"><span class="dc-n">%d</span>'
                    '<span>%s</span></a>%s</li>'
                    % (" dc-here" if current else "", e(href), number, e(title),
                       sections(meta, name) if current else ""))
    order = [m for m in meta if m[0]]
    at = next((i for i, m in enumerate(order) if m[0] == here), None)
    steps = ""
    if at is not None:
        if at > 0:
            steps += '<a class="dc-prev" href="../%s/" hidden></a>' % e(order[at - 1][0])
        if at < len(order) - 1:
            steps += '<a class="dc-next" href="../%s/" hidden></a>' % e(order[at + 1][0])
    return (
        '<nav class="dc-rail" aria-label="The series">'
        '<a class="dc-mark" href="%s">Tock on the RP2350</a>'
        '<a class="dc-back" href="%s">&larr; The work map</a>'
        '<p class="dc-group">Chapters</p><ol>%s</ol>'
        '<p class="dc-keys"><kbd>/</kbd> search &nbsp; <kbd>?</kbd> keys</p>'
        '%s</nav>' % (e(up + ""), e(up), "".join(rows), steps))


def sections(meta, name):
    for entry in meta:
        if entry[0] == name:
            return ('<ul class="dc-secs">%s</ul>' % "".join(
                '<li><a class="dc-sec" href="#%s">%s</a></li>' % (e(i), e(t))
                for i, t in entry[3]))
    return ""


def e(text):
    return html.escape(str(text))


def render(shell, body, meta, here, index):
    body, _ = outline(body)
    body, _ = vocabulary(body)
    body = link_citations(body)
    chrome = (
        '<style>%s</style>%s<div class="dc-bar"><i></i></div>'
        '<div class="dc-main">%s</div>'
        '<div class="dc-sheet" id="dc-search" hidden role="dialog" aria-modal="true"'
        ' aria-label="Search the series"><div class="dc-box">'
        '<input id="dc-q" type="search" autocomplete="off" spellcheck="false"'
        ' placeholder="Search 137 defined words and every heading" aria-controls="dc-hits">'
        '<ul id="dc-hits" role="listbox" aria-label="Results"></ul></div></div>'
        '<div class="dc-sheet" id="dc-keysheet" hidden role="dialog" aria-modal="true"'
        ' aria-labelledby="dc-kt"><div class="dc-box"><h2 id="dc-kt">Keys</h2>'
        '<dl class="dc-kl"><dt><kbd>/</kbd></dt><dd>Search the words and the headings</dd>'
        '<dt><kbd>?</kbd></dt><dd>This list</dd>'
        '<dt><kbd>&larr;</kbd> <kbd>&rarr;</kbd></dt><dd>Previous and next chapter</dd>'
        '<dt><kbd>Esc</kbd></dt><dd>Close</dd></dl></div></div>'
        '<script>%s</script>'
        % (CHROME_CSS, rail(meta, here), body,
           CHROME_JS.replace("__INDEX__", index.replace("</", "<\\/"))
                    .replace("__HERE__", json.dumps(here))))
    return shell % {"theme": "", "body": chrome}


def survey():
    """Every page's number, title and section headings, read once."""
    meta = []
    for name, source in pages():
        body = source.read_text()
        _, found = outline(body)
        _, defined = vocabulary(body)
        title = TITLE.search(body)
        number = int(name[2:4]) if name else -1
        meta.append((name, number, plain(title.group(1)) if title else name,
                     found, defined))
    return meta


def search_index(meta):
    """Every chapter and every heading in it, as one list the pages share."""
    entries = []
    for name, number, title, found, defined in meta:
        if not name:
            continue
        where = "%d. %s" % (number, title)
        entries.append({"t": where, "c": "chapter", "p": name + "/", "h": ""})
        for ident, text in found:
            entries.append({"t": text, "c": where, "p": name + "/", "h": ident})
        for ident, term, meaning in defined:
            entries.append({"t": term, "c": where, "p": name + "/", "h": ident,
                            "d": meaning[:190]})
    return json.dumps(entries, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what would change instead of writing")
    args = parser.parse_args()

    shell = skeleton()
    meta = survey()
    index = search_index(meta)
    stale = []
    for name, source in pages():
        target = OUT / name / "index.html" if name else OUT / "index.html"
        page = render(shell, source.read_text(), meta, name, index)
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
