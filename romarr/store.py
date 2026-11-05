"""Persistence.

The *arr applications all keep the same things across a restart: what you
asked for, what happened to it, and how you configured the thing. ROMarr kept
all of it in memory, so a restart lost your history and your settings -- which
is the difference between a tool and a demo.

This is a JSON file with a lock rather than a database, and that is a
deliberate ceiling rather than an oversight: the entire working set is a few
thousand events, and an *arr that needs a database daemon to file ROMs is
harder to install than the thing it automates. If this ever outgrows a file,
the shape here (load / mutate / save under one lock) is the same shape SQLite
would want.

Writes are atomic -- written to a sibling temp file and renamed -- because the
alternative is that a crash mid-write leaves a truncated JSON file and the
service will not start again.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field, fields as dataclass_fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class StateUnreadable(RuntimeError):
    """The state file is there and we are not allowed to read it.

    Its own class rather than a bare RuntimeError so the entry point can tell
    this apart from a crash and print the fix instead of a traceback.
    """


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rows(raw: Any, cls: type) -> list:
    """Rebuild stored dicts into dataclasses, ignoring fields we do not know.

    `cls(**row)` raises TypeError on a key this version has never heard of,
    and that is a state file which cannot be loaded -- an install that will
    not boot because it was once run by a newer ROMarr. Dropping the unknown
    key loses the field and keeps the service.
    """
    known = {f.name for f in dataclass_fields(cls)}
    return [cls(**{k: v for k, v in row.items() if k in known})
            for row in (raw or []) if isinstance(row, dict)]


@dataclass
class Event:
    """One thing that happened, in the sense *arr means by History."""

    kind: str          # grabbed | imported | failed | ignored
    game: str
    platform: str
    release: str = ""
    detail: str = ""
    seeders: int = 0
    size: int = 0
    indexer: str = ""
    # Which library server received it. Empty for events that predate multiple
    # libraries, and for events that never reached one.
    library: str = ""
    at: str = field(default_factory=now_iso)


@dataclass
class WantedItem:
    """A request that has not been satisfied yet -- *arr's Wanted/Missing."""

    game: str
    platform: str
    added: str = field(default_factory=now_iso)
    attempts: int = 0
    last_error: str = ""
    # When the scheduler last searched for this automatically. Empty means
    # never, which makes a fresh request immediately eligible; together with
    # `attempts` it drives the re-search backoff, so a title that has failed
    # for months is retried weekly rather than hourly.
    searched_at: str = ""
    # Like Sonarr/Radarr: an unmonitored entry stays on the list but is skipped
    # by the missing-search sweep and the RSS watcher until it is monitored.
    monitored: bool = True


@dataclass
class QueueItem:
    """One download ROMarr is waiting on -- what *arr calls Activity.

    This used to live only in the service object, so a restart emptied
    Activity while the download client carried happily on seeding. Losing the
    rows lost the only record of which *game* a finished torrent belongs to:
    the import sweep matches a completed download to its queue row by release
    title, so after a restart it could no longer tell that
    `Super.Metroid.USA.zip` was the SNES request from an hour ago, and skipped
    the file it had just finished downloading.
    """

    game: str
    platform: str
    release: str
    seeders: int
    state: str                # queued | grabbed | imported | failed
    detail: str = ""
    at: str = field(default_factory=now_iso)
    # Identity of the release this row took, as profiles.release_id computes
    # it -- the infohash when the link carried one. Stored so a dead download
    # can be blocklisted by the same identity a later search will compute,
    # without persisting the download URL, which carries the indexer API key.
    release_id: str = ""
    indexer: str = ""
    size: int = 0
    # Whether a failure is the *release's* fault. "qBittorrent rejected it"
    # and "the archive held no ROMs" are; "no download client configured" is
    # not, and blocklisting a release because the operator has not set up a
    # client yet would punish the release for somebody else's mistake.
    release_fault: bool = False
    # Set once this row's release has been blocklisted, so the sweep that
    # retires dead downloads never does it twice.
    blocklisted: bool = False
    # SeerrNG's request identity, when ROMarr was dispatched by SeerrNG.
    external_request_id: str = ""
    # Exact imported destinations for this request, persisted across restarts.
    # Release filenames and console title IDs need not equal the catalog title.
    imported_paths: list[str] = field(default_factory=list)
    # Download client's id, when available, captured at handoff. History names
    # often differ from the indexer's release title; old rows fall back to name.
    download_id: str = ""
    # Scope client-generated job IDs; two clients can both report job "1".
    download_client_id: str = ""


@dataclass
class SeerrRequest:
    """Durable request identity shared with a SeerrNG instance."""

    external_request_id: str
    game: str
    platform: str
    catalog_provider: str = ""
    catalog_id: int = 0
    # Provider-scoped opaque identity for catalogs whose IDs are not numeric
    # (currently ROMarrNG DAT entries). `catalog_id` remains the IGDB field.
    catalog_key: str = ""
    platform_id: int = 0
    status: str = "accepted"
    error: str = ""
    updated_at: str = field(default_factory=now_iso)
    # Kept when reading the generic integration schema used by upstream
    # ROMarr. The richer ROMarrNG API still derives verified assets from the
    # import queue before exposing or streaming them.
    created_at: str = field(default_factory=now_iso)
    assets: list[str] = field(default_factory=list)
    # Content chosen beyond the base game. For a patch request:
    # {"kind": "patch", "projectId", "versionId", "keepOriginal", "state":
    # pending|preparing|prepared|failed, "output", "errorCode", "error"}.
    selection: dict = field(default_factory=dict)


# Defaults are spelled out here rather than scattered through the UI so a fresh
# install and a configured one disagree about nothing.
DEFAULT_SETTINGS: dict[str, Any] = {
    # How a friend's server reaches this one, e.g. https://romarr.example.com.
    # Peering is the only feature that needs ROMarr to know its own address:
    # an invitation carries it, and without one the friend who redeems the
    # invitation has nowhere to call back to.
    "public_url": "",
    # Where *your browser* reaches RomM, for "Open in RomM" links. Empty falls
    # back to the library connection address, which may be an address only the
    # server can reach.
    "romm_public_url": "",
    # Which sources a game page's Soundtrack card searches, comma separated.
    # Zophar's Domain and the Internet Archive; KHInsider and the rest are
    # behind bot challenges and are only ever linked, never scraped.
    "soundtrack_sources": "zophar,archive",
    # Where a regular music library is mounted (read-only) for "Use an album
    # from your music library" on a game's Soundtrack card. ROMarr only reads it.
    "music_library_root": "/music-library",
    # Read ROM hashes from the library server so netplay can match on bytes.
    # Daily and at startup; off only if you never want the traffic.
    "hash_index": True,
    # Media management
    #
    # Empty means "nobody has chosen one", which is what a fresh install is.
    # It used to default to /mnt/roms, and because the service treats a stored
    # path as an operator's decision that outranks the environment, that
    # default silently outranked LIBRARY_PATH and ROMM_LIBRARY on every install
    # -- making both documented variables do nothing at all. It looked correct
    # only because the default matched the path the docs used as an example.
    "library_path": "",
    # A shared sidecar root for cached metadata and artwork, mounted at the same
    # relative location on each frontend machine. Empty disables local publishing.
    "metadata_path": "",
    # Optional aliases for immediate folders under LIBRARY_PATH. Empty means
    # canonical platform slugs plus unambiguous ES-DE system folders.
    "platform_folder_mappings": {},
    # Optional roots from an existing ES-DE installation, each containing
    # per-system subfolders. ROMarr's shared output lives under metadata_path.
    "esde_gamelists_path": "",
    "esde_media_path": "",
    # Private local key authenticating rename history stored on the shared
    # metadata mount. Generated on first use and never writable through config.
    "_organizer_journal_key": "",
    # Switch update/DLC routing is explicit because TitleDB IDs come from
    # filenames and do not verify package bytes.
    "switch_auto_route": False,
    "switch_updates_dir": "Updates",
    "switch_dlc_dir": "DLC",
    # Where No-Intro/Redump DATs live, as ROMarr sees it. Applied through
    # reload_dats when saved from the UI, so the setting acts rather than
    # just sits.
    "dat_path": "",
    # Directory shape ROMs are filed in, matching the library server's own
    # setting. "flat" is <root>/<platform>/<rom> (RomM "Structure A"); "nested"
    # is <root>/<platform>/roms/<rom> (RomM "Structure B"). Overridable per
    # library on the Libraries page; this is the default for the primary one.
    "library_layout": "flat",
    # What to do with English fan translations in a 1G1R set:
    # exclude | fill | prefer | keep_both. See collections.TRANSLATION_POLICIES.
    # keep_both files the translation in the platform's Translations subfolder.
    "translation_policy": "exclude",
    # Optional https URL of a JSON patch catalogue (see docs/patch-catalogue.md).
    # Empty means only the local patch-catalog.d folder is read.
    "patch_catalog_url": "",
    # Which fan-translation languages the policy accepts. "en" preserves the
    # historical English-only behaviour; operators select their own codes
    # under Settings -> Media Management.
    "translation_langs": ["en"],
    # "prefer" keeps a title even when no dump matches the region list (the
    # historical fallback); "strict" treats the list as an allowlist.
    "region_mode": "prefer",
    # "ntsc" | "pal" | "" -- see profiles.ReleaseProfile.video_standard.
    "video_standard": "",
    # {platform slug: [extension, ...]} best first; see ReleaseProfile.formats.
    "preferred_formats": {},
    "video_standard_strict": False,
    "rename_on_import": True,
    "overwrite_existing": False,
    # Profile: for ROMs the meaningful axis is region and revision, not
    # bitrate -- this is the games equivalent of a quality profile.
    "preferred_regions": ["USA", "World", "Europe", "Japan"],
    "allow_beta": False,
    "allow_rom_hacks": False,
    # Acquisition
    "min_seeders": 1,
    "max_size_mb": 8192,
    "protocol": "torrent",       # torrent | usenet
    # Remote path mappings, the same concept Radarr and Sonarr expose.
    #
    # A download client reports the path it sees. When the client and this
    # service are different containers or hosts, that path means nothing here:
    # qBittorrent says /mnt/usb1/Downloads/game.zip and this process has that
    # volume mounted somewhere else, or not at all. Without a translation the
    # import fails with "download path does not exist" while the file is
    # sitting right there.
    #
    # Each entry is {"remote": "<what the client says>",
    # "local": "<what we see>"}. Optional client_id scopes a rule to one
    # configured download client; entries without it stay shared for existing
    # installs and paths common to several clients.
    "remote_path_mappings": [],
    # Import lists: titles fed into Wanted on the List Sync schedule. Each
    # entry keeps a ledger of what it already added, so a list re-syncing
    # never resurrects a title that was acquired and fulfilled.
    "import_lists": [],
    "list_sync_interval_hours": 6,
    # Download clients and indexers, each a list of stored configurations.
    #
    # These used to come from environment variables only, which meant the
    # Settings pages could show them and not change them -- you had to edit a
    # file and restart to add a client. On first run the environment is read
    # once to seed these, so an existing install keeps working, and after that
    # the store is authoritative.
    "download_clients": [],
    "indexers": [],
    # Behaviour
    "auto_import": True,
    "rescan_after_import": True,
    # Failed download handling, the same idea Radarr and Sonarr have: a
    # release that could not be downloaded is not one to choose again. When
    # on, a download that the client refused, that finished with no ROMs in
    # it, or that stalled is added to the blocklist and the next best release
    # is grabbed in its place. Without this the next missing/RSS sweep re-runs
    # the same scorer over the same results and picks the same dead file.
    "blocklist_failed_downloads": True,
    # How long a grabbed download may sit without finishing before it counts
    # as stalled, in minutes. 0 disables stall detection entirely, leaving
    # only outright failures to be retired. Generous by default: a large disc
    # image on a thin swarm is slow, not dead.
    "stalled_timeout_minutes": 180,
    # The clock. Zero disables a job; the scheduler reads these live, so a
    # change applies at the next tick without a restart.
    #
    # Import polls often because it is cheap and the person is usually
    # waiting; the missing search is hours apart because hammering indexers
    # for titles that were not there this morning is how trackers hand out
    # bans; RSS fills the gap between those sweeps by watching what is new
    # instead of asking again for everything.
    "auto_import_interval_minutes": 1,
    "search_missing_interval_hours": 12,
    "rss_sync_interval_minutes": 60,
    # Whether to ask github.com once a day if a newer ROMarr exists. Checking
    # is the whole feature -- nothing is ever downloaded or applied.
    "update_check": True,
}


class Store:
    """Everything ROMarr remembers."""

    # Past this the history file grows without bound and nobody reads the tail.
    MAX_EVENTS = 2000

    # The queue is live state, not a log: rows leave it when they import or
    # are cleared. The cap is a backstop against a runaway sweep filling the
    # state file, not an expected working size.
    MAX_QUEUE = 500
    MAX_SEERR_REQUESTS = 1000

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        # Deep, not shallow. DEFAULT_SETTINGS holds mutable lists
        # (download_clients, indexers, preferred_regions); a shallow copy hands
        # every Store the *same* list objects, so appending a client in one
        # place silently appends it everywhere -- including into the module
        # default, which then leaks into every Store created afterwards.
        self.settings: dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self.events: list[Event] = []
        self.wanted: list[WantedItem] = []
        self.queue: list[QueueItem] = []
        self.seerr_requests: list[SeerrRequest] = []
        self.load()

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as err:
            # Unreadable and unparseable used to share this handler, and they
            # are not the same failure. A file we cannot read is one that is
            # intact and belongs to somebody else -- typically a root-owned
            # romarr.json under a container running as PUID. Starting from
            # defaults recovers nothing there; it destroys. The next save
            # replaces the API key, the password hash and the whole history,
            # and the install comes back unclaimed, so whoever reaches the port
            # next gets to set the password. Refusing to start costs an outage
            # and loses nothing.
            raise StateUnreadable(
                f"{self.path} exists but cannot be read ({err}). This file "
                "holds the API key, the password hash and the request "
                "history; starting from defaults would overwrite it and leave "
                "the install unclaimed. Fix the ownership or permissions -- in "
                "Docker, PUID/PGID must own /config and everything inside it "
                "-- and start ROMarr again."
            ) from err
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as err:
            # A corrupt file must not stop the service from starting; the
            # defaults are always a usable configuration. Unlike the case
            # above there is nothing here to preserve -- the bytes no longer
            # parse, so no version of this file can be handed back.
            log.warning("could not read %s (%s); starting from defaults", self.path, err)
            return
        migrated_integration_requests = False
        with self._lock:
            # Merged rather than replaced, so a setting added in a later
            # version has its default instead of being absent.
            self.settings = {**copy.deepcopy(DEFAULT_SETTINGS), **(raw.get("settings") or {})}
            self.events = _rows(raw.get("events"), Event)
            self.wanted = _rows(raw.get("wanted"), WantedItem)
            # Absent in files written before the queue was persisted, which is
            # simply an empty queue -- the same thing those installs had after
            # every restart anyway.
            self.queue = _rows(raw.get("queue"), QueueItem)
            requests_by_id = {
                row.external_request_id: row
                for row in _rows(raw.get("seerr_requests"), SeerrRequest)
            }
            legacy_requests = self.settings.get("integration_requests")
            if isinstance(legacy_requests, list):
                # Upstream ROMarr 1.0 stored these rows inside settings under
                # `integration_requests`; ROMarrNG stores them at the top
                # level. Import them before dropping the legacy setting so an
                # existing install keeps its request and resume state.
                for item in legacy_requests:
                    if not isinstance(item, dict):
                        continue
                    external_id = str(
                        item.get("id") or item.get("external_request_id") or ""
                    ).strip()
                    platform = str(item.get("platform") or "").strip()
                    game = str(item.get("game") or item.get("name") or "").strip()
                    if not external_id or not platform or not game:
                        continue
                    updated_at = str(item.get("updated_at")
                                     or item.get("created_at") or now_iso())
                    status = str(item.get("status") or "accepted")
                    if status in ("accepted", "requested"):
                        status = "searching"
                    try:
                        catalog_id = int(item.get("catalog_id") or 0)
                        platform_id = int(item.get("platform_id") or 0)
                    except (TypeError, ValueError):
                        catalog_id = platform_id = 0
                    assets = item.get("assets")
                    migrated = SeerrRequest(
                        external_request_id=external_id,
                        game=game,
                        platform=platform,
                        catalog_provider=str(item.get("catalog_provider") or ""),
                        catalog_id=catalog_id,
                        catalog_key=str(item.get("catalog_key") or ""),
                        platform_id=platform_id,
                        status=status,
                        error=str(item.get("error") or ""),
                        updated_at=updated_at,
                        created_at=str(item.get("created_at") or updated_at),
                        assets=([str(path) for path in assets
                                 if isinstance(path, str)]
                                if isinstance(assets, list) else []),
                    )
                    current = requests_by_id.get(external_id)
                    if current is None or migrated.updated_at > current.updated_at:
                        requests_by_id[external_id] = migrated
                self.settings.pop("integration_requests", None)
                migrated_integration_requests = True
            self.seerr_requests = list(requests_by_id.values())
        if migrated_integration_requests:
            # Persist the converted rows once, atomically, so later starts no
            # longer depend on the legacy settings representation.
            self.save()

    def save(self) -> None:
        with self._lock:
            payload = {
                "settings": self.settings,
                "events": [asdict(e) for e in self.events[-self.MAX_EVENTS:]],
                "wanted": [asdict(w) for w in self.wanted],
                "queue": [asdict(q) for q in self.queue[-self.MAX_QUEUE:]],
                "seerr_requests": [asdict(row) for row in self.seerr_requests],
            }
            # Keep the lock through replace as well as snapshotting. Two
            # concurrent saves used to be able to write snapshots in order A,
            # B and replace in order B, A, leaving the state file older than
            # the in-memory state even though both writes were atomic.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".romarr-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=1)
                os.replace(tmp, self.path)
            except OSError as err:
                log.warning("could not write %s: %s", self.path, err)
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # -- history -----------------------------------------------------------

    def record(self, event: Event) -> Event:
        with self._lock:
            self.events.append(event)
            if len(self.events) > self.MAX_EVENTS:
                del self.events[: len(self.events) - self.MAX_EVENTS]
        self.save()
        return event

    def history(self, limit: int = 100, kind: str = "") -> list[dict]:
        with self._lock:
            items = [e for e in self.events if not kind or e.kind == kind]
            return [asdict(e) for e in reversed(items[-limit:])]

    # -- wanted ------------------------------------------------------------

    def want(self, game: str, platform: str, monitored: bool = True) -> WantedItem:
        """Add to Wanted, or return the existing entry.

        Requesting the same game twice is a retry, not a second entry.
        """
        with self._lock:
            for item in self.wanted:
                if item.game.lower() == game.lower() and item.platform == platform:
                    return item
            item = WantedItem(game=game, platform=platform, monitored=monitored)
            self.wanted.append(item)
        self.save()
        return item

    def set_monitored(self, game: str, platform: str, monitored: bool) -> bool:
        """Turn watching on or off for one Wanted entry; False if it is not there."""
        with self._lock:
            for item in self.wanted:
                if item.game.lower() == game.lower() and item.platform == platform:
                    item.monitored = bool(monitored)
                    break
            else:
                return False
        self.save()
        return True

    def fulfil(self, game: str, platform: str) -> bool:
        """Drop something from Wanted once it has actually arrived."""
        with self._lock:
            before = len(self.wanted)
            self.wanted = [
                w for w in self.wanted
                if not (w.game.lower() == game.lower() and w.platform == platform)
            ]
            changed = len(self.wanted) != before
        if changed:
            self.save()
        return changed

    def unwant(self, game: str, platform: str) -> bool:
        """Drop a request nobody wants any more.

        The same removal `fulfil` performs, deliberately kept apart from it:
        fulfil means "this arrived", and the two are not the same event to
        anybody reading History later. Without this the only way off the
        Wanted list was an import, so a misspelled request cost an indexer
        search on every missing sweep and every RSS pass, forever, for a game
        that does not exist.
        """
        return self.fulfil(game, platform)

    def missing(self) -> list[dict]:
        with self._lock:
            return [asdict(w) for w in self.wanted]

    def note_failure(self, game: str, platform: str, reason: str) -> None:
        with self._lock:
            for item in self.wanted:
                if item.game.lower() == game.lower() and item.platform == platform:
                    item.attempts += 1
                    item.last_error = reason
                    break
        self.save()

    def mark_searched(self, game: str, platform: str) -> None:
        """Stamp when an automatic search ran, whatever it found.

        Separate from note_failure on purpose: the backoff clock starts when
        a search RUNS. Stamping only failures would make an item whose search
        crashed mid-way immediately eligible again, which is a retry storm
        with extra steps.
        """
        with self._lock:
            for item in self.wanted:
                if item.game.lower() == game.lower() and item.platform == platform:
                    item.searched_at = now_iso()
                    break
        self.save()

    # -- queue (Activity) ---------------------------------------------------

    def enqueue(self, item: QueueItem) -> QueueItem:
        """Add one row to the queue and write it down."""
        with self._lock:
            self.queue.append(item)
            if len(self.queue) > self.MAX_QUEUE:
                del self.queue[: len(self.queue) - self.MAX_QUEUE]
        self.save()
        return item

    def set_queue(self, items) -> None:
        """Replace the whole queue -- what remove, retry and clear do."""
        with self._lock:
            self.queue = list(items)
        self.save()

    def queue_rows(self) -> list[dict]:
        with self._lock:
            return [asdict(q) for q in self.queue]

    # -- SeerrNG request identities --------------------------------------

    def get_seerr_request(self, external_request_id: str) -> SeerrRequest | None:
        with self._lock:
            return next(
                (row for row in self.seerr_requests
                 if row.external_request_id == external_request_id),
                None,
            )

    def list_seerr_requests(self) -> list[SeerrRequest]:
        """Snapshot the durable external requests for the integration API."""
        with self._lock:
            return list(self.seerr_requests)

    def latest_seerr_request(self) -> SeerrRequest | None:
        """Return the most recently updated integration request, if any."""
        with self._lock:
            return max(
                self.seerr_requests,
                key=lambda row: (row.updated_at, row.external_request_id),
                default=None,
            )

    def put_seerr_request(self, row: SeerrRequest) -> SeerrRequest:
        with self._lock:
            for index, current in enumerate(self.seerr_requests):
                if current.external_request_id == row.external_request_id:
                    self.seerr_requests[index] = row
                    break
            else:
                self.seerr_requests.append(row)
            if len(self.seerr_requests) > self.MAX_SEERR_REQUESTS:
                excess = len(self.seerr_requests) - self.MAX_SEERR_REQUESTS
                terminal = {"available", "failed", "cancelled"}
                retention_cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=90)
                ).isoformat(timespec="seconds")
                retained = []
                for current in self.seerr_requests:
                    if (
                        excess
                        and current.status in terminal
                        and current.updated_at < retention_cutoff
                    ):
                        excess -= 1
                        continue
                    retained.append(current)
                self.seerr_requests = retained
        self.save()
        return row

    def put_seerr_request_if_absent(
        self, row: SeerrRequest
    ) -> tuple[SeerrRequest, bool]:
        """Insert one external identity once, returning the stored row.

        The read and insert share the store lock, so simultaneous retries
        cannot replace a live row or launch a second acquisition.
        """
        with self._lock:
            current = next(
                (item for item in self.seerr_requests
                 if item.external_request_id == row.external_request_id),
                None,
            )
            if current is not None:
                return current, False
            self.seerr_requests.append(row)
            if len(self.seerr_requests) > self.MAX_SEERR_REQUESTS:
                excess = len(self.seerr_requests) - self.MAX_SEERR_REQUESTS
                terminal = {"available", "failed", "cancelled"}
                retention_cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=90)
                ).isoformat(timespec="seconds")
                retained = []
                for current in self.seerr_requests:
                    if (excess and current is not row
                            and current.status in terminal
                            and current.updated_at < retention_cutoff):
                        excess -= 1
                        continue
                    retained.append(current)
                self.seerr_requests = retained
        self.save()
        return row, True

    def update_seerr_request(self, external_request_id: str, *, status: str,
                              error: str = "",
                              only_if_not_cancelled: bool = False) -> SeerrRequest | None:
        with self._lock:
            row = next(
                (item for item in self.seerr_requests
                 if item.external_request_id == external_request_id),
                None,
            )
            if row is None:
                return None
            if only_if_not_cancelled and row.status == "cancelled":
                return row
            row.status = status
            row.error = error
            row.updated_at = now_iso()
        self.save()
        return row

    def mark_seerr_dispatching(self, external_request_id: str) -> bool:
        """Claim the handoff so cancellation cannot race the downloader add."""
        with self._lock:
            row = next(
                (item for item in self.seerr_requests
                 if item.external_request_id == external_request_id),
                None,
            )
            if row is None or row.status == "cancelled":
                return False
            row.status = "dispatching"
            row.error = ""
            row.updated_at = now_iso()
        self.save()
        return True

    def cancel_seerr_request(
        self, external_request_id: str, confirm_no_existing_download: bool = False
    ) -> str:
        """Cancel before dispatch, or require queue confirmation after recovery."""
        with self._lock:
            row = next(
                (item for item in self.seerr_requests
                 if item.external_request_id == external_request_id),
                None,
            )
            if row is None:
                return "missing"
            if row.status == "cancelled":
                return "cancelled"
            if row.status == "available":
                return "available"
            if (
                row.error.startswith("The server restarted during download handoff.")
                and not confirm_no_existing_download
            ):
                return "confirmation"
            request_queue = [
                item for item in self.queue
                if item.external_request_id == external_request_id
            ]
            if any(item.state == "imported" for item in request_queue):
                return "available"
            if row.status in ("dispatching", "downloading") or any(
                item.state in ("queued", "grabbed") for item in request_queue
            ):
                return "active"
            row.status = "cancelled"
            row.error = ""
            row.updated_at = now_iso()
        self.save()
        return "cancelled"

    def recover_seerr_dispatches(self) -> None:
        """Make interrupted work safe and retryable after a process restart."""
        changed = False
        with self._lock:
            for request in self.seerr_requests:
                if request.status == "searching":
                    # No downloader handoff was recorded. Do not silently
                    # launch another acquisition during startup; surface a
                    # retryable state to SeerrNG instead.
                    request.status = "failed"
                    request.error = (
                        "The server restarted while searching. Retry this "
                        "request to resume it."
                    )
                    request.updated_at = now_iso()
                    changed = True
                    continue
                if request.status != "dispatching":
                    continue
                rows = [
                    item for item in self.queue
                    if item.external_request_id == request.external_request_id
                ]
                latest = rows[-1] if rows else None
                if latest and latest.state == "grabbed":
                    request.status, request.error = "downloading", ""
                elif latest and latest.state == "imported":
                    request.status, request.error = "available", ""
                elif latest and latest.state in ("failed", "import-failed"):
                    request.status = "failed"
                    request.error = latest.detail or "ROMarr could not complete the request."
                else:
                    request.status = "failed"
                    request.error = (
                        "The server restarted during download handoff. Check the "
                        "download client's queue and history before retrying."
                    )
                request.updated_at = now_iso()
                changed = True
        if changed:
            self.save()

    # -- per-game shelf state ------------------------------------------------
    #
    # What Questarr tracks per game -- playing / completed / shelved, a
    # rating, a note -- and the two states it also has that ROMarr derives
    # instead of storing: "wanted" IS the wanted list, and "owned" is the
    # library. Storing either would create a second copy that drifts.

    #: The statuses a person can set. Empty string clears.
    GAME_STATUSES = ("playing", "completed", "shelved")

    @staticmethod
    def _meta_key(platform: str, game: str) -> str:
        return f"{platform}/{game.strip().lower()}"

    def set_game_meta(self, platform: str, game: str, *, status=None,
                      rating=None, notes=None) -> dict:
        """Update the fields that were sent and leave the rest alone.

        `None` means "not in this request"; empty string (or 0) means
        "clear it". A record with nothing left in it is removed entirely so
        the file does not fill with empty husks of games somebody once rated.
        """
        key = self._meta_key(platform, game)
        with self._lock:
            table = self.settings.setdefault("game_meta", {})
            row = dict(table.get(key) or {})
            if status is not None:
                status = str(status).strip().lower()
                if status and status not in self.GAME_STATUSES:
                    raise ValueError(
                        f"unknown status {status!r}; one of "
                        f"{', '.join(self.GAME_STATUSES)} or empty to clear")
                row["status"] = status
            if rating is not None:
                rating = int(rating)
                if not 0 <= rating <= 10:
                    raise ValueError("rating is 0-10, where 0 clears it")
                row["rating"] = rating
            if notes is not None:
                row["notes"] = str(notes)
            fields = {k: v for k, v in row.items()
                      if k in ("status", "rating", "notes")
                      and v not in ("", 0, None)}
            if fields:
                row = {**fields, "game": game, "platform": platform}
                table[key] = row
            else:
                # Nothing left worth keeping: remove the record entirely so
                # the file does not fill with empty husks of games somebody
                # once rated.
                row = {}
                table.pop(key, None)
        self.save()
        return dict(row)

    def game_meta(self, platform: str, game: str) -> dict:
        with self._lock:
            return dict((self.settings.get("game_meta") or {})
                        .get(self._meta_key(platform, game)) or {})

    def all_game_meta(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in (self.settings.get("game_meta") or {}).values()]

    # -- settings ----------------------------------------------------------

    # -- collections (download clients, indexers) --------------------------

    def _collection(self, key: str) -> list[dict]:
        return self.settings.setdefault(key, [])

    def list_items(self, key: str) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._collection(key)]

    def get_item(self, key: str, item_id: str) -> dict | None:
        with self._lock:
            for item in self._collection(key):
                if str(item.get("id")) == str(item_id):
                    return dict(item)
        return None

    def put_item(self, key: str, item: dict) -> dict:
        """Add or replace one entry, returning it with its id."""
        import uuid
        with self._lock:
            items = self._collection(key)
            if item.get("id"):
                for i, existing in enumerate(items):
                    if str(existing.get("id")) == str(item["id"]):
                        items[i] = item
                        break
                else:
                    items.append(item)
            else:
                item["id"] = uuid.uuid4().hex[:12]
                items.append(item)
            out = dict(item)
        self.save()
        return out

    def delete_item(self, key: str, item_id: str) -> bool:
        with self._lock:
            items = self._collection(key)
            before = len(items)
            self.settings[key] = [i for i in items if str(i.get("id")) != str(item_id)]
            changed = len(self.settings[key]) != before
        if changed:
            self.save()
        return changed

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply a partial settings update.

        Unknown keys are dropped rather than stored: a typo in a PUT should not
        silently become permanent state that nothing ever reads.
        """
        with self._lock:
            for key, value in patch.items():
                if key in DEFAULT_SETTINGS and key != "_organizer_journal_key":
                    self.settings[key] = value
            out = dict(self.settings)
        self.save()
        return out


def to_jsonable(value: Any) -> Any:
    """dataclasses -> dicts, for the API layer."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value
