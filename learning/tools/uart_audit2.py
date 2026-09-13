#!/usr/bin/env python3
"""hil::uart Err(SIZE) audit, second attempt.

The first pass hardcoded the parameter names `tx_len` / `rx_len` and did not
follow delegations, so it produced at least two false positives:
  - imxrt10xx dispatches to transmit_buffer_dma / _interrupt, both of which
    check; only the wrapper was read.
  - x86_q35 names the parameter `len`, so `cmp::min(len, buffer.len())` did
    not match a pattern built around `tx_len`.

This version reads the real parameter names out of each signature and
follows a body that is a single delegating call. Every result is still read
by hand afterwards -- this only narrows the reading.
"""
import re
import subprocess

REV = "upstream/master"
REPO = "/Users/jonhillesheim/forge/tock"


def show(path):
    return subprocess.run(["git", "show", f"{REV}:{path}"],
                          capture_output=True, text=True, cwd=REPO).stdout


def find_fn(src, fname):
    """[(line, params_text, body)] for each `fn fname(`."""
    out = []
    for m in re.finditer(r"\bfn\s+" + re.escape(fname) + r"\s*\(", src):
        p_open = m.end() - 1
        depth, j = 0, p_open
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        params = src[p_open + 1: j]
        b = src.find("{", j)
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
        out.append((src[: m.start()].count("\n") + 1, params, src[b: k + 1]))
    return out


def param_names(params):
    """(buffer_param, len_param) from the signature, by position."""
    parts, depth, cur = [], 0, ""
    for ch in params:
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    named = [p.split(":")[0].strip() for p in parts if ":" in p and "self" not in p]
    return (named + [None, None])[:2]


def delegate_target(body):
    """If the body is just `self.foo(a, b)`, return foo."""
    inner = body.strip()[1:-1].strip()
    m = re.fullmatch(r"self\.(\w+)\s*\([^;]*\)\s*", inner, re.S)
    return m.group(1) if m else None


def checks(body, buf, ln):
    pats = [r"ErrorCode::SIZE"]
    if buf and ln:
        pats += [
            rf"\b{ln}\s*>\s*{buf}\.len\(\)", rf"\b{buf}\.len\(\)\s*<\s*{ln}\b",
            rf"\b{ln}\s*<=\s*{buf}\.len\(\)", rf"\b{buf}\.len\(\)\s*>=\s*{ln}\b",
            rf"min\(\s*{ln}\s*,", rf"min\(\s*{buf}\.len\(\)\s*,\s*{ln}",
        ]
    return any(re.search(p, body, re.S) for p in pats)


files = subprocess.run(
    ["git", "grep", "-ln", "fn transmit_buffer", REV, "--", "chips/", "capsules/"],
    capture_output=True, text=True, cwd=REPO).stdout.split()
files = sorted(f.split(":", 1)[1] for f in files if ":" in f)

for fname, label in (("transmit_buffer", "TX"), ("receive_buffer", "RX")):
    print(f"\n===== {label} — Err(SIZE) when the length exceeds the slice =====")
    ok, bad = [], []
    for path in files:
        src = show(path)
        for line, params, body in find_fn(src, fname):
            buf, ln = param_names(params)
            tgt = delegate_target(body)
            if tgt:  # follow one hop
                subs = find_fn(src, tgt)
                if subs:
                    good = all(checks(b, *param_names(p)) for _l, p, b in subs)
                    (ok if good else bad).append((path, line, f"-> {tgt}"))
                    continue
            (ok if checks(body, buf, ln) else bad).append((path, line, ""))
    print(f"  checks:   {len(ok)}")
    print(f"  NO CHECK: {len(bad)}")
    for path, line, note in bad:
        print(f"    {path}:{line} {note}")
