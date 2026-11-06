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

## Unpacking (item 7)

* `is_archive_name` / `MAX_ARCHIVE_DEPTH` / `_import_nested` ported onto upstream's `import_rom`
  (which has `platform_folders`; ROMarrNG's `folder_name`/`switch_index`/`route_switch_catalog` do not
  exist upstream and were not added). Single-archive directory unwrapping and digital set names also
  use `is_archive_name` so `.tar.gz` is handled everywhere `.zip` is.
* Upstream refuses a PS2/GameCube/Xbox disc image under 8 MB; the ported test uses a 9 MB image.

## Switch groundwork (item 6, part 1)

* `titled.py` is taken from ROMarrNG minus its SeerrNG `collection_plan`: upstream still classifies
  DLC as "low 12 bits <= 0xFF", which is wrong (DLC lives at base + 0x1001..0x1FFF, and `base_tid_of`
  must mask 13 bits). The Switch report and the attach-into-game-folder logic depend on the fix.
  `requests` replaces urllib there, and TitleDB product-key records are read by their `id`.
