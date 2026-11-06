# Port checklist (Tim's ROMarr features onto BlizzHacker/romarr)

Baseline on upstream/main: 4 failed, 2735 passed, 2 skipped (see baseline-failures.txt;
environment-dependent: no DNS for romm.internal, sandbox is a docker env).

| # | Feature | Status |
|---|---|---|
| 1 | Plugin confinement (uid helper + Landlock + env allowlist) | done (Python side tested with fakes; C helper copied verbatim, NOT compiled or run here: no gcc in the sandbox, no Docker; Dockerfile, Dockerfile.browser and entrypoint wired) |
| 2 | Scoring (video standard, formats, regions, whole-word titles) | done (regions: upstream implementation kept + case fix, see DECISIONS) |
| 3 | Queue (progress, queue_view, Fails., duplicate grab guard) | done (matches by qbit tag, infohash, then name; UI is stage 3) |
| 4 | Monitoring / wishlist / lookup / game detail | done (API + store + IGDB search; UI is stage 3) |
| 5 | Secret masking | done |
| 6 | Switch report + attach | done (API, store setting ignored_dlc, counts().switchgaps; UI is stage 3; TITLED_NAMES=1 + memory 1536m belong to the ops stage) |
| 7 | Unpacking (tar family, nested) | done |
| 8 | Soundtracks | done (backend, docs and tests; UI card/page is stage 3) |
| 9 | UI | done (adapted): stages 3a + 3b; only the items under "Stage 3b result" are unverifiable without a live install |
| 10 | Ops | not yet (end stage) |

## Stage 1 result (backend, items 1-7)

Tests: baseline 4 failed / 2735 passed / 2 skipped; now 4 failed (the same four) / 2839 passed / 3 skipped
(the extra skip is the Landlock kernel test, the sandbox has no Landlock).

## Hand-over notes for later stages

* Stage 2 (soundtracks): not started. Needs `Romm.write_token` (+ `WRITE_SCOPES`) in `clients.py`, the
  `soundtrack_sources` / `music_library_root` defaults in `store.py`, the soundtrack service methods and
  `_soundtrack_reply` + routes in `app.py` (the block was deliberately left out of the ported
  `lookup`..`switch_gap_count` section), openapi entries, docs/SOUNDTRACKS.md and the tests.
  Tim's `app.diff` pieces are reproducible with `git diff snapetech/main origin/main -- romarr/app.py`.
* Stage 3 (UI): every backend call the UI needs exists: `/api/v1/lookup`, `/game/detail`, `/wanted/add`,
  `/wanted/monitor`, `/switch/updates|gaps|ignore`, `/queue?refresh=1` (items have `progress`, `eta`,
  `speed`, `dl_state`, `waiting`; response has `at`), `/system/counts.switchgaps`, `/hub/status.isolation`,
  settings `romm_public_url`, `video_standard`, `video_standard_strict`, `preferred_formats`, `ignored_dlc`.
  `GET /api/v1/wanted/missing` rows carry `monitored`. Settings secrets come back as `********`.
* Ops stage: set `TITLED_NAMES=1` and ~1536m memory for the Switch DLC list; run with `--tmpfs /tmp`
  (plugin scratch needs a finite tmpfs); docs for `ROMARR_ALLOW_UNSANDBOXED_PLUGINS`,
  `ROMARR_PLUGIN_BACKEND_CREDENTIALS`; verify `docker/plugin-launch.c` compiles in the image build
  (could not be compiled in stage 1).

## Stage 2 result (soundtracks, item 8)

* `romarr/soundtracks.py`, `docs/SOUNDTRACKS.md` and the five test files are Tim's, unchanged apart from the
  test waits below. `Romm.write_token` / `WRITE_SCOPES` (clients.py) are identical: upstream's `Romm` signs in the
  same way (password grant, `api_token` honoured), so the write token is a second grant with `roms.read roms.write`,
  cached apart from the read-only token and never logged.
* app.py: soundtrack service methods, `_soundtrack_reply`, all 11 routes; `game_detail` already exposes `rom_id`.
  New module-level `import requests` (used by `_soundtrack_reply`). openapi entries and the settings defaults
  `soundtrack_sources` / `music_library_root` added.
* Test fix: the job-wait helpers now also wait for `finished` (stamped after the undo journal is written);
  `test_music_library_search_and_add` was flaky under CPU load (undo ran before the journal, `removed` was 0).
  The same race exists in Tim's main; production code is unchanged.

## Stage 3a result (UI, item 9 first half)

Done (all in `romarr/ui.py`, plain English strings, no i18n catalogue):

* 9.1 `pickerHtml`/`bindPicker`/`platPickerItems` + `.pp*` CSS; library platform filter is the picker (chip wall gone),
  compact header `.libstats` / `.lfrow`; library tiles open `#game/<slug>/<id>`.
* 9.2 `go('page/arg/...')`, `ROUTE_ARGS`, `ROUTE_SPEC` (hashchange only renders for changes made outside `go`),
  `routeEpoch` (renderers get `renderEpoch` and may drop a stale render), `#search` -> `#add`, `game` lights Library.
* 9.3 Add New (IGDB cards, state badges, `addDialog`, exact-title fallback, `ADD_PREFILL`), nav entry for Interactive
  Search removed, shared `renderReleases(out,game,platform)`.
* 9.4 `RENDER.game` (cover, facts, Open in RomM, monitor toggle, Add to Wanted/Search now, interactive search panel,
  shelf editor via the existing `shelfEditor`, downloads, history, `#g-alert`, `#g-swu`, `#g-snd`).
* 9.5 Missing: monitored On/Off column, game links, All / Monitored / Wishlist tabs (`MISSING_VIEW`).
* 9.6 Search palette (Ctrl/Cmd+K, `/`, top-bar button, `PALETTE_KEYWORDS`); Filter box only on Games.
* 9.7 Tests: `tests/test_ui_picker.py`, `tests/test_ui_addnew.py`; adjusted `test_ui_pages.py`, `test_ui.py`
  (#121/#122 assertions about the old Add/Interactive Search selects), `test_interactive_search.py`.

Stage 3b must still do (item 9 remainder): Soundtrack card (fill `#g-snd`; hook comment in `RENDER.game`), Switch
"Updates & DLC" card in `#g-swu` + `#g-alert` banner, library Switch banner + tile `.gap` badges (CSS `.tile .gap`,
`.alert-bar` already added) + nav badge, Switch Updates page (`RENDER.switchupdates`, nav entry, title in `go()`),
Soundtracks page (+ Duplicates tab), Queue page progress/ETA/Refresh, Profiles page (video standard, formats by
console, regions note), General "RomM address for links", Media Management unpacking help, Hub isolation banner.
Not verifiable here: real browser load (no Playwright in the sandbox); the JS was checked with `node --check`.

## Stage 3b result (UI, item 9 second half)

All in `romarr/ui.py`, plain English, no translation catalogue (`toast`, `confirm`, `fmtDate` instead of Tim's helpers).

* Game page: `soundtrackCard` (track count, Undo, Search with per-format Download, Open and manual links, music-library
  modal, `/soundtracks/jobs` progress polling until `state != running` AND `finished`, 409 `held_by` -> confirm -> `force:true`);
  `switchCard` (installed/latest, badge, Search buttons via `relBox`/`relOut`/`renderReleases`, per-DLC Search/Ignore,
  Ignore all N, Restore, POST `/switch/ignore`) and the `#g-alert` "Heads up" banner.
* `RENDER.switchupdates` (nav "Switch Updates & DLC", count key `switchgaps`), library banner + tile `.gap` badges from
  `/switch/gaps`, nav badge through the generic `data-ct` loop.
* `RENDER.soundtracks` with the Duplicates tab (scan, keep radio + Merge, Merged list + Undo, job follow).
* Queue: `.pbar`/`.pmeta` progress, ETA/speed, `QBIT_STATE`, "not in qBittorrent", Refresh (`?refresh=1`) + "Updated <time>",
  4 s refresh of only the progress cells (full redraw if rows changed), game name links to the game page.
* Settings: Profiles gets video standard + strict (global and per-platform) and the "File formats by console" editor
  (global; `preferred_formats`, `fmt-add` picker); regions are saved lower case and the default list is lower case;
  General "RomM address for links"; Media Management "Unpacking." help; Hub banner says uid isolation vs Landlock.
  `settingsPage` skips blank/`********` secret fields and `fld` never renders a masked value.
* Tests: `tests/test_ui_stage3b.py` (structure assertions + `node --check`); existing nav/renderer/title tests pass unchanged.
* Verified in headless Chromium (Playwright, throwaway script, not committed) with a faked API: every new page and both
  cards rendered with no JS errors. Not verifiable here: behaviour against a real RomM/qBittorrent (job polling timing,
  the 409 flow end to end).
