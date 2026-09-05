# tock-rp2350

Source for a single page that draws the Tock/RP2350 work as a graph: one column
per pull request, every commit as a node, arrows for what depends on what.

It exists to answer a specific review comment on #5126 — *"I'm thoroughly
confused... it doesn't seem like there is a clear testing/bring up strategy"* —
and its two halves answer the two halves of that. The columns show which commits
belong to which pull request, which GitHub cannot show when a stack lives in a
fork. The badge on each node shows how that change is verified.

## How it works

`index.html` is generated. Do not edit it — edit `build.py` and rebuild.

    ./build.py              # fetch from GitHub, write data.json and index.html
    ./build.py --offline    # rebuild from the cached data.json, no network

Structure is derived, never asserted:

- **Nodes** are the distinct commit headlines across every pull request.
- **Edges** are commit order inside each branch, plus the handful of real
  cross-branch dependencies listed in `EXTRA_DEPS`.
- **Which pull requests a commit belongs to** falls out of the same data, so a
  commit shared by two branches is drawn as shared without anyone saying so.
- **"These two branches collide"** comes from intersecting their file lists.

Only the short node labels, the verification badges and the prose are
hand-written, in `WORK` and the dictionaries above it. A commit that is fetched
but missing from `WORK` still renders, unlabelled, and the build prints its
name — new work must show up on the page rather than vanish because the table
was not updated.

The split is the point. A hand-kept list of pull request numbers goes stale
silently, and a page whose whole job is to be trusted cannot afford that. Run
the build after anything merges.

Requires the `gh` CLI, authenticated.

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
