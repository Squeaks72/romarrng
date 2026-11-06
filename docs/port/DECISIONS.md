# Port decisions

## Scoring (item 2)

* Upstream already has `preferred_regions`, per-platform overrides, `region_scores` and a strict
  `region_mode` (in `selection.judge`, scoring `40*(n-rank)/n`). Tim's `ReleaseProfile.regions`,
  `region_strict` and `region_points` hook were therefore NOT ported; upstream's implementation
  satisfies the behaviour (40/30/20/10 for the default four-region list).
* One real bug in upstream was fixed instead: the settings page and the default store the list
  capitalised (`["USA","World",...]`) while `detect_regions` returns lower case, so a custom order
  never matched and strict mode refused every release including USA. `selection._region_names`
  lower-cases the list and resolves aliases (`us`, `eu`, `jp`, `pal`, ...). `ReleaseProfile.preferred_regions`
  itself is stored as written (upstream tests assert that).
* Video standard (NTSC/PAL, +/-30, strict refusal) and per-console `preferred_formats` (30/20/10) are
  added to upstream's `ReleaseProfile`; video standard can also be set per platform via `platform_profiles`.
* `title_matches` is whole-word, as in Tim's version.

## Monitoring / lookup (item 4)

* Upstream has no IGDB catalog search (that is ROMarrNG's SeerrNG catalog). A small
  `igdb_catalog_*` set was added to `metadata.py` (platforms + title search + row mapping) and
  `igdb_query` gained `strict=` so a failed lookup is reported instead of reading as "no games".
  The search never sends `sort` (IGDB answers 406).
* `ROMarr._title_key` (compact, accent-folded) is a staticmethod on the class and is distinct from the
  module-level `_title_key` (space-separated words) that upstream uses for matching.

## Secrets (item 5)

* `import_lists` masking reuses upstream's `LIST_SECRETS`; metadata providers / connections use the
  same field sets as their dedicated endpoints. `PUT /api/v1/config` runs `restore_masked_items` first.
