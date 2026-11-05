"""Game soundtracks: find them, upload them into RomM's Jukebox, take them back.

A port of the core of the standalone romm-soundtracks tool, so ROMarr is one
application rather than two. This is phase 1 and deliberately small:

  * search Zophar's Domain and the Internet Archive for a game's soundtrack,
    rank what comes back, and list the manual-search sites for the rest;
  * download a chosen candidate, take ONLY audio out of any archive, and
    upload each file through RomM's own API (`POST /api/roms/{id}/soundtracks`)
    so RomM creates `soundtrack/`, registers the tracks and, for a lone ROM,
    moves it into a folder first. ROMarr never writes to the ROM tree;
  * journal exactly what was added (RomM's file ids) so Undo removes that and
    nothing else.

Safety rules, kept from the original because they are the point of it:

  * never overwrite -- a track RomM already has under that name is skipped;
  * only undo what this module added, by the file id RomM gave back;
  * a folder is only ever created by RomM, and only when a real file is being
    sent, so no empty `soundtrack/` is left behind;
  * one request per second per host, with a User-Agent that says who is asking;
  * archives are never extracted to disk: members are streamed out one at a
    time, names are flattened (no path traversal), only audio extensions are
    read, and an archive larger than 6 GB is refused.

Authentication is whatever the RomM library entry already has (see
`Romm.write_token`); this module never stores, accepts or prints a credential.
Not here yet: duplicate merge, music-library albums, 3DS decrypt/held
originals. See docs/SOUNDTRACKS.md.
"""

from __future__ import annotations

import difflib
import html
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote, quote_plus, urlencode, urljoin, urlparse

import requests

log = logging.getLogger(__name__)

UA = "ROMarr (self-hosted game library manager; soundtrack lookup)"

#: What RomM's Jukebox accepts. Anything else is refused by RomM, so it is not
#: even offered to it.
JUKEBOX_EXT = frozenset({".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav",
                         ".flac", ".spc", ".vgm", ".vgz", ".gym"})
#: Chiptune rips that are stored by the sources but that RomM cannot play. They
#: may be read out of an archive, but phase 1 only delivers through RomM, so
#: they are counted as skipped.
CHIPTUNE_EXT = frozenset({".nsf", ".nsfe", ".gbs", ".sap", ".kss", ".hes", ".ay", ".gsf",
                          ".minigsf", ".2sf", ".mini2sf", ".usf", ".miniusf", ".psf",
                          ".minipsf", ".psf2", ".minipsf2", ".ssf", ".minissf", ".dsf",
                          ".sgc", ".s98", ".mod", ".xm", ".it", ".s3m", ".mid", ".midi"})
AUDIO_EXT = JUKEBOX_EXT | CHIPTUNE_EXT

#: Past this an archive is refused before anything is read out of it.
MAX_ARCHIVE_BYTES = 6 << 30
#: Hosts a download link may point at. A source page is third-party HTML, so a
#: link in it is not trusted to name any host it likes.
ALLOWED_HOSTS = ("zophar.net", "archive.org")

# RomM platform slug -> regex over Zophar's console label; only used to rank candidates
ZOPHAR_CONSOLE = {
    "nes": r"Nintendo NES", "fds": r"Famicom Disk|Disk System", "snes": r"SNES", "satellaview": r"SNES",
    "gb": r"Game Boy \(GBS\)", "gbc": r"Game Boy \(GBS\)|Game Boy Color", "gba": r"Game Boy Advance",
    "n64": r"Nintendo 64", "nds": r"Nintendo DS", "3ds": r"3DS", "ngc": r"GameCube", "wii": r"Wii(?! U)",
    "psx": r"^Playstation( \(|$)", "psp": r"PSP|Portable", "genesis": r"Genesis|Mega Drive", "segacd": r"Sega CD|Mega CD",
    "sms": r"Master System", "gamegear": r"Game Gear", "tg16": r"PC Engine|TurboGrafx", "turbografx-cd": r"PC Engine|TurboGrafx",
    "arcade": r"Arcade", "cps3": r"Arcade", "model2": r"Arcade", "neogeoaes": r"Neo.?Geo|Arcade", "c64": r"Commodore 64",
    "dos": r"MS-DOS", "atari2600": r"Atari 2600", "atari5200": r"Atari 5200", "atari7800": r"Atari 7800", "lynx": r"Lynx",
    "colecovision": r"Coleco", "zxs": r"Spectrum", "vectrex": r"Vectrex", "ps3": r"Playstation 3", "xbox360": r"360",
}
# Consoles whose "original" rip format RomM's Jukebox can actually play
JUKEBOX_NATIVE = r"\(SPC\)|\(VGM\)|Genesis|Mega Drive|Master System|Game Gear|\(GYM\)"


# ------------------------------------------------------------------ titles --

def clean_title(name: str, is_folder: bool = False) -> str:
    """A ROM file name as a plain game title: no extension, no (tags), "Legend, The" -> "The Legend"."""
    base = name
    if not is_folder:
        stem, ext = os.path.splitext(name)
        if 1 < len(ext) <= 5 and ext[1:].isalnum():
            base = stem
    base = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", base).replace("_", " ")
    m = re.match(r"^(.*?),\s*(The|A|An)$", base.strip())
    if m:
        base = f"{m.group(2)} {m.group(1)}"
    return re.sub(r"\s+", " ", base).strip(" -.") or name


def fold(s: str) -> str:
    """Accents to ASCII (Pokémon -> Pokemon): the source sites index plain-ASCII titles."""
    return unicodedata.normalize("NFKD", html.unescape(s)).encode("ascii", "ignore").decode()


def norm(s: str) -> str:
    s = fold(s).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(version|edition)\b", " ", s)         # "Pokemon LeafGreen Version" == "Pokemon LeafGreen"
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^the ", "", s)


def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3) if a and b else 0.0


def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .")
    return s or "_"


def header_safe(name: str) -> str:
    """RomM reads the file name from an HTTP header, which can only carry Latin-1."""
    try:
        name.encode("latin-1")
        return name
    except UnicodeEncodeError:
        stem, ext = os.path.splitext(name)
        folded = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode().strip(" .")
        return (folded or "track-" + uuid.uuid4().hex[:6]) + ext


_EXT = re.compile(r"\.(([a-z]+\.)*\w+)$")      # RomM's own extension pattern


def stem_stable(file_name: str) -> bool:
    """Would RomM keep the same name for this ROM once it lives in a folder named after it?

    RomM recomputes the name from the folder name with the same extension
    pattern, so a stem that itself ends in '.<word>' ("Game v1.2") loses that
    tail, and anything matching device saves by that name stops finding them.
    """
    stem = _EXT.sub("", file_name).strip()
    return _EXT.sub("", stem).strip() == stem


def manual_links(title: str, platform_name: str) -> list[dict]:
    """Search pages worth opening by hand. Sites behind a bot challenge are never scraped, only linked."""
    q = quote_plus
    return [
        {"name": "KHInsider", "url": "https://downloads.khinsider.com/search?search=" + q(title)},
        {"name": "VGMRips", "url": "https://vgmrips.net/packs/search?q=" + q(title)},
        {"name": "Zophar's Domain", "url": "https://www.zophar.net/music/search?search=" + q(title)},
        {"name": "Internet Archive", "url": "https://archive.org/search?query=" + q(title + " soundtrack") + "&and[]=mediatype%3Aaudio"},
        {"name": "MusicBrainz", "url": "https://musicbrainz.org/search?type=release_group&query=" + q(title + " soundtrack")},
        {"name": "Bandcamp", "url": "https://bandcamp.com/search?q=" + q(title + " soundtrack")},
        {"name": "YouTube", "url": "https://www.youtube.com/results?search_query=" + q(f"{title} {platform_name} soundtrack")},
    ]


def best_for_auto(cands: list[dict], threshold: float) -> dict | None:
    """The one candidate safe to take without a person looking: same platform and a near-exact title."""
    for x in cands:
        if x["platform_match"] and x["score"] >= threshold:
            return x
    return None


# -------------------------------------------------------------- polite HTTP --

_last: dict[str, float] = {}
_gap_lock = threading.Lock()


def _wait_turn(host: str, gap: float = 1.0) -> None:
    """Block until `host` has not been asked for `gap` seconds. The slot is claimed
    under the lock, so concurrent jobs queue behind one another instead of racing."""
    with _gap_lock:
        now = time.time()
        at = max(now, _last.get(host, 0.0) + gap)
        _last[host] = at
    if at > now:
        time.sleep(at - now)


def allowed_url(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def polite_get(url: str, binary: bool = False, gap: float = 1.0):
    """GET one page, at most one request per second per host."""
    _wait_turn(urlparse(url).netloc, gap)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
    r.raise_for_status()
    return r.content if binary else r.content.decode("utf-8", "replace")


def stream(url: str, on_total: Callable[[int], None] | None = None) -> Iterator[bytes]:
    """Stream one file in 1 MiB chunks. The request itself waits its turn like any other."""
    if not allowed_url(url):
        raise ValueError("download link points outside the supported sources")
    _wait_turn(urlparse(url).netloc)
    with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=60) as r:
        r.raise_for_status()
        if on_total and r.headers.get("Content-Length", "").isdigit():
            on_total(int(r.headers["Content-Length"]))
        yield from r.iter_content(1 << 20)


# ---------------------------------------------------------------- providers --

def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def zophar_search(title: str, platform: str) -> list[dict]:
    out, seen = [], set()
    title = fold(title)
    # the site's search wants every word in its title, so lead with the form without "Version"/"Edition"
    queries: list[str] = []
    for q in (norm(title), title, re.split(r"\s*[:\-–]\s+", title)[0]):
        q = " ".join(q.split())
        if q and q not in queries:
            queries.append(q)
    for q in queries:
        page = polite_get("https://www.zophar.net/music/search?" + urlencode({"search": q}))
        for m in re.finditer(r'<tr class="regularrow[^"]*">(.*?)</tr>', page, re.S):
            row = m.group(1)
            a = re.search(r'<td class="name"><a href="(/music/[^"]+)">(.*?)</a>', row, re.S)
            if not a or a.group(1) in seen:
                continue
            seen.add(a.group(1))
            cons = _text((re.search(r'<td class="console">(.*?)</td>', row, re.S) or [0, ""])[1])
            year = _text((re.search(r'<td class="year">(.*?)</td>', row, re.S) or [0, ""])[1])
            name = _text(a.group(2))
            plat_ok = bool(re.search(ZOPHAR_CONSOLE.get(platform, r"(?!x)x"), cons))
            out.append({"provider": "zophar", "id": a.group(1), "title": name, "console": cons, "year": year,
                        "url": "https://www.zophar.net" + a.group(1), "platform_match": plat_ok,
                        "score": similarity(title, name), "jukebox_original": bool(re.search(JUKEBOX_NATIVE, cons))})
        if out:
            break
    return out


def valid_zophar_id(cand_id: str) -> bool:
    return bool(re.fullmatch(r"/music/[A-Za-z0-9._~%/\-]+", cand_id)) and ".." not in cand_id.split("/")


def zophar_plan(cand_id: str) -> dict:
    if not valid_zophar_id(cand_id):
        raise ValueError("not a Zophar music page")
    base = "https://www.zophar.net" + cand_id
    page = polite_get(base)
    box = re.search(r'<div id="mass_download">(.*?)</div>', page, re.S)
    plans = []
    for m in re.finditer(r'<a href="([^"]+)">\s*<p>(.*?)</p>', box.group(1) if box else "", re.S):
        label = _text(m.group(2))
        kind = "mp3" if "mp3" in label.lower() else "original" if "original" in label.lower() else "flac" if "flac" in label.lower() else "other"
        plans.append({"kind": kind, "label": label, "url": urljoin(base, html.unescape(m.group(1)))})
    tracks = len(re.findall(r'class="regularrow trackrow"', page))
    return {"downloads": plans, "tracks": tracks}


def archive_search(title: str, platform: str) -> list[dict]:
    words = " ".join(norm(title).split())          # already accent-folded
    q = f'title:({words}) AND mediatype:audio AND (subject:soundtrack OR subject:"video game" OR title:soundtrack OR title:ost)'
    url = "https://archive.org/advancedsearch.php?" + urlencode(
        {"q": q, "fl[]": ["identifier", "title", "item_size", "downloads"], "rows": 8, "output": "json"}, doseq=True)
    docs = json.loads(polite_get(url))["response"]["docs"]
    return [{"provider": "archive", "id": d["identifier"], "title": d.get("title", d["identifier"]), "console": "Internet Archive",
             "year": "", "url": "https://archive.org/details/" + d["identifier"], "platform_match": False,
             "score": similarity(title, d.get("title", "")), "size": d.get("item_size"), "jukebox_original": False} for d in docs]


def archive_plan(ident: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]*", ident):
        raise ValueError("not an Internet Archive identifier")
    meta = json.loads(polite_get("https://archive.org/metadata/" + quote(ident)))
    files = [f for f in meta.get("files", []) if f.get("source") == "original" and os.path.splitext(f["name"])[1].lower() in JUKEBOX_EXT]
    base = "https://archive.org/download/" + quote(ident) + "/"
    return {"downloads": [{"kind": "files", "label": f"{len(files)} audio files from the item", "files": [
        {"url": base + quote(f["name"]), "name": os.path.basename(f["name"])} for f in files]}], "tracks": len(files)}


PROVIDERS: dict[str, tuple[Callable, Callable]] = {
    "zophar": (zophar_search, zophar_plan), "archive": (archive_search, archive_plan)}

#: Download formats a candidate offers, before its page is opened. The real set
#: comes from the plan at download time, which refuses a format that is absent.
FORMATS = {"zophar": ["mp3", "original"], "archive": ["files"]}


# ----------------------------------------------------------------- archives --

def audio_member_name(filename: str) -> str | None:
    """The flat name to store a zip member under, or None when it is not audio worth taking.

    The member's own path is discarded (`../../etc/x.mp3` becomes `x.mp3`), so
    nothing can land outside wherever the caller puts it.
    """
    name = os.path.basename(filename.replace("\\", "/"))
    if not name or name.startswith(".") or os.path.splitext(name)[1].lower() not in AUDIO_EXT:
        return None
    return name


def check_zip(path: str, limit: int = MAX_ARCHIVE_BYTES) -> int:
    """Refuse an archive whose declared contents exceed `limit`; returns how many audio members it holds."""
    with zipfile.ZipFile(path) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > limit:
            raise ValueError("archive too large (>6 GB)")
        return sum(1 for i in infos if audio_member_name(i.filename))


def iter_zip_audio(path: str, limit: int = MAX_ARCHIVE_BYTES) -> Iterator[tuple[str, Iterator[bytes]]]:
    """Yield (flat name, chunks) for each audio member of a zip, lazily and without extracting to disk.

    Each member's chunks must be consumed before asking for the next, while the
    generator (and so the archive) is still open. Non-audio members are never
    opened. A member that decompresses to more than its header declared is cut
    off, so a lying header cannot get past the size cap.
    """
    check_zip(path, limit)
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            name = None if i.is_dir() else audio_member_name(i.filename)
            if name is None:
                continue

            def chunks(info=i):
                left = info.file_size
                with z.open(info) as src:
                    while True:
                        b = src.read(1 << 20)
                        if not b:
                            return
                        left -= len(b)
                        if left < 0:
                            raise ValueError(f"{info.filename} is larger than its header says")
                        yield b
            yield name, chunks()


def do_download(item: dict, sink: Callable[[str, Iterator[bytes]], int | None], tmp_dir: str,
                progress: Callable[..., None], limit: int = MAX_ARCHIVE_BYTES) -> tuple[int, int]:
    """Fetch one download and hand each audio file in it to `sink(name, chunks)`.

    `sink` returns the bytes it took, or None when it skipped the file. Returns
    (made, skipped). A plain-files item (Internet Archive) is streamed file by
    file; anything else is a zip, saved to a temp file in `tmp_dir` and removed.
    """
    made = skipped = 0
    if item.get("files"):
        n = len(item["files"])
        for i, f in enumerate(item["files"]):
            progress(f"Adding track {i + 1} of {n}", pct=i / n)
            name = os.path.basename(f["name"])
            if os.path.splitext(name)[1].lower() not in AUDIO_EXT:
                skipped += 1
                continue
            w = sink(name, stream(f["url"]))
            made, skipped = (made + 1, skipped) if w is not None else (made, skipped + 1)
        return made, skipped
    if not allowed_url(item["url"]):
        raise ValueError("download link points outside the supported sources")
    os.makedirs(tmp_dir, exist_ok=True)
    fd, tmpzip = tempfile.mkstemp(prefix="dl-", suffix=".zip", dir=tmp_dir)
    try:
        total = [0]
        done = 0
        with os.fdopen(fd, "wb") as f:
            for b in stream(item["url"], lambda n: total.__setitem__(0, n)):
                f.write(b)
                done += len(b)
                if done > limit:
                    raise ValueError("archive too large (>6 GB)")
                progress("Downloading the soundtrack", pct=(done / total[0]) if total[0] else None)
        total_members = check_zip(tmpzip, limit)
        for k, (name, chunks) in enumerate(iter_zip_audio(tmpzip, limit)):
            progress(f"Adding track {k + 1} of {total_members}", pct=k / max(total_members, 1))
            w = sink(name, chunks)
            made, skipped = (made + 1, skipped) if w is not None else (made, skipped + 1)
    finally:
        try:
            os.unlink(tmpzip)
        except OSError:
            pass
    return made, skipped


# --------------------------------------------------------------------- RomM --

class RommError(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"RomM answered {status}" + (f": {body}" if body else ""))
        self.status = status


class _Multipart:
    """A one-file multipart/form-data body RomM's streaming parser accepts.

    Sized up front (`__len__`) so the request carries a Content-Length rather
    than chunked encoding, and read from disk a megabyte at a time.
    """

    def __init__(self, name: str, path: str, size: int, boundary: str):
        self.boundary = boundary
        self.head = (f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n').encode("latin-1")
        self.tail = f"\r\n--{self.boundary}--\r\n".encode()
        self.path, self.size = path, size
        self._fh = None
        self._stage = 0

    def __len__(self) -> int:
        return len(self.head) + self.size + len(self.tail)

    def read(self, n: int = -1) -> bytes:
        if self._stage == 0:
            self._stage, self._fh = 1, open(self.path, "rb")
            return self.head
        if self._stage == 1:
            b = self._fh.read(1 << 20 if n is None or n < 0 else n)
            if b:
                return b
            self._fh.close()
            self._stage = 2
            return self.tail
        return b""

    def __iter__(self):
        while True:
            b = self.read(1 << 20)
            if not b:
                return
            yield b

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.close()


class RommApi:
    """The few RomM calls soundtracks needs, authenticated by the library entry's own login.

    `token_fn(refresh)` returns a bearer token (see `Romm.write_token`); a 401 is
    retried once with a fresh one. The token is only ever put in a request
    header, and is scrubbed from any text this class raises.
    """

    def __init__(self, base_url: str, token_fn: Callable[[bool], str | None], session: requests.Session | None = None):
        self.base = base_url.rstrip("/")
        self._token_fn = token_fn
        self._session = session or requests.Session()

    def _redact(self, text: str) -> str:
        tok = self._token_fn(False) or ""
        return text.replace(tok, "***") if tok and len(tok) > 6 else text

    def _request(self, method: str, path: str, make_body: Callable[[], object] | None = None,
                 headers: dict | None = None, timeout: int = 60) -> requests.Response:
        for attempt in (0, 1):
            tok = self._token_fn(bool(attempt))
            if not tok:
                raise RommError(401, "ROMarr could not sign in to RomM with the saved library login")
            body = make_body() if make_body else None
            try:
                r = self._session.request(method, self.base + path, data=body, timeout=timeout,
                                          headers={"Authorization": "Bearer " + tok, "User-Agent": UA, **(headers or {})})
            finally:
                if hasattr(body, "close"):
                    body.close()
            if r.status_code != 401 or attempt:
                return r
        return r

    def json(self, method: str, path: str):
        r = self._request(method, path)
        if not r.ok:
            raise RommError(r.status_code, self._redact(r.text[:300]))
        return r.json() if r.content else None

    def rom(self, rom_id: str) -> dict:
        return self.json("GET", f"/api/roms/{int(rom_id)}") or {}

    def tracks(self, rom_id: str) -> list[dict]:
        """The soundtrack files RomM holds for this ROM: [{file_name, file_id, ...}]."""
        out = self.json("GET", f"/api/roms/{int(rom_id)}/soundtracks/metadata")
        return out if isinstance(out, list) else []

    def upload(self, rom_id: str, name: str, path: str, size: int) -> None:
        """POST one file as multipart whose part is named after the file, with its name in x-upload-filename too."""
        boundary = "----romarr" + uuid.uuid4().hex
        # A fresh body per attempt: a retry after a 401 has to start from byte 0.
        r = self._request("POST", f"/api/roms/{int(rom_id)}/soundtracks",
                          make_body=lambda: _Multipart(name, path, size, boundary),
                          headers={"x-upload-filename": name, "Content-Type": "multipart/form-data; boundary=" + boundary},
                          timeout=600)
        if r.status_code != 201:
            raise RommError(r.status_code, self._redact(r.text[:300]))

    def delete_track(self, rom_id: str, file_id: str) -> bool:
        """Remove one registered soundtrack file. A file RomM no longer has counts as already gone."""
        r = self._request("DELETE", f"/api/roms/{int(rom_id)}/soundtracks/{int(file_id)}")
        if r.status_code == 404:
            return False
        if not r.ok:
            raise RommError(r.status_code, self._redact(r.text[:300]))
        return True


class RommSink:
    """Sends each file to RomM instead of writing it, skipping what RomM already has."""

    def __init__(self, api: RommApi, rom_id: str, tmp_dir: str):
        self.api, self.rom_id, self.tmp_dir = api, str(rom_id), tmp_dir
        self.sent: list[str] = []
        self.refused: list[str] = []
        self.existing = {t["file_name"] for t in api.tracks(self.rom_id)}

    def __call__(self, name: str, data_iter: Iterator[bytes]) -> int | None:
        name = header_safe(safe_name(os.path.basename(name)))
        if name.startswith(".") or os.path.splitext(name)[1].lower() not in JUKEBOX_EXT or name in self.existing:
            return None                                                  # not something RomM's Jukebox accepts, or already there
        os.makedirs(self.tmp_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="up-", dir=self.tmp_dir)
        size = 0
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in data_iter:
                    f.write(chunk)
                    size += len(chunk)
            try:
                self.api.upload(self.rom_id, name, tmp, size)
            except RommError as ex:
                if ex.status in (400, 409):                              # this one file is unacceptable; carry on with the rest
                    log.info("RomM refused %s: %s", name, ex)
                    self.refused.append(name)
                    return None
                raise
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        self.sent.append(name)
        self.existing.add(name)
        return size


# ------------------------------------------------------------------ storage --

DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sound(key TEXT PRIMARY KEY, status TEXT, cands TEXT, chosen TEXT, files INT DEFAULT 0,
    dest TEXT, provider TEXT, note TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, key TEXT, path TEXT, size INT, ts REAL, undone INT DEFAULT 0);
"""


def db_path_for(data_file: str) -> Path:
    """The sqlite file that sits beside ROMarr's own data file (ROMARR_DATA)."""
    return Path(data_file).parent / "romarr-soundtracks.db"


class Soundtracks:
    """Search, download-through-RomM and undo for one ROMarr install.

    The caller supplies the per-game facts (`game`: id, name, platform_slug,
    platform_name) and a `RommApi` for it; nothing here knows ROMarr's service
    class, which keeps it testable with a fake RomM and a temp directory.
    """

    MAX_JOBS = 50

    def __init__(self, db_path: str | os.PathLike, providers: dict | None = None):
        self.db_path = Path(db_path)
        self.tmp_dir = str(self.db_path.parent / "soundtracks-tmp")
        self.providers = providers if providers is not None else PROVIDERS
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

    def _set_sound(self, key: str, **kw) -> None:
        with self._lock:
            c = self._db()
            try:
                c.execute("INSERT OR IGNORE INTO sound(key,status,ts) VALUES(?,?,?)", (key, "unsearched", time.time()))
                for k, v in kw.items():
                    if k not in ("status", "cands", "chosen", "files", "dest", "provider", "note"):
                        raise ValueError(k)
                    c.execute(f"UPDATE sound SET {k}=? WHERE key=?", (v, key))
                c.execute("UPDATE sound SET ts=? WHERE key=?", (time.time(), key))
                c.commit()
            finally:
                c.close()

    def _journal_count(self, key: str) -> int:
        c = self._db()
        try:
            return c.execute("SELECT COUNT(*) FROM journal WHERE key=? AND undone=0", (key,)).fetchone()[0]
        finally:
            c.close()

    # -- status --
    def status(self, game: dict, api: RommApi | None) -> dict:
        key = str(game["id"])
        c = self._db()
        try:
            s = c.execute("SELECT * FROM sound WHERE key=?", (key,)).fetchone()
        finally:
            c.close()
        tracks, error = None, ""
        if api is not None:
            try:
                tracks = [{"name": t.get("file_name", ""), "id": t.get("file_id")} for t in api.tracks(key)]
            except (RommError, requests.RequestException, ValueError) as ex:
                error = f"Could not ask RomM what it holds: {ex.__class__.__name__}"
        else:
            error = "No RomM library is configured"
        return {"id": key, "title": game.get("name", ""), "tracks": tracks, "track_count": len(tracks) if tracks is not None else None,
                "undoable": self._journal_count(key), "state": s["status"] if s else "unsearched",
                "note": (s["note"] if s else "") or "", "provider": (s["provider"] if s else "") or "",
                "job": self.job_for(key), "error": error}

    # -- search --
    def search(self, game: dict, enabled: tuple[str, ...] = ("zophar", "archive")) -> dict:
        key, title = str(game["id"]), game["name"]
        cands: list[dict] = []
        errors: list[str] = []
        for name, (search_fn, _) in self.providers.items():
            if name not in enabled:
                continue
            try:
                found = search_fn(title, game.get("platform_slug", ""))
            except Exception as ex:  # noqa: BLE001 - one dead source must not hide the others
                log.warning("%s search failed: %s", name, ex.__class__.__name__)
                errors.append(f"{name}: {ex.__class__.__name__}")
                continue
            cands += found
        cands = [x for x in cands if x["score"] >= 0.45]
        seen, uniq = set(), []
        for x in sorted(cands, key=lambda x: (x["platform_match"], x["score"]), reverse=True):
            if (x["provider"], x["id"]) not in seen:
                seen.add((x["provider"], x["id"]))
                x["formats"] = FORMATS.get(x["provider"], [])
                uniq.append(x)
        uniq = uniq[:8]
        self._set_sound(key, status="found" if uniq else "none", cands=json.dumps(uniq))
        return {"id": key, "title": title, "candidates": uniq, "errors": errors,
                "links": manual_links(title, game.get("platform_name", ""))}

    # -- jobs --
    def job_for(self, key: str) -> dict | None:
        """The running job for a game, else its most recent finished one."""
        with self._lock:
            mine = [j for j in self._jobs.values() if j["game_id"] == key]
        mine.sort(key=lambda j: j["started"])
        running = [j for j in mine if j["state"] == "running"]
        return dict(running[-1] if running else mine[-1]) if mine else None

    def jobs(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["started"], reverse=True)

    def start_download(self, game: dict, api: RommApi, cand: dict, fmt: str, run_async: bool = True) -> dict:
        """Begin a download job. One job per game at a time: a second request while one runs is refused."""
        key = str(game["id"])
        provider, cid = str(cand.get("provider") or ""), str(cand.get("id") or "")
        if provider not in self.providers:
            raise ValueError("unknown source")
        if fmt not in ("mp3", "original", "both", "files", "flac"):
            raise ValueError("unknown format")
        if provider == "zophar" and not valid_zophar_id(cid):
            raise ValueError("not a Zophar music page")
        if provider == "archive" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]*", cid):
            raise ValueError("not an Internet Archive identifier")
        with self._lock:
            if any(j["game_id"] == key and j["state"] == "running" for j in self._jobs.values()):
                raise JobBusy("a soundtrack job is already running for this game")
            job = {"id": uuid.uuid4().hex[:12], "game_id": key, "title": game["name"], "state": "running",
                   "step": "Starting", "pct": None, "made": 0, "skipped": 0, "message": "",
                   "started": time.time(), "finished": None}
            self._jobs[job["id"]] = job
            for old in sorted(self._jobs.values(), key=lambda j: j["started"])[:-self.MAX_JOBS]:
                if old["state"] != "running":
                    del self._jobs[old["id"]]
        args = (job, game, api, {"provider": provider, "id": cid}, fmt)
        if run_async:
            threading.Thread(target=self._run_download, args=args, daemon=True, name=f"soundtrack-{job['id']}").start()
        else:
            self._run_download(*args)
        return dict(job)

    def _progress(self, job: dict) -> Callable[..., None]:
        def progress(step: str, pct: float | None = None) -> None:
            job["step"], job["pct"] = step, (round(pct, 3) if pct is not None else None)
        return progress

    def _run_download(self, job: dict, game: dict, api: RommApi, cand: dict, fmt: str) -> None:
        key = job["game_id"]
        try:
            made, skipped = self._download(job, game, api, cand, fmt)
            job.update(state="done", made=made, skipped=skipped, pct=1.0, step="Done",
                       message=(f"Added {made} track{'s' if made != 1 else ''}" +
                                (f"; {skipped} skipped (already there or not a format Jukebox plays)" if skipped else "")))
        except Exception as ex:  # noqa: BLE001 - reported on the job, never raised into a thread nobody joins
            msg = api._redact(str(ex)) if isinstance(ex, RommError) else (str(ex) if isinstance(ex, ValueError) else ex.__class__.__name__)
            log.warning("soundtrack download for %s failed: %s", key, ex.__class__.__name__)
            job.update(state="error", step="Failed", message=msg)
            self._set_sound(key, note=f"download failed: {msg}"[:300])
        finally:
            job["finished"] = time.time()

    def _download(self, job: dict, game: dict, api: RommApi, cand: dict, fmt: str) -> tuple[int, int]:
        key = job["game_id"]
        progress = self._progress(job)
        progress(f"Looking up the download on {cand['provider'].capitalize()}")
        plan = self.providers[cand["provider"]][1](cand["id"])
        picks = pick_downloads(plan["downloads"], fmt)
        if not picks:
            raise ValueError(f"no '{fmt}' download is offered for this item")
        rom = api.rom(key)
        if not (rom.get("has_multiple_files") or rom.get("has_nested_single_file")) and not stem_stable(str(rom.get("fs_name") or "")):
            raise ValueError("moving this ROM into a folder would change the name RomM stores for it (its name ends in a "
                             "dotted number), which breaks name-based save matching; not downloaded")
        sink = RommSink(api, key, self.tmp_dir)
        made = skipped = 0
        try:
            for item in picks:
                m, s_ = do_download(item, sink, self.tmp_dir, progress)
                made, skipped = made + m, skipped + s_
                job["made"], job["skipped"] = made, skipped
        except RommError as ex:
            if ex.status in (401, 403):
                raise ValueError("RomM refused the upload: the library login needs permission to edit ROMs (roms.write)") from ex
            raise
        finally:
            self._record(key, sink, api)
        total = len(api.tracks(key)) if made else None
        self._set_sound(key, status="downloaded" if (made or total) else "found", files=total or 0,
                        provider=cand["provider"], chosen=json.dumps(cand),
                        note=f"{made} new file(s), {skipped} skipped (already there, or not a format RomM Jukebox plays)")
        return made, skipped

    def _record(self, key: str, sink: RommSink, api: RommApi) -> None:
        """Journal what was uploaded, with RomM's file ids, so it can be undone through RomM.

        Runs even when the job failed part-way, so a half-finished download can
        still be taken back.
        """
        if not sink.sent:
            return
        ids = {t["file_name"]: t["file_id"] for t in api.tracks(key)}
        with self._lock:
            c = self._db()
            try:
                for n in sink.sent:
                    if n in ids:
                        c.execute("INSERT INTO journal(key,path,size,ts) VALUES(?,?,?,?)",
                                  (key, f"romm://{key}/{ids[n]}/{n}", 0, time.time()))
                c.commit()
            finally:
                c.close()

    # -- undo --
    def undo(self, game: dict, api: RommApi) -> dict:
        """Remove exactly what this module added to the game, by the file ids it journaled."""
        key = str(game["id"])
        with self._lock:
            if any(j["game_id"] == key and j["state"] == "running" for j in self._jobs.values()):
                raise JobBusy("a soundtrack job is running for this game")
        c = self._db()
        try:
            rows = c.execute("SELECT * FROM journal WHERE key=? AND undone=0", (key,)).fetchall()
        finally:
            c.close()
        removed = 0
        try:
            for r in rows:
                parts = r["path"][len("romm://"):].split("/", 2) if r["path"].startswith("romm://") else []
                if len(parts) != 3 or parts[0] != key:
                    continue                                        # not ours to act on
                if api.delete_track(key, parts[1]):
                    removed += 1
                with self._lock:
                    c = self._db()
                    try:
                        c.execute("UPDATE journal SET undone=1 WHERE id=?", (r["id"],))
                        c.commit()
                    finally:
                        c.close()
        finally:
            # Committed per file above, so a failure part-way leaves the rest journaled to retry.
            left = self._journal_count(key)
            self._set_sound(key, status="unsearched" if not left else "downloaded", files=left,
                            note=f"undone: {removed} file(s) removed")
        return {"removed": removed, "remaining": self._journal_count(key)}


class JobBusy(Exception):
    pass


def pick_downloads(downloads: list[dict], fmt: str) -> list[dict]:
    """Which of a plan's downloads a format choice means. Plain file lists always count; FLAC only when asked for."""
    want = {"mp3": ["mp3"], "original": ["original"], "both": ["mp3", "original"], "flac": ["flac"]}.get(fmt, [])
    picks = [d for d in downloads if d["kind"] in want or d["kind"] == "files"]
    if not picks and fmt == "mp3":
        picks = [d for d in downloads if d["kind"] == "flac"]      # a set with no MP3 still has a lossless one
    return picks


def purge_tmp(tmp_dir: str) -> None:
    """Drop temp files a killed process left behind. Only ever called on startup."""
    shutil.rmtree(tmp_dir, ignore_errors=True)
