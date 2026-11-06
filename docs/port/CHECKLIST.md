# Port checklist (Tim's ROMarr features onto BlizzHacker/romarr)

Baseline on upstream/main: 4 failed, 2735 passed, 2 skipped (see baseline-failures.txt;
environment-dependent: no DNS for romm.internal, sandbox is a docker env).

| # | Feature | Status |
|---|---|---|
| 1 | Plugin confinement (uid helper + Landlock + env allowlist) | not yet |
| 2 | Scoring (video standard, formats, regions, whole-word titles) | not yet |
| 3 | Queue (progress, queue_view, Fails., duplicate grab guard) | not yet |
| 4 | Monitoring / wishlist / lookup / game detail | not yet |
| 5 | Secret masking | not yet |
| 6 | Switch report + attach | not yet |
| 7 | Unpacking (tar family, nested) | not yet |
| 8 | Soundtracks | not yet (stage 2) |
| 9 | UI | not yet (stage 3) |
| 10 | Ops | not yet (end stage) |
