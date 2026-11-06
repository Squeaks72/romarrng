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

## Switch report (item 6)

* `switch_report.py` is copied unchanged. The service uses upstream's `self.titled` (built at startup by
  `reload_titled`) instead of ROMarrNG's lazy `ensure_titled`, which does not exist upstream. Switch
  folders are resolved through `platform_dir` with the configured `platform_folders` and library layout,
  rather than a hard-coded `<library>/switch`.
* Upstream's `import_rom` has no Switch catalog routing (`route_switch_catalog`, `switch_updates_dir`);
  only the attach-into-game-folder rule (`switch_attach_dir`, update/ and dlc/) was ported.
* TitleDB names (needed for the full DLC list) stay opt-in via `TITLED_NAMES=1`; Tim's Unraid template
  sets it with a 1536m memory limit. That is a deployment setting for the ops stage, not code.

## Plugin confinement (item 1)

What upstream had: `hub._plugin_env` already used an environment allowlist, `rom_hub`'s own
`plugin_environment` allowlist covers in-process search/fetch, and `ROM_HUB_ALLOW_UNSANDBOXED` was only
set when the seccomp probe failed (not unconditionally). But a plugin still ran as ROMarr's own uid and
could read `/config/romarr.json` (every credential ROMarr holds), and the library username/password were
handed to every plugin. Neither is acceptable (Tim's hard rule), so:

* Landlock runtime ported from ROMarrNG (`plugin_runtime/landlock.py`, `scratch.py`, `syscall_guard.py`,
  `sitecustomize.py`) and the hub wrapper (`_install_plugin_runtime_hardening`: trusted `-S` bootstrap,
  private tmpfs scratch, Popen guard) is installed before `search`, `fetch` AND upstream's
  `resolve_torrents` (which also spawns plugin processes and does not exist in ROMarrNG).
* Where the kernel has no Landlock (Unraid) plugins run as uid 10001 through the setuid helper
  `docker/plugin-launch.c` (installed 4750 root:PGID by the entrypoint). `sitecustomize` fails closed if the
  child is root or can read the state file; `hub.uid_isolation_state()` proves the helper by running it.
  The state file is 0600 because `Store.save` writes it through `mkstemp`.
* Fail closed: with no confinement available, plugin calls are refused unless the operator sets
  `ROMARR_ALLOW_UNSANDBOXED_PLUGINS=1` (upstream silently fell back to unsandboxed). That variable is a
  deliberate, loud operator choice and is the ONLY way a plugin can run with ROMarr's privileges.
* Library credentials are withheld from plugins unless `ROMARR_PLUGIN_BACKEND_CREDENTIALS=1`.
* `/api/v1/hub/status` gains `isolation` (`uid` | `landlock` | `none`).
* `tests/conftest.py` stubs `uid_isolation_state` so tests see the same answer everywhere.
* NOT ported from ROMarrNG's hub: passing `prepare_assets`/`prepare_secrets` (plugin data assets and
  secret config) to `PluginProcess` - upstream does not do it and it is outside the confinement brief; the
  confinement code reads `process.data_assets` if present.
* Dockerfile (Alpine): the C helper is compiled in the existing builder stage. Dockerfile.browser (Debian,
  single stage upstream) gets a small `launcher` stage so the runtime carries no compiler.
* Plugin scratch requires a finite tmpfs for /tmp or /dev/shm (`scratch.tmpfs_root`); on Unraid run the
  container with `--tmpfs /tmp` or the sandbox probe reports "unavailable" (ops stage).
* The plugin uid needs read access to the plugin directory under `$ROM_HUB_HOME` (group/other readable;
  default UMASK 002 satisfies this).
