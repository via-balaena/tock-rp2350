#!/usr/bin/env python3
"""hil::uart abort contract, across every implementation.

kernel/src/hil/uart.rs states, for transmit_abort (and the same shape for
receive_abort):

  "If this function returns `Ok(())`, there will be no future callback and
   the client may retransmit immediately. If this function returns any
   `Err()` there will be a callback. This means that if there is no
   outstanding call to [transmit_word] or [transmit_buffer] then a call to
   this function returns `Ok(())`."

Two separable promises, both checkable from the body alone:

  A. no operation outstanding  =>  MUST return Ok(())
  B. returns Err(_)            =>  a callback MUST follow

A body that returns Err unconditionally breaks A always, and breaks B
unless it schedules a callback -- it tells the caller to wait for a
callback that will never arrive.
"""
import re
import subprocess

REV = "upstream/master"
REPO = "/Users/jonhillesheim/forge/tock"


def show(path):
    return subprocess.run(["git", "show", f"{REV}:{path}"],
                          capture_output=True, text=True, cwd=REPO).stdout


def find_fn(src, fname):
    out = []
    for m in re.finditer(r"\bfn\s+" + re.escape(fname) + r"\s*\(", src):
        b = src.find("{", m.end())
        if b < 0:
            continue
        depth, k = 0, b
        while k < len(src):
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append((src[: m.start()].count("\n") + 1, src[b: k + 1]))
    return out


def classify(body):
    inner = " ".join(body.strip()[1:-1].split())
    if re.fullmatch(r"Ok\(\(\)\)", inner):
        return "ok-always", inner
    m = re.fullmatch(r"Err\(ErrorCode::(\w+)\)", inner)
    if m:
        return "ERR-ALWAYS", inner
    if re.search(r"\bif\b|\bmatch\b|\bmap\b|\.get\(\)|is_some\(\)", inner):
        return "conditional", inner[:70]
    return "other", inner[:70]


files = subprocess.run(
    ["git", "grep", "-ln", "fn transmit_abort", REV, "--", "chips/", "capsules/"],
    capture_output=True, text=True, cwd=REPO).stdout.split()
files = sorted(f.split(":", 1)[1] for f in files if ":" in f)

for fname in ("transmit_abort", "receive_abort"):
    print(f"\n===== {fname} =====")
    buckets = {}
    for path in files:
        src = show(path)
        for line, body in find_fn(src, fname):
            kind, txt = classify(body)
            buckets.setdefault(kind, []).append((path, line, txt))
    for kind in ("ERR-ALWAYS", "ok-always", "conditional", "other"):
        rows = buckets.get(kind, [])
        print(f"  {kind}: {len(rows)}")
        if kind == "ERR-ALWAYS":
            for path, line, txt in rows:
                print(f"      {path}:{line}   {txt}")
