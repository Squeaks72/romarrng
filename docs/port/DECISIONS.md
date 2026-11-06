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

## Queue (item 3)

* Upstream tags every qBittorrent add with `romarr-<hex>` and stores `download_id = qbit-tag:<tag>`.
  `QBittorrent.progress()` therefore also returns each torrent's tags, and `queue_view` matches a row in
  this order: tag, info-hash (`download_id` or `release_id` `btih:`), then release name
  (`match_torrent_by_name`). Clients are keyed by upstream's `romarr_id` / `QueueItem.download_client`
  (ROMarrNG used `config_id` / `download_client_id`).
* `last_reject` on `QBittorrent` is thread-local like `last_job_id`. A "Fails." body is only set on `add()`
  (URL/magnet); `add_torrent_file` already confirms by tag.
* `normalise_infohash` was added to `profiles.py` (base32 -> hex); `release_id` is unchanged so existing
  blocklist ids stay valid.
