# Soundtracks

ROMarr can find a game's soundtrack and put it into RomM's **Jukebox**, from the game page. This
is a port of the standalone `romm-soundtracks` tool, built into ROMarr so there is one app and no
second process to run. It is being ported in phases; this page describes phase 1.

## What phase 1 does

Open a game that is in your RomM library. The **Soundtrack** card shows:

* how many soundtrack files RomM holds for the game, and how many of those ROMarr added;
* **Search for a soundtrack**: ranked candidates from Zophar's Domain and the Internet Archive
  (same platform first, then title similarity), each with an **Open** link and a download button
  per format offered, plus a row of manual-search links (KHInsider, VGMRips, Zophar, Internet
  Archive, MusicBrainz, Bandcamp, YouTube);
* progress while a download runs (it continues if you leave the page);
* **Undo**, which removes the files ROMarr added and nothing else.

Files go in **through RomM's own API** (`POST /api/roms/{id}/soundtracks`). RomM creates the
`soundtrack/` folder, registers the tracks and, for a lone ROM file, first moves the ROM into a
folder of its own. ROMarr never writes to the ROM tree.

RomM only accepts MP3, OGG, OPUS, M4A, AAC, WAV, FLAC, SPC, VGM, VGZ and GYM. Other chiptune
formats (NSF, GBS, ...) are read out of archives but skipped, because RomM would refuse them.
MP3 is the safe choice; "original rips" are only useful on consoles whose native format is SPC,
VGM or GYM.

### Sign-in

ROMarr uses the login already saved on the RomM entry on the **Libraries** page. There is no
soundtrack token to configure. For uploads and undo it asks RomM for a token that also carries
`roms.write` (the token ROMarr uses all day stays read-only). If the library entry uses a fixed API
token instead of a username and password, that token must itself be allowed to edit ROMs. The URL
used is the library entry's URL.

### Settings

`soundtrack_sources` (comma separated, default `zophar,archive`) picks which sources the Search
button queries. It can be edited through the settings API; there is no page for it yet.

## HTTP API

All routes use the normal ROMarr authentication. `id` is the RomM game id, as on the game page.

| Route | |
|---|---|
| `GET /api/v1/soundtracks/game?id=` | Status: tracks RomM holds, how many ROMarr added, last job |
| `GET /api/v1/soundtracks/search?id=` | Ranked candidates, any source errors, manual links |
| `POST /api/v1/soundtracks/download` `{id, candidate:{provider,id}, format}` | Starts a background job, returns it |
| `GET /api/v1/soundtracks/jobs` | Recent jobs with step, progress and counts |
| `POST /api/v1/soundtracks/undo` `{id}` | Removes what ROMarr added to that game |

`format` is `mp3`, `original`, `both`, `flac` or `files` (Internet Archive items). Only one job
runs per game: a second download or an undo while one is running answers 409. Search runs on the
request (a few seconds, bounded by the one-request-per-second rule); downloading and uploading
never do.

Data lives in `romarr-soundtracks.db` beside the ROMarr data file (`ROMARR_DATA`), in tables
`sound` and `journal` keyed by RomM game id, the same names the standalone tool used.

## Safety rules

* **Never overwrites.** A track RomM already has under that name is skipped.
* **Undo only removes what ROMarr added.** Each upload is journaled with the file id RomM gave it,
  and undo deletes exactly those ids through RomM. Files you added yourself are never touched, and
  a journal entry for a different game is ignored. A file RomM no longer has counts as already gone.
  If a delete fails part-way, the rest stay journaled so Undo can be retried.
* **No empty `soundtrack/` folders.** ROMarr creates no folders; RomM does, and only when a real
  file is being sent. Nothing is sent unless it is an accepted audio file.
* **Archives are streamed, not extracted.** Only audio extensions are read out of a zip, names are
  flattened (`../../x.mp3` becomes `x.mp3`, nothing is written to a path from the archive), and an
  archive over 6 GB is refused before anything is read.
* **Polite to the sources.** At most one request per second per host, with a User-Agent that says
  ROMarr is asking. Download links must point at zophar.net or archive.org. Sites behind a bot
  challenge (KHInsider) are never scraped, only linked.
* **A ROM whose name would change** when RomM moves it into a folder (its name ends in a dotted
  number, like `Game v1.2`) is left alone, because that would break name-based save matching.
* **No credentials in output.** Nothing logs or returns the library password or a token; errors
  from RomM have the token scrubbed.

## Not ported yet

* **Phase 2:** duplicate soundtrack merge (several games sharing one stored soundtrack).
* **Phase 3:** music-library albums (use an album from a regular music library as a game's
  soundtrack).
* **Phase 4:** 3DS encryption status and the decrypt tool, and held originals (the safety copy kept
  before any ROM is replaced).
* Direct delivery (writing files into the game folder instead of uploading through RomM) is not
  planned for phase 1 or 2; it was the standalone tool's fallback.
* "Download confident matches" for a whole selection, and a soundtrack column or filter on the
  library page, come with the later phases.

## Assumptions about RomM's API

The calls are the ones the standalone tool made against a live RomM: `GET /api/roms/{id}`
(`fs_name`, `has_multiple_files`), `GET /api/roms/{id}/soundtracks/metadata` (list of
`file_name`/`file_id`), `POST /api/roms/{id}/soundtracks` (multipart, one part named after the file,
`x-upload-filename` header, `201` on success; `400`/`409` mean that file is refused),
`DELETE /api/roms/{id}/soundtracks/{file_id}` (`404` = already gone). The standalone tool
authenticated these with a client token; ROMarr authenticates with the password-grant bearer token
it already uses elsewhere, with the `roms.write` scope added. That the same grant is accepted for
the upload endpoints has not been tried against a live RomM.
