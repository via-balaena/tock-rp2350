# tock-rp2350

Source for a single-page map of the Tock/RP2350 work: what has merged upstream,
what is open, what is broken and known, and what is not done.

## How it works

`index.html` is generated. Do not edit it — edit `build.py` and rebuild.

    ./build.py              # fetch from GitHub, write data.json and index.html
    ./build.py --offline    # rebuild from the cached data.json, no network

Pull request state, sizes, dates, review decisions and commit lists are read
from the GitHub API at build time. Everything else — the prose, the defect
list, the userspace and documentation tracks — lives in the dictionaries at the
top of `build.py`.

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
