# Squeaks72/romarrng

Tim's personal fork of [BlizzHacker/romarr](https://github.com/BlizzHacker/romarr).
It is not a GitHub fork, and nothing from it goes back upstream: no PRs and no issues.

## Branches

- `main` mirrors upstream `main` exactly. Nothing is ever committed to it.
- `tim` is the default branch: upstream plus the fork's own features, kept current by
  merging upstream into it (merging, not rebasing).
- `legacy-romarrng-main`, `on-upstream`, `soundtracks*` are history from before the
  port onto upstream. They are kept for reference and not built.

## Automation

- `.github/workflows/fork-sync.yml` runs at 22:21 and 01:45 UTC. It merges upstream/main
  into `tim`, runs the test suite, pushes `tim`, keeps upstream's workflows disabled, and
  mirrors `main`. A conflict or a failing suite stops the run without pushing.
- `.github/workflows/fork-build.yml` runs on every push to `tim`. It tests, builds
  linux/amd64, smoke-boots the image, and publishes `ghcr.io/squeaks72/romarrng:latest`
  and `:v<upstream>-tim.<sha>`.
- Upstream's `docker.yml`, `windows.yml` and `cartridge-windows-proof.yml` stay disabled.
- A nightly caretaker session checks both workflows, and repairs a failed sync.

## What the fork carries

Ported from the original romarrng onto upstream (Nov 2026):

- Soundtracks: soundtrack sources, a music library root, a RomM write token, the
  `/api/v1/soundtracks/*` API, and the Soundtracks page and game-page card
- Switch Updates & DLC report: gap map and badge, ignore-DLC setting, update and DLC
  files attached into the game folder, TitleDB loaded on first use
- Unpacking for tar-family archives and for archives nested up to two levels deep
- Monitoring and wishlist store; lookup, add, monitor and game-detail endpoints; IGDB
  catalogue search
- UI: Add New merged with Interactive Search, the game page, a search palette (Ctrl K),
  a searchable platform picker, and queue progress with ETA
- NTSC/PAL video standard, preferred formats per console, whole-word title matching
- Plugin confinement without Landlock, through a setuid uid-10001 launcher

## Conflict policy

When upstream adds functionality that overlaps something the fork carries, upstream
wins: the fork's version is dropped, not merged alongside upstream's. The fork keeps
only work that has no counterpart upstream. For example, upstream's saved-region fix
(#139) replaced the fork's `_region_names` helper in Nov 2026.
