# Facts for `agents-safety-comment-form`

**This is a fact sheet, not a draft.** Nothing here is a sentence to paste.
`AGENTS.md:12-28` bans AI-written prose addressed to humans and says, of the
AI-use disclosure specifically: *"You cannot write that disclosure, so state
those three things plainly to the user and let them write it up."* Sections 4
and 5 below are that statement.

Every number was taken on `upstream/master` at **a7b14ffaf**, not on a working
branch. Re-take any of them with the command given.

---

## 1. The change

| | |
|---|---|
| Branch | `agents-safety-comment-form`, head `104b137ab` |
| Base | `upstream/master` at `a7b14ffaf`, rebased 2026-09-13, applies clean |
| Diff | `AGENTS.md`, +9 −4. One file. No code. |
| Concern | One: the form `AGENTS.md` asks for when documenting `unsafe` |

## 2. What the rule says now, and what is in the tree

`AGENTS.md:53` requires *"a comment starting with `### Safety`"* for all
`unsafe` usage.

    git grep -c '### Safety' upstream/master -- '*.rs'                    ->   0
    git grep -c '// SAFETY'  upstream/master -- '*.rs'                    -> 144
    git grep -cE '^[[:space:]]*(///|//!)[[:space:]]*#+ Safety' \
            upstream/master -- '*.rs'                                     -> 149

Controls for those counts. A zero from a search that cannot see is
indistinguishable from a zero over a clean tree: earlier today a `-lE` search
for a PCRE word boundary returned 0 files over this same tree, where 589
contain the word, because that escape means nothing in POSIX ERE.

    git grep -l  'unsafe'        upstream/master -- '*.rs' | wc -l        -> 589 files
    git grep -c  '##### Safety'  upstream/master -- '*.rs'                ->   0

Of the 149 doc sections, **141 are `/// # Safety`**, 2 are `//! # Safety`, and
1 is `/// ### Safety` — and that one is not upstream at all, see §6.

## 3. Why the heading is not cosmetic

`kernel/src/lib.rs:94` carries `#![deny(clippy::missing_safety_doc)]`. That
lint requires a `# Safety` heading. So the rule as written asks for a form the
kernel's own lint does not accept.

`kernel/src/lib.rs:92-93`, verbatim:

    // `clippy::missing_safety_doc`: Our goal is to apply this in all of Tock,
    // but as of September 2026 we are starting with the kernel crate.

Elsewhere the lint is off: `Cargo.toml:249` sets `missing_safety_doc = "allow"`
workspace-wide, and `clippy.toml:13` records the exception as *"(allowed in
Tock, except kernel)"*.

**The two forms answer different questions.** `# Safety` on a `pub unsafe fn`
tells a *caller* what they must guarantee. `// SAFETY:` above an `unsafe` block
tells a *reader* why that operation is sound. One rule covering both is why it
reads as hard to follow.

## 4. AI-use disclosure — the three things the policy requires

State these in your own words; I cannot write the disclosure.

1. **Which tool.** Claude Opus 5 (1M context), via Claude Code. The policy says
   to name the specific tool and model, not a placeholder.
2. **What portion it produced.** The whole patch: a 9-line replacement of one
   bullet in `AGENTS.md`. No code. It also produced the commit message, which
   `AGENTS.md:32-38` permits provided the `Co-Authored-By` trailer is present —
   it is, on `104b137ab`.
3. **How the output was reviewed.** Whatever you actually did. What exists on
   my side: every count above re-run on `upstream/master` rather than a working
   branch, each with a control; the `### Safety` claim corrected once after the
   first counts were taken on the wrong tree (§6); the kernel lint located and
   read rather than assumed.

## 5. House constraints that have cost PRs here

- **Length matches the change.** bradjc on #5086: *"far too long for a 3 byte
  change ... makes this PR much harder to review."* Merged bodies here run
  about 1,000 characters. This is a one-file prose change.
- **One concern.** ppannuto, #5126. This has one.
- **Never open it as a draft.** #5150 and #5154 were closed as drafts and could
  not be reopened — tested in the browser and the API.
- **Every closed PR in this queue was closed for its description, not its
  change** — #5104, #5150, #5154.

## 6. Not established, and one correction

- **The first counts were wrong and the error is worth knowing.** They were
  taken in a checkout sitting on `learning/series` and came out 133 / 141 / 1.
  The "1" was `boards/raspberry_pi_pico_2/src/lib.rs:221` — **our own file,
  which does not exist upstream**, written 2026-08-29 by following this rule
  literally. On upstream the mandated form appears nowhere at all.
- **Why the rule was written this way is not established.** I did not look for
  the commit or discussion that introduced it.
- **Nothing was run.** No code changed, so there is nothing to build or test
  beyond the license checker, which passes.
- **Whether maintainers want the two forms named separately, or the rule
  simplified some other way, is theirs to decide.** The patch preserves their
  substance word for word and renames only the form.
