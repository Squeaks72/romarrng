# Extras: DLC, updates, manuals and the other game folders

RomM looks for special sub-folders inside a multi-file game and tags what it finds:
`dlc`, `update`, `manual`, `patch`, `hack`, `mod`, `demo`, `translation`, `prototype`
([RomM's folder structure](https://docs.romm.app/4.8.1/Getting-Started/Folder-Structure/#folder-organization)).
ROMarr can find content for those folders and put it there, from the game page, the way it already does
for soundtracks.

Open a game that is in your RomM library. Below the Soundtrack card there is a card each for **DLC**,
**Updates** and **Manuals**, and one **More extras** card with a picker for the rest (patches, hacks,
mods, demos, translations, prototypes). Every card shows how many files RomM holds in that folder and how
many ROMarr added, and offers:

* **Search torrents**: an indexer search (the Prowlarr ROMarr already uses) with terms you can edit. The
  default is the game's name plus the kind ("Chrono Trigger DLC"). **Grab** sends the torrent to
  qBittorrent in the `romarr-extras` category and ROMarr watches it. When it finishes, the files that fit the
  folder are uploaded to RomM; the torrent itself is never touched and keeps seeding. Results are
  unscored: check the title and size, because ROMarr cannot tell a DLC pack from a whole-game release.
* **Search the Internet Archive** (manuals): items that look like the game's manual, then the PDFs and
  text files inside the one you pick.
* **Add from a link**: paste the direct link to a file. Public sites only (see Safety).
* **Upload a file**: pick a file in your browser; it is streamed to ROMarr and on to RomM.
* **Undo**: removes exactly the files ROMarr added to that folder.
* Links to search by hand (Internet Archive, Google, and for manuals Replacement Docs and Vimm's Manual
  Museum). Those sites are only linked, never scraped.

Files go in **through RomM's own chunked-upload API** with the folder as the target
(`POST /api/roms/upload/start` with `rom_id` and `folder`, then the chunks, then `complete`). RomM creates
the folder, registers the file, and for a lone ROM file first moves the ROM into a folder of its own.
ROMarr never writes to the ROM tree. The library login needs `roms.write`; removing a DLC/update/other file
also needs RomM's permission to delete ROM files (removing a manual only needs `roms.write`).

## What goes in which folder

| Folder | Takes |
|---|---|
| `manual` | `.pdf`, `.md`, `.txt` only (what RomM's manual tab shows). From a torrent, text files are only taken when there is no PDF; PDFs inside a zip in the torrent are taken. |
| `dlc`, `update`, `patch`, `hack`, `mod`, `demo`, `translation`, `prototype` | Any file, including archives (`.7z`, `.zip`, `.rar`) as they are. |

Never taken, from any source: Windows programs and scripts (`.exe .msi .bat .cmd .com .scr .lnk .vbs .vbe
.jse .ps1 .reg .dll`), release leftovers (`.nfo .sfv .md5 .sha1 .sha256 .url .torrent .par2 ...`), hidden
files, and `Thumbs.db`-style clutter. A file whose name RomM already holds in that folder is skipped, never
replaced. A torrent holding more than 200 files is not filed automatically (it is almost certainly the wrong
release); the watch says so.

RomM's own scraped manual (from ScreenScraper and similar) is a different thing from the `manual/` folder.
The card says when RomM already has one; adding a manual here puts a file in the game folder next to the ROM,
which is what handhelds and frontends that read the folder use.

## Safety rules

* **Never overwrites.** A file already in that folder under that name is skipped.
* **Undo only removes what ROMarr added**, by the file id RomM gave back, per game and per kind. Files you
  added yourself are never touched, and a file RomM no longer has counts as already gone.
* **A pasted link is fetched carefully.** Only `http`/`https`; every address the host resolves to must be a
  public one (loopback, private ranges, link-local and the cloud metadata address are refused); redirects are
  followed by hand, at most five, and each hop is checked again; a web page (HTML) is refused; the file is
  capped at 8 GB; a partial file is deleted. This guards against a link used to reach services on your own
  network. It cannot stop a hostile DNS server that answers differently the second time; the route is behind
  the same login as the rest of ROMarr.
* **Uploads from the browser** are checked against the folder's file types before any bytes are read, capped at
  8 GB and written to disk a megabyte at a time.
* **A ROM whose name would change** when RomM moves it into a folder (its name ends in a dotted number, like
  `Game v1.2`) is left alone, because that would break name-based save matching.
* **Polite to the sources:** one request per second per host, with a User-Agent that says ROMarr is asking.
* **No credentials in output.** Errors from RomM have the token scrubbed.

## HTTP API

All routes use the normal ROMarr authentication. `id` is the RomM game id, `kind` is one of the folder names
above.

| Route | |
|---|---|
| `GET /api/v1/extras/game?id=&kind=` | Files RomM holds for that kind, how many ROMarr added, last job, torrent watch, hand-search links |
| `GET /api/v1/extras/torrents?id=&kind=&q=` | Indexer search; results are unscored |
| `POST /api/v1/extras/torrents/grab` `{id, kind, release}` | Send the pick to qBittorrent and watch it |
| `POST /api/v1/extras/torrents/cancel` `{id, kind}` | Stop watching (the torrent stays in the client) |
| `GET /api/v1/extras/archive/search?id=&kind=manual&q=` | Internet Archive items that look like the manual |
| `GET /api/v1/extras/archive/files?id=&kind=&item=` | The PDF/text files of one item |
| `POST /api/v1/extras/archive/add` `{id, kind, item, name}` | Fetch that file and upload it |
| `POST /api/v1/extras/link` `{id, kind, url}` | Fetch a public link and upload the file |
| `POST /api/v1/extras/upload?id=&kind=&name=` | The file as the raw request body |
| `POST /api/v1/extras/undo` `{id, kind}` | Remove what ROMarr added to that folder |
| `GET /api/v1/extras/jobs` | Recent jobs with step and progress |

One job per game and kind runs at a time; a second request answers `409`. Data lives in
`romarr-extras.db` beside the ROMarr data file (tables `added` and `watch`).

## Setup notes

* The torrent import reads the finished download from the path qBittorrent reports, mapped through ROMarr's
  remote path mappings. In the usual layout `/data/torrents` is mounted in both containers and nothing needs
  setting up.
* The extras torrent category is `romarr-extras`. Do not point Sonarr/Radarr or ROMarr's own import at it.
* Uploads pass through RomM chunk by chunk (16 MiB), so a multi-gigabyte DLC works but takes as long as RomM
  needs to write it. The card shows progress.

## Not built

Walkthroughs and cheats have their own RomM endpoints and are not part of this. There is no automatic
"find everything for the whole library" run; each game is looked at by hand, because a wrong torrent for a
DLC is worse than a missing one. The Switch Updates & DLC report is separate and still works the way it did.
