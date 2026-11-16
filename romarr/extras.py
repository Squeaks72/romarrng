"""Game extras: DLC, updates, manuals and the other folders RomM understands inside a game's folder.

RomM looks for special sub-folders in a multi-file game (`dlc`, `update`, `manual`, `patch`, `hack`,
`mod`, `demo`, `translation`, `prototype`) and shows what it finds as tagged files on the game page.
This module finds that content, puts it there and takes it back, the same way `soundtracks.py` does
for the `soundtrack/` folder:

  * every file goes in **through RomM's own chunked-upload API** with the sub-folder as the target, so
    RomM creates the folder, registers the file and, for a lone ROM, first moves the ROM into a folder
    of its own. ROMarr never writes to the ROM tree;
  * sources are the indexers ROMarr already searches (the pick goes to qBittorrent and is watched until
    it finishes), the Internet Archive (manuals), a link someone pastes, and a file someone uploads;
  * everything added is journaled with RomM's file id, so Undo removes that and nothing else;
  * never overwrites: a file RomM already holds under that name is skipped.

Safety rules specific to this module:

  * a pasted link is fetched only after every address it resolves to is a public one, redirects are
    followed by hand and checked at every hop, and the size is capped;
  * Windows executables and scripts are never taken from a download, and neither are the .nfo/.sfv
    style leftovers;
  * a manual folder only takes what RomM's manual tab can show (PDF, Markdown, text).

The login is the RomM library entry's own (see `Romm.write_token`); nothing here stores or prints a
credential. See docs/EXTRAS.md.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import math
import os
import re
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote, quote_plus, unquote, urlencode, urljoin, urlparse

import requests

from .soundtracks import (JobBusy, RommApi, RommError, UA, _wait_turn, check_zip, header_safe, norm,
                          polite_get, safe_name, similarity, stem_stable)

log = logging.getLogger(__name__)

#: How a game's extras are filed. `term` is what the indexer search adds to the game's name.
KINDS: dict[str, dict] = {
    "dlc": {"label": "DLC", "plural": "DLC", "term": "DLC", "docs": False,
            "help": "Downloadable content packs for this game."},
    "update": {"label": "Update", "plural": "Updates", "term": "update", "docs": False,
               "help": "Title updates and patches released by the publisher, such as a later version of the game."},
    "manual": {"label": "Manual", "plural": "Manuals", "term": "manual", "docs": True,
               "help": "The instruction booklet, as a PDF (or a text/Markdown file)."},
    "patch": {"label": "Patch", "plural": "Patches", "term": "patch", "docs": False,
              "help": "Fan or unofficial patches (bug fixes, widescreen)."},
    "hack": {"label": "Hack", "plural": "Hacks", "term": "rom hack", "docs": False,
             "help": "Modified versions of the game."},
    "mod": {"label": "Mod", "plural": "Mods", "term": "mod", "docs": False,
            "help": "Mods for the game."},
    "demo": {"label": "Demo", "plural": "Demos", "term": "demo", "docs": False,
             "help": "Demo and trial versions."},
    "translation": {"label": "Translation", "plural": "Translations", "term": "translation", "docs": False,
                    "help": "Fan translations."},
    "prototype": {"label": "Prototype", "plural": "Prototypes", "term": "prototype", "docs": False,
                  "help": "Prototype and beta builds."},
}
#: The folders the game page offers first; the rest share one card.
MAIN_KINDS = ("dlc", "update", "manual")

#: What RomM's manual tab can show (its own ALLOWED_MANUAL_EXTENSIONS).
DOC_EXT = frozenset({".pdf", ".md", ".txt"})
#: Never taken from a download: Windows programs and scripts. A game's DLC or update is data, and
#: an executable arriving with it is a reason to look at the release again, not to file it.
BLOCKED_EXT = frozenset({".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".lnk", ".vbs", ".vbe",
                         ".jse", ".ps1", ".reg", ".dll"})
#: Release leftovers that are not part of the content.
JUNK_EXT = frozenset({".nfo", ".sfv", ".md5", ".sha1", ".sha256", ".url", ".torrent", ".part", ".parts",
                      ".tmp", ".!qb", ".db", ".ini", ".diz", ".srr", ".srs", ".par2"})
JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})

#: Bytes per chunk sent to RomM (its hard cap is 64 MiB).
CHUNK = 16 << 20
#: A pasted link or an uploaded file larger than this is refused.
MAX_FILE_BYTES = 8 << 30
#: A torrent that holds more files than this is not filed automatically; the pick was probably wrong.
MAX_TORRENT_FILES = 200
WATCH_LOST_AFTER = 600
WATCH_DONE = ("added", "failed", "lost", "cancelled")

#: Set by tests only: lets the link fetcher talk to a loopback server.
ALLOW_PRIVATE_HOSTS = False


# ------------------------------------------------------------------- files --

def word(kind: str) -> str:
    """The kind as it reads in a sentence: "DLC", "update", "manual"."""
    return "DLC" if kind == "dlc" else KINDS[kind]["label"].lower()


def clean_name(name: str) -> str:
    """A plain, header-safe file name that is never a path."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    return header_safe(safe_name(base))


def allowed_file(kind: str, name: str) -> bool:
    """Is this file something to put in this kind's folder?"""
    base = os.path.basename(name).lower()
    ext = os.path.splitext(base)[1]
    if not base or base.startswith(".") or base in JUNK_NAMES or ext in BLOCKED_EXT or ext in JUNK_EXT:
        return False
    if KINDS[kind]["docs"]:
        return ext in DOC_EXT
    return True


def pick_files(kind: str, names: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    """From (store name, path, size) keep what belongs in the folder.

    A manual download often carries a readme beside the PDF, so text files are only taken when there is
    no PDF at all.
    """
    keep = [f for f in names if allowed_file(kind, f[0])]
    if KINDS[kind]["docs"] and any(f[0].lower().endswith(".pdf") for f in keep):
        keep = [f for f in keep if f[0].lower().endswith(".pdf")]
    return keep


def torrent_files(path: str, kind: str) -> tuple[list[tuple[str, str, int]], list[str]]:
    """(files worth storing, zips inside the torrent) for a finished torrent's content path.

    Names are the base names; two files that would collide keep their folder in the name
    ("Disc 2 - patch.bin"). Symlinks that lead out of the torrent are ignored.
    """
    if not path or not os.path.exists(path):
        return [], []
    real = os.path.realpath(path)
    found: list[tuple[str, str, int]] = []
    zips: list[str] = []
    if os.path.isfile(real):
        walk = [(os.path.dirname(real), [], [os.path.basename(real)])]
        top = os.path.dirname(real)
    else:
        walk = list(os.walk(real))
        top = real
    for dp, _dns, fns in walk:
        for fn in sorted(fns):
            full = os.path.realpath(os.path.join(dp, fn))
            if not full.startswith(top + os.sep) and full != real:
                continue
            if not os.path.isfile(full):
                continue
            if KINDS[kind]["docs"] and fn.lower().endswith(".zip"):
                zips.append(full)
            found.append((clean_name(os.path.relpath(full, top).replace(os.sep, " - ")), full, os.path.getsize(full)))
    # Prefer the short base name; fall back to the path-in-name only for a collision.
    counts: dict[str, int] = {}
    for _n, full, _s in found:
        counts[os.path.basename(full)] = counts.get(os.path.basename(full), 0) + 1
    out = [((clean_name(os.path.basename(full)) if counts[os.path.basename(full)] == 1 else n), full, size)
           for n, full, size in found]
    return pick_files(kind, out), zips


def zip_docs(zips: list[str]) -> list[tuple[str, str, str]]:
    """[(name to store, zip path, member)] for the manuals inside each zip; unreadable zips are skipped."""
    out = []
    for zp in zips:
        try:
            check_zip(zp)
            with zipfile.ZipFile(zp) as z:
                for i in z.infolist():
                    if i.is_dir() or not allowed_file("manual", i.filename):
                        continue
                    parts = [p for p in i.filename.replace("\\", "/").split("/") if p and p != ".."]
                    out.append((clean_name(" - ".join(parts)), zp, i.filename))
        except (zipfile.BadZipFile, ValueError, OSError):
            continue
    return out


# -------------------------------------------------------------- fetch a link --

def _check_host(host: str) -> None:
    """Refuse a host any of whose addresses is private, loopback, link-local or otherwise not public."""
    if ALLOW_PRIVATE_HOSTS:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as ex:
        raise ValueError(f"could not look up {host}") from ex
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError("that link points at a private network address; only public sites can be fetched")


def _link_name(url: str, headers) -> str:
    cd = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*\s*=\s*[\w-]+''([^;]+)", cd, re.I) or re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    name = unquote(m.group(1)) if m else unquote(os.path.basename(urlparse(url).path))
    name = clean_name(name)
    if not os.path.splitext(name)[1] and "pdf" in headers.get("Content-Type", "").lower():
        name += ".pdf"
    return name


def fetch_link(url: str, tmp_dir: str, kind: str, progress: Callable[..., None] | None = None,
               limit: int = MAX_FILE_BYTES) -> tuple[str, str, int]:
    """Download one file from a public http(s) link into `tmp_dir`. Returns (store name, temp path, size).

    Redirects are followed by hand (at most five) and every hop is checked, so a public page cannot
    bounce the request onto the local network. A web page (HTML) is refused: the link has to be the file.
    """
    for _hop in range(6):
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("the link must start with http:// or https://")
        _check_host(u.hostname)
        _wait_turn(u.netloc)
        r = requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=60, allow_redirects=False)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", ""))
            r.close()
            continue
        break
    else:
        raise ValueError("too many redirects")
    try:
        if not r.ok:
            raise ValueError(f"the site answered {r.status_code}")
        if "text/html" in r.headers.get("Content-Type", "").lower():
            raise ValueError("that link is a web page, not a file; open it and copy the file's own download link")
        name = _link_name(url, r.headers)
        if not allowed_file(kind, name):
            raise ValueError(f"{name or 'that file'} is not a type that goes in the {word(kind)} folder"
                             + (" (PDF, Markdown or text only)" if KINDS[kind]["docs"] else ""))
        total = int(r.headers["Content-Length"]) if r.headers.get("Content-Length", "").isdigit() else 0
        if total > limit:
            raise ValueError("that file is larger than ROMarr will fetch")
        os.makedirs(tmp_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="dl-", dir=tmp_dir)
        done = 0
        try:
            with os.fdopen(fd, "wb") as f:
                for b in r.iter_content(1 << 20):
                    f.write(b)
                    done += len(b)
                    if done > limit:
                        raise ValueError("that file is larger than ROMarr will fetch")
                    if progress:
                        progress("Downloading " + name, (done / total) if total else None)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return name, tmp, done
    finally:
        r.close()


# ----------------------------------------------------------- Internet Archive --

def archive_manual_search(title: str, platform: str = "") -> list[dict]:
    """Internet Archive text items that look like this game's manual, best match first."""
    words = " ".join(norm(title).split())
    if not words:
        return []
    q = f"title:({words}) AND mediatype:texts AND (manual OR booklet OR instruction OR instructions)"
    url = "https://archive.org/advancedsearch.php?" + urlencode(
        {"q": q, "fl[]": ["identifier", "title", "item_size"], "rows": 12, "output": "json"}, doseq=True)
    docs = json.loads(polite_get(url))["response"]["docs"]
    out = []
    for d in docs:
        t = str(d.get("title") or d["identifier"])
        bare = re.sub(r"\b(game )?(manual|booklet|instructions?|instruction booklet|owner'?s)\b", " ", t, flags=re.I)
        out.append({"id": d["identifier"], "title": t, "url": "https://archive.org/details/" + d["identifier"],
                    "score": similarity(title, bare), "size": d.get("item_size")})
    return sorted((x for x in out if x["score"] >= 0.45), key=lambda x: -x["score"])[:8]


def archive_item_files(ident: str, kind: str = "manual") -> list[dict]:
    """The files in an Internet Archive item that fit a folder: [{name, size, url}], originals first."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]*", ident):
        raise ValueError("not an Internet Archive identifier")
    meta = json.loads(polite_get("https://archive.org/metadata/" + quote(ident)))
    base = "https://archive.org/download/" + quote(ident) + "/"
    rows = [f for f in meta.get("files", []) if allowed_file(kind, f.get("name", ""))]
    rows.sort(key=lambda f: (f.get("source") != "original", f.get("name", "")))
    return [{"name": f["name"], "size": int(f.get("size") or 0), "url": base + quote(f["name"])} for f in rows][:40]


def kind_links(kind: str, title: str, platform_name: str) -> list[dict]:
    """Search pages worth opening by hand (links only, never scraped)."""
    word = KINDS[kind]["term"]
    q = quote_plus
    links = [{"name": "Internet Archive", "url": "https://archive.org/search?query=" + q(f"{title} {word}")},
             {"name": "Google", "url": "https://www.google.com/search?q=" + q(f"{title} {platform_name} {word}")}]
    if kind == "manual":
        links.insert(1, {"name": "Replacement Docs",
                         "url": "https://www.google.com/search?q=" + q(f"site:replacementdocs.com {title} {platform_name}")})
        links.insert(2, {"name": "Vimm's Manual Museum",
                         "url": "https://www.google.com/search?q=" + q(f"site:vimm.net manual {title}")})
    return links


# ------------------------------------------------------------------- RomM --

class ExtrasApi(RommApi):
    """RomM calls for extras: list a game's files, upload into a sub-folder, delete one file."""

    def files_of(self, rom: dict, kind: str) -> list[dict]:
        """RomM's records for the files of this kind: [{id, name, size}]."""
        return [{"id": f.get("id"), "name": f.get("file_name", ""), "size": int(f.get("file_size_bytes") or 0)}
                for f in rom.get("files") or [] if str(f.get("category") or "") == kind]

    def _json_request(self, method: str, path: str, body: dict | None, headers: dict) -> requests.Response:
        raw = json.dumps(body).encode() if body is not None else None
        return self._request(method, path, make_body=(lambda: raw) if raw is not None else None,
                             headers={"Content-Type": "application/json", **headers})

    def upload_file(self, rom: dict, folder: str, name: str, path: str, size: int,
                    progress: Callable[[int], None] | None = None) -> None:
        """Send one local file into `folder` of the ROM's own folder, in chunks, never replacing a file."""
        rom_id, platform_id = int(rom["id"]), int(rom["platform_id"])
        chunks = 0 if size == 0 else math.ceil(size / CHUNK)
        r = self._json_request(
            "POST", "/api/roms/upload/start",
            {"rom_id": rom_id, "folder": folder, "filename": name, "overwrite": False},
            {"x-upload-platform": str(platform_id), "x-upload-filename": header_safe(name),
             "x-upload-total-size": str(size), "x-upload-total-chunks": str(chunks)})
        if r.status_code not in (200, 201):
            raise RommError(r.status_code, self._redact(r.text[:300]))
        upload_id = str((r.json() or {}).get("upload_id") or "")
        if not upload_id:
            raise RommError(502, "RomM did not return an upload id")
        try:
            # RomM expects fixed-size chunks with a shorter last one, sized from the total and the count.
            step = math.ceil(size / chunks) if chunks else 0
            sent = 0
            with open(path, "rb") as fh:
                for i in range(chunks):
                    data = fh.read(step)
                    for attempt in (0, 1):
                        rr = self._request("PUT", f"/api/roms/upload/{upload_id}", make_body=lambda d=data: d,
                                           headers={"x-chunk-index": str(i), "Content-Type": "application/octet-stream"},
                                           timeout=600)
                        if rr.ok or attempt or rr.status_code < 500:
                            break
                    if not rr.ok:
                        raise RommError(rr.status_code, self._redact(rr.text[:300]))
                    sent += len(data)
                    if progress:
                        progress(sent)
            done = self._request("POST", f"/api/roms/upload/{upload_id}/complete", timeout=3600)
            if done.status_code not in (200, 201):
                raise RommError(done.status_code, self._redact(done.text[:300]))
        except BaseException:
            try:
                self._request("POST", f"/api/roms/upload/{upload_id}/cancel", timeout=30)
            except Exception:  # noqa: BLE001 - best effort; RomM expires the session by itself
                pass
            raise

    def delete_file(self, rom_id: str, file_id: str, kind: str) -> bool:
        """Remove one registered file. False when RomM no longer has it."""
        path = (f"/api/roms/{int(rom_id)}/manuals/files/{int(file_id)}" if kind == "manual"
                else f"/api/roms/{int(rom_id)}/files/{int(file_id)}")
        r = self._request("DELETE", path)
        if r.status_code == 404:
            return False
        if not r.ok:
            raise RommError(r.status_code, self._redact(r.text[:300]))
        return True


# ----------------------------------------------------------------- the store --

DDL = """
CREATE TABLE IF NOT EXISTS added(id INTEGER PRIMARY KEY, key TEXT NOT NULL, kind TEXT NOT NULL, file_id INTEGER,
    name TEXT, size INTEGER, source TEXT, ts REAL, undone INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS added_key ON added(key, kind);
CREATE TABLE IF NOT EXISTS watch(id INTEGER PRIMARY KEY, key TEXT NOT NULL, kind TEXT NOT NULL, tag TEXT, release TEXT,
    state TEXT, message TEXT, pct REAL, added REAL, updated REAL, seen REAL);
"""


def db_path_for(data_file: str) -> Path:
    return Path(data_file).parent / "romarr-extras.db"


def _reason(ex: Exception, api: RommApi | None = None) -> str:
    """A message safe to show: RomM errors are scrubbed, ValueErrors are ours, anything else is a class name."""
    if isinstance(ex, RommError):
        if ex.status in (401, 403):
            return "RomM refused it: the library login needs permission to edit ROMs (roms.write)"
        return api._redact(str(ex)) if api else str(ex)
    return str(ex) if isinstance(ex, ValueError) else ex.__class__.__name__


class Extras:
    """Find, add and undo the files in a game's `dlc`/`update`/`manual`/... folders for one install."""

    MAX_JOBS = 50

    def __init__(self, db_path: str | os.PathLike):
        self.db_path = Path(db_path)
        self.tmp_dir = str(self.db_path.parent / "extras-tmp")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._init_db()

    # -- db --
    def _db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        c = self._db()
        try:
            c.executescript(DDL)
            c.commit()
        finally:
            c.close()

    @staticmethod
    def _check_kind(kind: str) -> str:
        if kind not in KINDS:
            raise ValueError("unknown kind of extra")
        return kind

    def journal_count(self, key: str, kind: str) -> int:
        c = self._db()
        try:
            return c.execute("SELECT COUNT(*) FROM added WHERE key=? AND kind=? AND undone=0", (key, kind)).fetchone()[0]
        finally:
            c.close()

    # -- status --
    def status(self, game: dict, kind: str, api: RommApi | None) -> dict:
        self._check_kind(kind)
        key = str(game["id"])
        files, error, scraped = None, "", False
        if api is not None:
            try:
                rom = api.rom(key)
                files = api.files_of(rom, kind)
                scraped = kind == "manual" and bool(rom.get("has_manual") or rom.get("path_manual"))
            except (RommError, requests.RequestException, ValueError) as ex:
                error = f"Could not ask RomM what it holds: {ex.__class__.__name__}"
        else:
            error = "No RomM library is configured"
        return {"id": key, "kind": kind, "label": KINDS[kind]["label"], "plural": KINDS[kind]["plural"],
                "help": KINDS[kind]["help"], "title": game.get("name", ""), "files": files,
                "count": len(files) if files is not None else None, "undoable": self.journal_count(key, kind),
                "scraped_manual": scraped, "job": self.job_for(key, kind), "watch": self.watch_for(key, kind),
                "term": KINDS[kind]["term"], "docs": KINDS[kind]["docs"],
                "links": kind_links(kind, game.get("name", ""), game.get("platform_name", "")), "error": error}

    # -- jobs --
    def job_for(self, key: str, kind: str) -> dict | None:
        with self._lock:
            mine = [j for j in self._jobs.values() if j["game_id"] == key and j["extra"] == kind]
        mine.sort(key=lambda j: j["started"])
        running = [j for j in mine if j["state"] == "running"]
        return dict(running[-1] if running else mine[-1]) if mine else None

    def jobs(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["started"], reverse=True)

    def _begin_job(self, key: str, kind: str, title: str, source: str) -> dict:
        with self._lock:
            if any(j["state"] == "running" and j["game_id"] == key and j["extra"] == kind for j in self._jobs.values()):
                raise JobBusy(f"a {word(kind)} job is already running for this game")
            job = {"id": uuid.uuid4().hex[:12], "game_id": key, "extra": kind, "kind": "extra", "source": source,
                   "title": title, "state": "running", "step": "Starting", "pct": None, "made": 0, "skipped": 0,
                   "message": "", "started": time.time(), "finished": None}
            self._jobs[job["id"]] = job
            for old in sorted(self._jobs.values(), key=lambda j: j["started"])[:-self.MAX_JOBS]:
                if old["state"] != "running":
                    del self._jobs[old["id"]]
        return job

    def _ensure_idle(self, key: str, kind: str) -> None:
        with self._lock:
            if any(j["state"] == "running" and j["game_id"] == key and j["extra"] == kind for j in self._jobs.values()):
                raise JobBusy(f"a {word(kind)} job is running for this game")

    def _spawn(self, fn: Callable[..., None], job: dict, *args, run_async: bool = True) -> None:
        if run_async:
            threading.Thread(target=fn, args=(job, *args), daemon=True, name=f"extras-{job['id']}").start()
        else:
            fn(job, *args)

    @staticmethod
    def _progress(job: dict) -> Callable[..., None]:
        def progress(step: str, pct: float | None = None) -> None:
            job["step"], job["pct"] = step, (round(pct, 3) if pct is not None else None)
        return progress

    # -- the one upload path --
    @staticmethod
    def _guard_rom(rom: dict) -> None:
        """Putting a file in a folder moves a lone ROM into a folder of its own. If that would change the
        name RomM stores for it, anything matching device saves by name would stop finding them."""
        if not (rom.get("has_multiple_files") or rom.get("has_nested_single_file")) and not stem_stable(str(rom.get("fs_name") or "")):
            raise ValueError("moving this ROM into a folder would change the name RomM stores for it (its name ends in a "
                             "dotted number), which breaks name-based save matching; nothing was added")

    def _upload_files(self, job: dict, game: dict, kind: str, api: ExtrasApi,
                      files: list[tuple[str, str, int]], source: str) -> tuple[int, int]:
        """Upload (name, path, size) files into the kind's folder. Returns (made, skipped); journals what went in."""
        key = str(game["id"])
        progress = self._progress(job)
        rom = api.rom(key)
        self._guard_rom(rom)
        existing = {f["name"] for f in api.files_of(rom, kind)}
        total = sum(s for _n, _p, s in files) or 1
        base = 0
        sent: list[str] = []
        made = skipped = 0
        try:
            for i, (name, path, size) in enumerate(files):
                if name in existing:
                    skipped += 1
                    base += size
                    continue
                progress(f"Adding {name} ({i + 1} of {len(files)})", base / total)
                try:
                    api.upload_file(rom, kind, name, path, size,
                                    lambda n, b=base: progress(f"Adding {name} ({i + 1} of {len(files)})", (b + n) / total))
                except RommError as ex:
                    if ex.status in (401, 403):
                        raise ValueError(_reason(ex)) from ex
                    if ex.status in (400, 409, 413):
                        log.info("RomM refused %s: %s", name, ex)
                        skipped += 1
                        base += size
                        continue
                    raise
                base += size
                sent.append(name)
                existing.add(name)
                made += 1
                job["made"], job["skipped"] = made, skipped
        finally:
            try:
                self._journal(key, kind, sent, api, source)
            except Exception:  # noqa: BLE001
                log.warning("could not journal the %s upload for %s", kind, key)
        return made, skipped

    def _journal(self, key: str, kind: str, names: list[str], api: ExtrasApi, source: str) -> None:
        if not names:
            return
        held = {f["name"]: f for f in api.files_of(api.rom(key), kind)}
        with self._lock:
            c = self._db()
            try:
                for n in names:
                    if n in held:
                        c.execute("INSERT INTO added(key,kind,file_id,name,size,source,ts) VALUES(?,?,?,?,?,?,?)",
                                  (key, kind, held[n]["id"], n, held[n]["size"], source[:200], time.time()))
                c.commit()
            finally:
                c.close()

    def _finish(self, job: dict, kind: str, made: int, skipped: int, what: str = "") -> None:
        label = word(kind)
        job.update(state="done", made=made, skipped=skipped, pct=1.0, step="Done",
                   message=(f"Added {made} {label} file{'s' if made != 1 else ''}" + (f" from {what}" if what else "") +
                            (f"; {skipped} skipped (already there or refused by RomM)" if skipped else "")))

    def _fail(self, job: dict, ex: Exception, api: RommApi | None) -> None:
        log.warning("%s upload for %s failed: %s", job["extra"], job["game_id"], ex.__class__.__name__)
        job.update(state="error", step="Failed", message=_reason(ex, api))

    # -- sources: local files (an upload from the browser, a link, an Internet Archive file) --
    def start_files(self, game: dict, kind: str, api: ExtrasApi, files: list[tuple[str, str, int]], source: str,
                    cleanup: bool = True, run_async: bool = True) -> dict:
        """Upload files that already sit on this machine. They are deleted afterwards when `cleanup` is set."""
        self._check_kind(kind)
        files = [f for f in files if allowed_file(kind, f[0])]
        if not files:
            raise ValueError(f"nothing to add: that is not a type that goes in the {word(kind)} folder")
        job = self._begin_job(str(game["id"]), kind, game["name"], source)
        self._spawn(self._run_files, job, game, kind, api, files, source, cleanup, run_async=run_async)
        return dict(job)

    def _run_files(self, job, game, kind, api, files, source, cleanup) -> None:
        try:
            made, skipped = self._upload_files(job, game, kind, api, files, source)
            self._finish(job, kind, made, skipped)
        except Exception as ex:  # noqa: BLE001
            self._fail(job, ex, api)
        finally:
            if cleanup:
                for _n, path, _s in files:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            job["finished"] = time.time()

    def start_link(self, game: dict, kind: str, api: ExtrasApi, url: str, run_async: bool = True) -> dict:
        """Fetch a public link, then upload what it is."""
        self._check_kind(kind)
        url = str(url or "").strip()
        if not re.match(r"https?://", url, re.I):
            raise ValueError("the link must start with http:// or https://")
        job = self._begin_job(str(game["id"]), kind, game["name"], "link")
        self._spawn(self._run_link, job, game, kind, api, url, run_async=run_async)
        return dict(job)

    def _run_link(self, job, game, kind, api, url) -> None:
        tmp = None
        try:
            name, tmp, size = fetch_link(url, self.tmp_dir, kind, self._progress(job))
            made, skipped = self._upload_files(job, game, kind, api, [(name, tmp, size)], "link:" + (urlparse(url).hostname or ""))
            self._finish(job, kind, made, skipped, urlparse(url).hostname or "")
        except Exception as ex:  # noqa: BLE001
            self._fail(job, ex, api)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            job["finished"] = time.time()

    def start_archive(self, game: dict, kind: str, api: ExtrasApi, item: str, name: str, run_async: bool = True) -> dict:
        """Fetch one file of an Internet Archive item (chosen from `archive_item_files`) and upload it."""
        self._check_kind(kind)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]*", str(item or "")):
            raise ValueError("not an Internet Archive identifier")
        if not name or not allowed_file(kind, str(name)):
            raise ValueError("that file does not fit this folder")
        url = "https://archive.org/download/" + quote(item) + "/" + quote(str(name))
        job = self._begin_job(str(game["id"]), kind, game["name"], "archive")
        self._spawn(self._run_archive, job, game, kind, api, url, item, run_async=run_async)
        return dict(job)

    def _run_archive(self, job, game, kind, api, url, item) -> None:
        tmp = None
        try:
            name, tmp, size = fetch_link(url, self.tmp_dir, kind, self._progress(job))
            made, skipped = self._upload_files(job, game, kind, api, [(name, tmp, size)], "archive:" + item)
            self._finish(job, kind, made, skipped, "the Internet Archive")
        except Exception as ex:  # noqa: BLE001
            self._fail(job, ex, api)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            job["finished"] = time.time()

    def stage_path(self) -> str:
        """A fresh temp path for an upload being received."""
        os.makedirs(self.tmp_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="up-", dir=self.tmp_dir)
        os.close(fd)
        return path

    # -- torrents --
    def add_watch(self, key: str, kind: str, tag: str, release: str) -> int:
        now = time.time()
        with self._lock:
            c = self._db()
            try:
                c.execute("UPDATE watch SET state='cancelled', updated=? WHERE key=? AND kind=? AND state NOT IN ('added','failed','lost','cancelled')",
                          (now, key, kind))
                cur = c.execute("INSERT INTO watch(key,kind,tag,release,state,message,pct,added,updated,seen) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (key, kind, tag, release[:300], "downloading", "Waiting for the torrent to start", 0.0, now, now, now))
                c.commit()
                return int(cur.lastrowid)
            finally:
                c.close()

    def _set_watch(self, wid: int, **kw) -> None:
        with self._lock:
            c = self._db()
            try:
                for k, v in kw.items():
                    if k not in ("state", "message", "pct", "seen"):
                        raise ValueError(k)
                    c.execute(f"UPDATE watch SET {k}=? WHERE id=?", (v, wid))
                c.execute("UPDATE watch SET updated=? WHERE id=?", (time.time(), wid))
                c.commit()
            finally:
                c.close()

    def active_watches(self) -> list[dict]:
        c = self._db()
        try:
            return [dict(r) for r in c.execute("SELECT * FROM watch WHERE state NOT IN ('added','failed','lost','cancelled') ORDER BY id")]
        finally:
            c.close()

    def watch_for(self, key: str, kind: str) -> dict | None:
        c = self._db()
        try:
            r = c.execute("SELECT * FROM watch WHERE key=? AND kind=? ORDER BY (state NOT IN ('added','failed','lost','cancelled')) DESC, id DESC",
                          (key, kind)).fetchone()
        finally:
            c.close()
        return dict(r) if r else None

    def cancel_watch(self, key: str, kind: str) -> None:
        with self._lock:
            c = self._db()
            try:
                c.execute("UPDATE watch SET state='cancelled', message='Stopped watching; the torrent is still in your download client', "
                          "updated=? WHERE key=? AND kind=? AND state NOT IN ('added','failed','lost','cancelled')", (time.time(), key, kind))
                c.commit()
            finally:
                c.close()

    def process_watches(self, rows: list[dict], resolve: Callable[[str], tuple[dict, ExtrasApi]],
                        map_path: Callable[[str], str]) -> list[str]:
        """One pass over the watched torrents (`rows` = the client's torrents in the extras category)."""
        notes = []
        for w in self.active_watches():
            row = next((r for r in rows if w["tag"] in {t.strip() for t in str(r.get("tags") or "").split(",")}), None)
            now = time.time()
            if row is None:
                if now - (w["seen"] or w["added"]) > WATCH_LOST_AFTER:
                    self._set_watch(w["id"], state="lost", message="The torrent is no longer in the download client")
                    notes.append(f"{w['release']}: lost")
                continue
            pct = float(row.get("progress") or 0.0)
            st = str(row.get("state") or "").lower()
            if "error" in st and "missing" in st:
                self._set_watch(w["id"], state="failed", message="The download client reports missing files", seen=now)
                continue
            if pct < 1.0:
                self._set_watch(w["id"], pct=pct, seen=now, state="downloading",
                                message=f"Downloading {pct * 100:.0f}%" + (f", {int(row['num_seeds'])} seeders" if row.get("num_seeds") else ""))
                continue
            try:
                game, api = resolve(w["key"])
            except (LookupError, RuntimeError, ValueError):
                self._set_watch(w["id"], pct=1.0, seen=now, message="Finished; waiting for the RomM library to load")
                continue
            path = map_path(str(row.get("content_path") or row.get("save_path") or ""))
            self._set_watch(w["id"], pct=1.0, seen=now, state="importing", message="Download finished; choosing files")
            try:
                done = self._import_torrent(w, game, api, path, str(row.get("name") or w["release"]))
            except JobBusy:
                self._set_watch(w["id"], state="downloading", message="Finished; waiting for the current job on this game")
                continue
            except Exception as ex:  # noqa: BLE001 - recorded on the watch, never raised into the scheduler
                log.warning("extras torrent import for %s failed: %s", w["key"], ex.__class__.__name__)
                self._set_watch(w["id"], state="failed", message=_reason(ex, api)[:300])
                continue
            notes.append(f"{w['release']}: {done}")
        return notes

    def _import_torrent(self, w: dict, game: dict, api: ExtrasApi, path: str, name: str) -> str:
        kind = w["kind"]
        files, zips = torrent_files(path, kind)
        members = zip_docs(zips) if KINDS[kind]["docs"] else []
        if not files and not members:
            hint = ""
            if not os.path.exists(path):
                hint = f"; the path {path!r} is not visible to ROMarr (mount it or add a remote path mapping)"
            self._set_watch(w["id"], state="failed", message=(f"Nothing in the torrent fits the {word(kind)} folder" + hint)[:300])
            return "nothing to add"
        if len(files) + len(members) > MAX_TORRENT_FILES:
            self._set_watch(w["id"], state="failed", message=f"The torrent holds {len(files) + len(members)} files, which is more than "
                            f"ROMarr files automatically ({MAX_TORRENT_FILES}); it looks like the wrong release")
            return "too many files"
        job = self._begin_job(str(game["id"]), kind, game["name"], "torrent")
        self._spawn(self._run_torrent, job, w, game, kind, api, files, members, name, run_async=False)
        if job["state"] == "error":
            self._set_watch(w["id"], state="failed", message=job["message"][:300])
            return "failed"
        made = job["made"]
        self._set_watch(w["id"], state="added" if made else "failed",
                        message=(f"Added {made} file{'s' if made != 1 else ''}" + (f"; {job['skipped']} skipped" if job["skipped"] else ""))
                        if made else "Everything in the torrent was already on this game or refused by RomM")
        return f"added {made}"

    def _run_torrent(self, job, w, game, kind, api, files, members, name) -> None:
        extracted: list[tuple[str, str, int]] = []
        try:
            for stored, zp, member in members:
                os.makedirs(self.tmp_dir, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix="zm-", dir=self.tmp_dir)
                with zipfile.ZipFile(zp) as z, z.open(member) as src, os.fdopen(fd, "wb") as dst:
                    left = z.getinfo(member).file_size
                    while True:
                        b = src.read(1 << 20)
                        if not b:
                            break
                        left -= len(b)
                        if left < 0:
                            raise ValueError(f"{member} is larger than its header says")
                        dst.write(b)
                extracted.append((stored, tmp, os.path.getsize(tmp)))
            everything = pick_files(kind, files + extracted)
            made, skipped = self._upload_files(job, game, kind, api, everything, "torrent:" + name)
            self._finish(job, kind, made, skipped, "a torrent")
        except Exception as ex:  # noqa: BLE001
            self._fail(job, ex, api)
        finally:
            for _n, tmp, _s in extracted:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            job["finished"] = time.time()

    # -- undo --
    def undo(self, game: dict, kind: str, api: ExtrasApi) -> dict:
        """Remove exactly what this module added to the game's folder of this kind, by RomM's file ids."""
        self._check_kind(kind)
        key = str(game["id"])
        self._ensure_idle(key, kind)
        c = self._db()
        try:
            rows = c.execute("SELECT * FROM added WHERE key=? AND kind=? AND undone=0", (key, kind)).fetchall()
        finally:
            c.close()
        removed = 0
        for r in rows:
            try:
                if api.delete_file(key, r["file_id"], kind):
                    removed += 1
            except RommError as ex:
                if ex.status in (401, 403):
                    raise ValueError("RomM refused the removal: the library login needs permission to delete ROM files") from ex
                raise
            with self._lock:
                c = self._db()
                try:
                    c.execute("UPDATE added SET undone=1 WHERE id=?", (r["id"],))
                    c.commit()
                finally:
                    c.close()
        return {"removed": removed, "remaining": self.journal_count(key, kind)}


def purge_tmp(tmp_dir: str) -> None:
    """Drop temp files a killed process left behind. Only called on startup."""
    shutil.rmtree(tmp_dir, ignore_errors=True)
