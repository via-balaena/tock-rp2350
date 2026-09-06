# tock-rp2350

Source for a single page about Tock on the Raspberry Pi Pico 2 and Pico 2 W. It
has two subjects: **the chip** — what Tock can drive on an RP2350 and how a
system call reaches a register — and **the work**, drawn as a graph with one
column per pull request, every commit a node, arrows for what depends on what.

The work half exists to answer a specific review comment on #5126 — *"I'm
thoroughly confused... it doesn't seem like there is a clear testing/bring up
strategy"* — and its two halves answer the two halves of that. The columns show
which commits belong to which pull request, which GitHub cannot show when a
stack lives in a fork. The badge on each node shows how that change is verified.

The chip half exists because the same question has a version nobody had drawn
either: what actually works on this board today, and what a process can call.

## How it works

`index.html` is generated. Do not edit it — edit `build.py` and rebuild.

    ./build.py              # fetch from GitHub, write data.json and index.html
    ./build.py --offline    # rebuild from the cached data.json, no network

The page is the source of truth for this work — for the maintainers reading it,
for whoever is writing the userspace half, and for me. That only holds if it is
derived rather than remembered, so:

- **Nodes** are the distinct commit headlines across every pull request.
- **Edges** are commit order inside each branch, plus the handful of real
  cross-branch dependencies listed in `EXTRA_DEPS`.
- **Which pull requests a commit belongs to** falls out of the same data, so a
  commit shared by two branches is drawn as shared without anyone saying so.
- **"These two branches collide"** comes from intersecting their file lists.
- **The evidence dropdown** on each unsent branch derives its commit list,
  diffstat and base; only the numbered facts above them are hand-written, in
  `FACTS`.
- **The queue is drawn as a pipeline**, one column per stage: on the fork, in
  review, approved, merged, closed. The columns are deliberately not balanced.
  A first column five times the height of the rest is the whole point of
  drawing it — the constraint is not how fast the work goes, it is how fast it
  is asked for. Dashed arrows are the couplings in `QUEUE_DEPS`, the one
  hand-written part, and both ends of each are checked to exist.
- **The queue** is read from the working clones listed in `LOCAL`: every branch,
  how far ahead of upstream it is, whether it is pushed, and which pull request
  it matches by shared commits. A clone that is missing is skipped, and the
  survey is cached into `data.json` so `--offline` still renders.

### The chip half

Read from the Tock working clone at build time, at two refs — `upstream/master`
and the bench branch that has everything merged. If the clone is missing, these
sections are skipped and the rest of the page still builds.

- **The list of hardware blocks is the chip's own.** Every chip crate has a
  `resets.rs` with one bit per resettable block, so "how many blocks does an
  RP2350 have" is a question Tock's source already answers — 23, against the
  RP2040's 21. A cell is filled when a driver module for that block exists.
- **What a process can call** is read from every `with_driver` arm on a board.
  Boards delegate: `raspberry_pi_pico/src/main.rs` answers one driver number
  and passes the rest to a base platform *in another crate*, so reading the one
  file reports one driver on a board that exposes ten. Both hops are followed.
- **The trace from a system call to a register** is derived rung by rung: the
  driver number from the enum that assigns them, the capsule from the board's
  own `with_driver`, the kernel interface from what that capsule imports, the
  chip driver from the crate implementing it, the registers from its
  `register_structs!`.
- **One register opened up.** The bottom rung draws a register as its bits,
  high to low, from `register_bitfields!`. The gaps are drawn as gaps: a
  control register is mostly nothing, and a picture that packs the named
  fields together tells you the opposite of what the silicon does.
- **The forty pins** are read the same way. The header's shape is the board's
  form factor and is written down; every role on it comes from that board's
  own source — the binding beside the pin, or the component being built with
  it. Recursion into a base board reads its `lib.rs` and never its `main.rs`:
  `raspberry_pi_pico_2/lib.rs` is shared setup that the Pico 2 W runs, but
  `raspberry_pi_pico_2/main.rs` is a *different binary* with its own userspace
  GPIO table, and reading both put the standalone Pico 2's pins on the W.
- **The capsule-to-chip join is on what a driver *implements*, not what it
  names.** `pio.rs` imports `hil::gpio` to configure pins; joining on names put
  the GPIO capsule above the PIO block, on the same page that lists a userspace
  PIO driver as not done.
- **The two chips are kept apart.** Taking whichever file came first printed the
  RP2040's ADC base under the RP2350's block — wrong in a way only somebody
  with the datasheet open would catch. The RP2040's driver is still shown, as
  the RP2040's, because for a block the RP2350 lacks it is what would be ported.

Only what each block *is for* is hand-written, in `BLOCKS`, `PLUMBING` and
`MODULE_BLOCK`. A block or a module missing from those fails a check.

Only the short node labels, the verification badges and the prose are
hand-written, in `WORK` and the dictionaries above it. A commit that is fetched
but missing from `WORK` still renders, unlabelled, and the build prints its
name — new work must show up on the page rather than vanish because the table
was not updated.

The split is the point. A hand-kept list of pull request numbers goes stale
silently, and a page whose whole job is to be trusted cannot afford that. Run
the build after anything merges.

Requires the `gh` CLI, authenticated.

## Checking

    ./check.py            # everything, including a live fetch
    ./check.py --offline  # skip the live fetch

Thirteen checks, each proven to fail when it should rather than only observed
to pass:

| check | catches |
|---|---|
| `drift` | `index.html` is not what `build.py` produces — hand-edited, or a rebuild is pending |
| `fresh` | the cached data disagrees with GitHub now. A merged pull request still drawn as open is the page lying |
| `annotated` | a commit is on the page with no label or verification badge |
| `intent` | a local branch is in the queue with no recorded intent |
| `facts` | a finished, unsent branch has no evidence recorded |
| `refs` | a hand-written `#1234` in the prose names something that does not exist |
| `private` | an address, MAC, serial path or home directory reached the HTML |
| `contrast` | a text-on-surface pair fell below 4.5:1 — and a surface it *cannot read*, which is how most of this page went unchecked for a fortnight: `--panel:#fff` is three-digit hex, the parser wanted six, and every pair drawn on the panel was skipped in silence |
| `blocks` | a hardware block or a driver module reached the tree and not the page. The quiet half: a module in neither table is simply absent from the grid, so a port could land and the page would go on reporting the old number |
| `nav` | a rail link points at a section that is not there, or a section is missing from the rail. Invisible to everything else — the page builds and the link just does nothing |
| `grid` | a coverage row carries the wrong number of cells. It does not look broken; it shifts every later cell one column left |
| `trace` | a block has no trace panel, or more than one is visible at rest, which is what a reader with no JavaScript is shown |
| `styles` | a class in the markup that no rule matches, or a rule no markup uses. Both have shipped here |
| `pins` | a pin used for something `PIN_ROLE` cannot name, so the map would render a raw `into_cs`; or a name no board uses any more |
| `header` | the forty-pin table is internally consistent. A typo, not a pinout — nothing here can tell you the pinout is *right* |
| `pinmaps` | the board tabs and the pin maps agree, and one map shows at rest |
| `bits` | a register drawn as bits that does not add up to the register's width. The strips stretch to fill the row, so a mis-read field still looks like a register — only the sum shows it |
| `queue` | the drawn queue and the written queue disagreeing: a stage heading counting something other than what is under it, a card matching nothing else on the page, or a `QUEUE_DEPS` end naming nothing so its arrow is silently not drawn |

Run it before every push. Most failures are fixed by running `./build.py`.

### Driving the page

A final check runs the page in a real DOM and asserts its interactions,
which is the closest thing here to looking at it. It needs node and jsdom, and
is reported as skipped rather than failed without them:

    npm install jsdom
    node drive.js index.html     # or just ./check.py, which runs it

It earned its place immediately. The scrollspy threw on any browser without
`IntersectionObserver`, and because the page ships one script, that single throw
silently took the search, the key bindings and the whole palette down with it.
Nothing that reads the markup as text could have seen that.

**What no check covers: nobody has looked at the page.** There is still no
browser on the machine it is built on. The interactions are now driven, and the
grid's shape, its colour contrast and its class coverage are computed — but
jsdom has no layout engine, so nothing here has ever measured a pixel. Spacing,
wrapping and overlap remain unverified.

## Publishing

The repository is set up to serve from its root:

    git remote add origin git@github.com:via-balaena/tock-rp2350.git
    git push -u origin main

Then in the repository's settings, Pages → Build and deployment → Deploy from a
branch → `main` / `/ (root)`. `.nojekyll` is already present so the site is
served as plain files.

## What is deliberately not on the page

- **No bench details.** No addresses, hostnames, MACs, network layout or serial
  device paths. The bench is described only as what it is: a Raspberry Pi that
  flashes the board and holds its serial line.
- **No scan results.** The Pico 2 W's WiFi scan is cited as a result, never with
  the networks it saw.
- **Nothing reported privately.** One report went to the project's security
  contact and is not public; it is not listed here, and adding it would be a
  disclosure decision rather than a documentation one.

Check the first two before every push:

    grep -nEi '192\.168|10\.[0-9]+\.|[0-9a-f]{2}(:[0-9a-f]{2}){5}|ttyACM|/home/' index.html
