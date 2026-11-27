# Squeaks72/romarrng

Tim's personal fork of [BlizzHacker/romarr](https://github.com/BlizzHacker/romarr).
It is not a GitHub fork, and nothing from it goes back upstream: no PRs and no issues.

## Branches

- `upstream` mirrors upstream's `main` exactly. Nothing is ever committed to it.
- `main` is the default branch: upstream plus the fork's own features, kept current by
  merging upstream into it (merging, not rebasing).
- `legacy-romarrng-main`, `on-upstream`, `soundtracks*` are history from before the
  port onto upstream. They are kept for reference and not built.

## Automation

- `.github/workflows/fork-sync.yml` runs at 22:21 and 01:45 UTC. It merges upstream/main
  into `main`, runs the test suite, pushes `main`, keeps upstream's workflows disabled, and
  mirrors `upstream`. A conflict or a failing suite stops the run without pushing.
- `.github/workflows/fork-build.yml` runs on every push to `main`. It tests, builds
  linux/amd64, smoke-boots the image, and publishes `ghcr.io/squeaks72/romarrng:latest`
  and `:v<upstream>-tim.<sha>`.
- Upstream's `docker.yml`, `windows.yml` and `cartridge-windows-proof.yml` stay disabled.
- A nightly caretaker session checks both workflows, and repairs a failed sync.

## What the fork carries

Upstream 1.11.0 (Nov 2026) adopted most of the fork's earlier work: soundtracks, the
Switch Updates & DLC report and attach, wishlist monitoring and game pages, download
progress, compressed TAR imports, NTSC/PAL and per-console formats, and plugin start-up
hardening. Those are now upstream's versions; the fork's own copies were dropped.
What the fork still carries on top of upstream:

- Extras: DLC, update, manual (and patch/hack/mod/demo/translation/prototype) cards on the game page,
  filled from indexer torrents, the Internet Archive, a pasted link or an uploaded file, through RomM's
  upload API; see docs/EXTRAS.md
- The library is re-read from the server hourly by default (`ROMARR_LIBRARY_REFRESH_SECONDS`)

## Conflict policy

When upstream adds functionality that overlaps something the fork carries, upstream
wins: the fork's version is dropped, not merged alongside upstream's. The fork keeps
only work that has no counterpart upstream. For example, upstream's saved-region fix
(#139) replaced the fork's `_region_names` helper in Nov 2026. In Nov 2026 upstream 1.11.0 likewise
replaced the fork's soundtracks, Switch report, monitoring/game page, Add New/Interactive
Search merge, platform picker, queue ETA, tar unpacking, video-standard/format preferences
and the Landlock/setuid plugin launcher.
