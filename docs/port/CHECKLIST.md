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
| 8 | Soundtracks | not yet (stage 2) |
| 9 | UI | not yet (stage 3) |
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
