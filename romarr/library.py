"""Getting a finished download into RomM's library.

RomM reads a directory tree: `<library>/<platform-slug>/<rom file>`. Nothing
more clever than that is required, which is why this module is small — but the
details it does handle are the ones that silently corrupt a library:

  * archives (game releases are usually zipped or 7z'd, not bare ROMs)
  * choosing the ROM among the readmes and box art
  * never overwriting an existing ROM without being told to
  * never writing outside the library root, even if an archive contains
    `../../etc/passwd` — a real and old attack against every extractor
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .dat import BAD_DUMP, UNKNOWN, VERIFIED, Match, hash_bytes, hash_file, hash_stream
from .platforms import Platform
from .selection import pick_all_rom_sets, pick_rom_set

log = logging.getLogger(__name__)

#: Formats a finished download arrives in.
#:
#: `.zip` was the whole list, which was survivable while only cartridges were
#: supported. It is not survivable now: the live library's disc platforms are
#: overwhelmingly `.7z` -- 2,621 PlayStation entries, 2,409 PS2, 1,470 Wii --
#: and an importer that cannot open the format the content ships in supports
#: the platform on paper only.
ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                    ".tar.xz", ".txz")


def is_archive_name(name: str) -> bool:
    """Whether a file name is an archive ROMarr unpacks (compound suffixes included)."""
    lowered = str(name).lower()
    return any(lowered.endswith(s) for s in ARCHIVE_SUFFIXES)

#: How many archives deep ROMarr will look: a zip holding a 7z holding the disc.
MAX_ARCHIVE_DEPTH = 2

#: Handled by the standard library, with no tool to install.
_STDLIB_ARCHIVES = (".zip",)


def _bsdtar() -> str | None:
    """A libarchive `bsdtar`, which reads 7z, rar and zip uniformly.

    `RommStreamServer` already reaches for exactly this and for the same
    reason, so this is a second user of a proven choice rather than a new
    dependency. Windows ships it as `tar.exe`; Alpine needs
    `libarchive-tools`, which the Dockerfile installs.

    GNU tar is explicitly rejected. It answers to the same name on most Linux
    systems and cannot read a 7z, so accepting it on name alone would turn a
    missing dependency into a corrupt-archive error pointing at the download.

    Every `PATH` entry is searched rather than the first hit per name, because
    a machine with both is the normal case, not a corner: Windows ships
    libarchive as `System32\\tar.exe` while Git for Windows puts GNU tar
    earlier on the same `PATH`, and a Linux box with `libarchive-tools`
    installed alongside GNU tar looks identical. Stopping at the first binary
    called `tar` finds the one that cannot do the job and concludes the job
    cannot be done.
    """
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for name in ("bsdtar", "tar"):
            path = shutil.which(name, path=directory)
            if path and _is_libarchive(path):
                return path
    return None


def _is_libarchive(path: str) -> bool:
    try:
        out = subprocess.run([path, "--version"], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return "libarchive" in (out.stdout + out.stderr).lower()


@lru_cache(maxsize=1)
def bsdtar_path() -> str | None:
    """`_bsdtar()`, resolved once. `None` when no usable tool is installed."""
    return _bsdtar()


@dataclass(frozen=True)
class ImportResult:
    ok: bool
    destination: Path | None
    reason: str = ""
    #: What the DAT said about the bytes that actually landed. `unknown` when
    #: no DAT is loaded, which is the default and is not a failure.
    verification: Match = field(default_factory=lambda: Match(UNKNOWN))
    #: What the game is, once a metadata provider has been asked. Empty
    #: when none is configured -- metadata is an enhancement and its
    #: absence must never look like a failed import.
    info: dict = field(default_factory=dict)


def _canonical_component(value: str) -> str:
    """A DAT title as a portable filename component, never as a path."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', " ", str(value or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")[:180].rstrip(" .")
    while name and len(name.encode("utf-8")) > 180:
        name = name[:-1].rstrip(" .")
    if name.casefold() in {"", ".", ".."}:
        return ""
    if re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
                name, re.I):
        name = "_" + name
    return name


def is_safe_name(name: str, root: Path) -> bool:
    """Whether extracting `name` under `root` stays under `root`.

    Applied to every format, not only zip. The check used to live inside the
    zip reader, so adding 7z and rar would have added two formats with no
    zip-slip protection at all -- and the format an attacker chooses is the one
    with the gap.
    """
    normalized = name.replace("\\", "/")
    if (not normalized or normalized.endswith("/") or "\x00" in normalized
            or normalized.startswith("/") or ":" in normalized
            or ".." in normalized.split("/")):
        return False
    root_resolved = root.resolve()
    return (root_resolved / name).resolve().is_relative_to(root_resolved)


def safe_members(archive: zipfile.ZipFile, root: Path) -> list[str]:
    """Archive entries that stay inside `root` when extracted.

    A zip may contain absolute paths or `../` traversal. Extracting those writes
    outside the library -- the classic zip-slip. Anything that does not resolve
    inside root is dropped rather than sanitised, because a release that needs
    sanitising is not one to trust.
    """
    keep = []
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        if is_safe_name(name, root):
            keep.append(name)
        else:
            log.warning("refusing archive entry outside root: %r", name)
    return keep


class _Source:
    """Where the files of a finished download are, and how to get at them.

    Three shapes exist -- a zip, an archive only `bsdtar` can read, and a plain
    file or directory the client already unpacked -- and each answers the same
    three questions. `pick_rom_set` needs `read` to parse a `.cue`, and only
    something that knows the shape can provide it.
    """

    def names(self) -> list[str]:
        raise NotImplementedError

    def read(self, name: str) -> bytes | None:
        raise NotImplementedError

    def copy(self, name: str, destination: Path) -> None:
        raise NotImplementedError

    def hashes(self, name: str) -> dict:
        return hash_bytes(self.read(name), suffix=Path(name).suffix)

    def copy_set(self, members, stage):
        for member, name in members:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            self.copy(member, target)


class _ZipSource(_Source):
    def __init__(self, path: Path):
        self.path = path

    def names(self):
        with zipfile.ZipFile(self.path) as archive:
            return safe_members(archive, self.path.parent)

    def read(self, name):
        with zipfile.ZipFile(self.path) as archive:
            return archive.read(name)

    def copy(self, name, destination):
        with zipfile.ZipFile(self.path) as archive, \
                archive.open(name) as src, open(destination, "wb") as dst:
            shutil.copyfileobj(src, dst)

    def hashes(self, name):
        with zipfile.ZipFile(self.path) as archive, archive.open(name) as handle:
            return hash_stream(handle, suffix=Path(name).suffix,
                               size=archive.getinfo(name).file_size)

    def copy_set(self, members, stage):
        # One central-directory read for the whole game, rather than reopening
        # a potentially large ZIP once for every asset.
        with zipfile.ZipFile(self.path) as archive:
            for member, name in members:
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)


class _BsdtarSource(_Source):
    """7z and rar, via libarchive.

    Every member is read by re-invoking `bsdtar` rather than unpacking the
    archive once. A disc release is a handful of files and the sheet is a few
    hundred bytes, so the cost is small -- and unpacking the whole thing means
    materialising up to twelve gigabytes to keep four of them.
    """

    def __init__(self, path: Path, tool: str):
        self.path = path
        self.tool = tool

    def _run(self, args: list[str], **kw):
        return subprocess.run([self.tool, *args], capture_output=True,
                              check=True, timeout=600, **kw)

    def names(self):
        out = self._run(["-tf", str(self.path)], text=True)
        return [n for n in (line.strip() for line in out.stdout.splitlines())
                if n and not n.endswith("/") and is_safe_name(n, self.path.parent)]

    def read(self, name):
        return self._run(["-xOf", str(self.path), name]).stdout

    def copy(self, name, destination):
        with open(destination, "wb") as dst:
            subprocess.run([self.tool, "-xOf", str(self.path), name],
                           stdout=dst, check=True, timeout=600)

    def hashes(self, name):
        # Copier-header detection needs a member length for these small ROMs.
        if Path(name).suffix.lower() in (".smc", ".sfc", ".nes"):
            return super().hashes(name)
        with subprocess.Popen([self.tool, "-xOf", str(self.path), name],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            deadline = threading.Timer(600, process.kill)
            deadline.daemon = True
            deadline.start()
            try:
                result = hash_stream(process.stdout, suffix=Path(name).suffix)
                if process.wait() != 0:
                    raise OSError("could not read archive member")
                return result
            except BaseException:
                process.kill()
                raise
            finally:
                deadline.cancel()

    def copy_set(self, members, stage):
        # Solid 7z archives must be decoded once, rather than once per file.
        # libarchive's default traversal and symlink protections stay enabled.
        with tempfile.TemporaryDirectory(prefix=".romarr-import-", dir=stage.parent) as temp:
            extracted = Path(temp) / "files"
            extracted.mkdir()
            manifest = Path(temp) / "members"
            manifest.write_bytes(b"".join(member.encode("utf-8") + b"\0"
                                          for member, _ in members))
            subprocess.run([self.tool, "-xf", str(self.path), "-C", str(extracted),
                            "--no-same-owner", "--no-same-permissions",
                            "--null", "-T", str(manifest)],
                           check=True, timeout=600, capture_output=True)
            for member, name in members:
                source = extracted / member.replace("\\", "/")
                if (source.is_symlink() or not source.is_file()
                        or not source.resolve().is_relative_to(extracted.resolve())):
                    raise OSError("archive member is not a safe regular file")
                # Reject symlink directories too, even when their target stays
                # inside extraction: bundles preserve data, never link tricks.
                if any(parent.is_symlink() for parent in source.parents
                       if parent != extracted and parent.is_relative_to(extracted)):
                    raise OSError("archive member traverses a symlink")
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)


class _PathSource(_Source):
    """A bare ROM file, or a directory the download client already unpacked."""

    def __init__(self, path: Path):
        self.path = path

    def names(self):
        if self.path.is_file():
            return [self.path.name]
        return [str(p.relative_to(self.path)).replace("\\", "/")
                for p in self.path.rglob("*") if p.is_file()
                and not p.is_symlink()
                and p.resolve().is_relative_to(self.path.resolve())]

    def read(self, name):
        target = self.path if self.path.is_file() else self.path / name
        try:
            return target.read_bytes()
        except OSError:
            return None

    def copy(self, name, destination):
        source = self.path if self.path.is_file() else self.path / name
        # The source belongs to the download client.  Copy its bytes, not its
        # permission bits: propagating a client's private 0700/0600 mode made
        # the imported library file unreadable to the shared media group.
        # A new destination therefore follows the process umask, while the
        # source inode, owner, group and mode remain untouched.
        shutil.copyfile(source, destination)

    def hashes(self, name):
        return hash_file(self.path if self.path.is_file() else self.path / name)


class MissingArchiveTool(Exception):
    """The download is in a format no installed tool can open."""


def _source_for(download: Path, platform: Platform | None = None) -> _Source:
    # For MAME, FBNeo and DOSBox the archive IS the ROM: the core opens it and
    # expects its internal layout. Looking inside would pick one chip dump out
    # of a romset and import that, which succeeds and leaves an entry no core
    # can load. Treat it as a plain file.
    if (platform is not None and platform.archive_is_the_rom
            and download.is_file()):
        return _PathSource(download)

    suffix = download.suffix.lower()
    if download.is_file() and suffix in _STDLIB_ARCHIVES:
        return _ZipSource(download)
    if download.is_file() and is_archive_name(download.name):
        tool = bsdtar_path()
        if tool is None:
            raise MissingArchiveTool(
                f"{download.name} is a {suffix} archive and bsdtar is not "
                "installed, so its contents cannot be read. Install "
                "libarchive-tools (Debian/Alpine) or use the official ROMarr "
                "image, which ships it.")
        return _BsdtarSource(download, tool)
    return _PathSource(download)


def list_candidates(download: Path) -> list[str]:
    """Every file a completed download offers, looking inside an archive if needed."""
    return _source_for(download).names()


def verify_set(source, members, dats) -> Match:
    """What a DAT says about the files that are about to be imported.

    Verified means **every** member matched. Redump lists each track of a disc
    as its own `<rom>`, so a cue with a good checksum beside a corrupt track
    is not a good import -- and reporting the set on the strength of its first
    member is how that would be missed.

    Read from the source rather than the destination on purpose: it is the
    same bytes, and doing it here means a refusal can happen before anything
    is written.
    """
    if dats is None:
        return Match(UNKNOWN)
    verdicts = []
    for member in members:
        try:
            hashes = source.hashes(member) if hasattr(source, "hashes") else None
            if hashes is None:
                data = source.read(member)
                if data is None:
                    return Match(UNKNOWN, detail=f"could not read {member!r} to verify")
                hashes = hash_bytes(data, suffix=Path(member).suffix)
        except Exception:
            return Match(UNKNOWN, detail=f"could not read {member!r} to verify")
        verdicts.append(dats.lookup(**hashes))

    if not verdicts:
        return Match(UNKNOWN)
    bad = next((v for v in verdicts if v.status == BAD_DUMP), None)
    if bad is not None:
        return bad
    if all(v.status == VERIFIED for v in verdicts):
        # Every member matched; name the game they all belong to.
        return verdicts[0]
    return Match(UNKNOWN)


#: The two directory layouts RomM understands, and every folder-based
#: frontend after it. Named for what RomM calls them in its own docs so an
#: operator can match this to the setting they already know.
#:
#:   flat  -- <root>/<platform>/<rom>            (RomM "Structure A")
#:   nested -- <root>/<platform>/roms/<rom>      (RomM "Structure B")
#:
#: A translation, when the policy keeps it beside the original, goes one
#: level deeper in a folder RomM treats as a variant rather than a second
#: game. That subfolder is the same in both layouts.
TRANSLATION_SUBDIR = "Translations"


def platform_dir(library_root: Path, platform: "Platform | str", *,
                 layout: str = "flat", translation: bool = False,
                 folder_name: str = "") -> Path:
    """Where a ROM for this platform is filed, under the chosen layout."""
    slug = getattr(platform, "slug", platform)
    name = str(folder_name or slug)
    if (not name or name in (".", "..") or "/" in name or "\\" in name
            or "\x00" in name or name != _canonical_component(name)):
        raise ValueError("platform folder name must be one safe path component")
    base = library_root / name
    if str(layout).lower() in ("nested", "romm_b", "b"):
        base = base / "roms"
    if translation:
        base = base / TRANSLATION_SUBDIR
    return base


_SWITCH_TID = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])")
_SWITCH_MEDIA_DIRS = {"3dboxes", "backcovers", "covers", "miximages", "miximages_v2",
                      "physicalmedia", "screenshots", "marquees", "videos", "manuals"}


def switch_attach_dir(file_name: str, platform_dir: Path) -> Path | None:
    """Where an update or DLC for a game already on disk belongs, if it is there.

    RomM files extra content by sub-folder name inside the game's own folder
    (`update/`, `dlc/`). An update dropped loose in the platform folder shows
    up as a second game, so when the base game's folder exists the file goes
    inside it. Returns None when the file is not an update/DLC or no folder
    holds the base game; the caller then keeps its normal destination.
    """
    from .titled import base_tid_of, classify_tid
    m = _SWITCH_TID.search(file_name)
    if not m:
        return None
    tid = m.group(1)
    kind = classify_tid(tid)
    if kind not in ("update", "dlc"):
        return None
    base = (base_tid_of(tid) or "").upper()
    if not base or not platform_dir.is_dir():
        return None
    try:
        for entry in platform_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith(".") \
                    or entry.name.lower() in _SWITCH_MEDIA_DIRS:
                continue
            for f in entry.rglob("*"):
                if f.is_file() and base in {t.upper() for t in _SWITCH_TID.findall(f.name)
                                             if (base_tid_of(t) or "").upper() == base}:
                    return entry / kind
    except OSError:
        return None
    return None


def _import_nested(source, inner: list[str], download: Path, platform: Platform,
                   library_root: Path, depth: int, kwargs: dict) -> list[ImportResult]:
    """Unpack archives found inside an archive and import what they hold."""
    base = Path(os.environ.get("ROMARR_DATA", "/config/romarr.json")).parent / "unpack-tmp"
    results: list[ImportResult] = []
    work = None
    try:
        base.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="unpack-", dir=str(base)))
        for index, member in enumerate(inner):
            target = work / f"{index}-{Path(member).name}"
            try:
                source.copy(member, target)
            except Exception as exc:  # noqa: BLE001 - one bad inner archive must not hide the rest
                results.append(ImportResult(False, None, f"could not unpack {Path(member).name}: {type(exc).__name__}"))
                continue
            results.extend(import_rom(target, platform, library_root, _depth=depth + 1, **kwargs))
            target.unlink(missing_ok=True)
    except OSError as exc:
        results.append(ImportResult(False, None, f"could not prepare an unpack folder: {type(exc).__name__}"))
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
    return results or [ImportResult(False, None, f"no {platform.name} ROM found inside the nested archives.")]


def import_rom(download: Path, platform: Platform, library_root: Path, *,
               overwrite: bool = False, dats=None,
               require_verified: bool = False,
               layout: str = "flat", translation: bool = False,
               folder_name: str = "",
               rename: bool = False, switch_index=None,
               route_switch_catalog: bool = False,
               switch_updates_dir: str = "Updates",
               switch_dlc_dir: str = "DLC",
               _depth: int = 0) -> list[ImportResult]:
    """Place every ROM from a finished download into the library.

    A cartridge zip may hold several games (a 3-in-1 collection, a bundle)
    and every one is imported.  A disc lands as a directory holding every
    file of the set, which is the layout the live library already uses for
    multi-track rips.

    `layout` picks the directory shape (see `platform_dir`); `translation`
    files the set in the platform's Translations subfolder, for the
    keep-both case where a T-En patch sits beside the original dump.
    """
    if not download.exists():
        msg = (
            f"download path does not exist in this container: {download}. "
            "Mount the download client's completed directory at that exact "
            "path, or add a remote path mapping under Settings -> Media "
            "Management.")
        return [ImportResult(False, None, msg)]

    try:
        source = _source_for(download, platform)
        candidates = source.names()
    except MissingArchiveTool as exc:
        return [ImportResult(False, None, str(exc))]

    chosen_sets = pick_all_rom_sets(candidates, platform, read=source.read)
    if not chosen_sets and _depth < MAX_ARCHIVE_DEPTH and not platform.archive_is_the_rom:
        # Nothing playable at this level, but the download holds archives (a
        # zip around a 7z around the disc). No console reads those, so unpack
        # them here, into a work folder beside ROMarr's data, and import from
        # the result.
        inner = [c for c in candidates if is_archive_name(c)]
        if inner:
            return _import_nested(source, inner, download, platform, library_root, _depth,
                                  dict(overwrite=overwrite, dats=dats,
                                       require_verified=require_verified, layout=layout,
                                       translation=translation, folder_name=folder_name,
                                       rename=rename, switch_index=switch_index,
                                       route_switch_catalog=route_switch_catalog,
                                       switch_updates_dir=switch_updates_dir,
                                       switch_dlc_dir=switch_dlc_dir))
    if not chosen_sets:
        return [ImportResult(
            False, None,
            f"no {platform.name} ROM found; candidate count: {len(candidates)}.")]

    results: list[ImportResult] = []
    for chosen in chosen_sets:
        verdict = verify_set(source, chosen.members, dats)
        if require_verified and verdict.status != VERIFIED:
            results.append(ImportResult(
                False, None,
                f"refused: {verdict.detail or verdict}",
                verification=verdict))
            continue

        target_dir = platform_dir(library_root, platform,
                                   layout=layout, translation=translation,
                                   folder_name=folder_name)

        if platform.slug == "switch":
            attach = switch_attach_dir(Path(chosen.primary).name, target_dir)
            if attach is not None:
                target_dir = attach
        if platform.slug == "switch" and route_switch_catalog and target_dir.name not in ("update", "dlc"):
            # TitleDB classifies an ID read from the filename; it does not
            # verify the package header or contents. This routing stays behind
            # an explicit setting and never changes the reported DAT verdict.
            try:
                from .titled import validate_switch_rom
                switch = validate_switch_rom(
                    Path(chosen.primary).name, index=switch_index)
                title = switch.get("title")
                kind = str(getattr(title, "kind", "") or "")
                subdir = (switch_updates_dir if kind == "update" else
                          switch_dlc_dir if kind == "dlc" else "")
                subdir = str(subdir or "").strip()
                if (switch.get("status") == "verified"
                        and kind in ("update", "dlc") and subdir
                        and _canonical_component(subdir) == subdir
                        and "/" not in subdir and "\\" not in subdir):
                    target_dir = target_dir / subdir
            except Exception as exc:
                log.debug("Switch content routing skipped (%s)", type(exc).__name__)

        if chosen.preserve_paths:
            results.append(_import_directory_set(
                source, chosen, download, target_dir, library_root,
                overwrite=overwrite, verdict=verdict))
            continue

        if not chosen.is_multi_file:
            target_dir.mkdir(parents=True, exist_ok=True)
            original_name = Path(chosen.primary).name
            destination_name = original_name
            if rename and verdict.status == VERIFIED and verdict.game:
                component = _canonical_component(verdict.game)
                if component:
                    destination_name = component + Path(original_name).suffix
            destination = target_dir / destination_name
            if destination_name != original_name and target_dir.is_dir():
                try:
                    collision = next((p for p in target_dir.iterdir()
                                      if p.name.casefold() == destination.name.casefold()
                                      and p.name != original_name), None)
                except OSError:
                    collision = None
                if collision is not None and collision != destination:
                    results.append(ImportResult(
                        False, collision,
                        "canonical DAT name already exists; refusing to overwrite it",
                        verification=verdict))
                    continue
            if destination.exists() and not overwrite:
                results.append(
                    ImportResult(False, destination, "already in the library"))
                continue
            source.copy(chosen.primary, destination)
            log.info("imported %s -> %s", chosen.primary, destination)
            results.append(ImportResult(True, destination,
                                        verification=verdict))
            continue

        # A digital set is named after the download, not its primary: every
        # repack's installer is called setup.exe, and a library of
        # directories all named "setup" is a library of nothing.
        set_name = (download.stem if platform.media == "digital"
                    else _set_name(chosen.primary))
        destination = target_dir / set_name
        if destination.exists() and any(destination.iterdir()) and not overwrite:
            results.append(
                ImportResult(False, destination, "already in the library"))
            continue
        destination.mkdir(parents=True, exist_ok=True)

        written: dict[str, str] = {}
        for member in chosen.members:
            name = Path(member.replace("\\", "/")).name
            if not is_safe_name(name, destination):
                log.warning("refusing set member with an unusable name: %r",
                            member)
                continue
            if name in written:
                results.append(ImportResult(
                    False, destination,
                    f"two files in this download are both called {name!r} "
                    f"({written[name]} and {member}); refusing to guess which "
                    "one the game needs"))
                break
            source.copy(member, destination / name)
            written[name] = member
        else:
            log.info("imported %d files -> %s", len(written), destination)
            results.append(ImportResult(True, destination,
                                        verification=verdict))

    return results


def _import_directory_set(source, chosen, download, target_dir, library_root,
                          *, overwrite, verdict):
    """Publish a whole game tree only after all files have been copied."""
    root_name = Path(chosen.root.rstrip("/\\")).name if chosen.root else ""
    set_name = root_name or (download.name if download.is_dir() else download.stem)
    destination = target_dir / set_name
    if (not is_safe_name(set_name, target_dir)
            or not destination.resolve().is_relative_to(library_root.resolve())
            or destination.is_symlink()):
        return ImportResult(False, None, "unsafe game directory")
    if destination.exists() and not overwrite:
        return ImportResult(False, destination, "already in the library")
    # Preflight the complete set, including collisions on case-insensitive
    # libraries. Do not leave half a game behind on a rejected member.
    members = []
    seen = set()
    for member in chosen.members:
        name = member.replace("\\", "/")[len(chosen.root):]
        if not is_safe_name(name, destination) or name.casefold() in seen:
            return ImportResult(False, destination, "unsafe or duplicate game file")
        seen.add(name.casefold())
        members.append((member, name))
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".romarr-import-", dir=target_dir) as temp:
        stage = Path(temp) / "game"
        stage.mkdir()
        try:
            source.copy_set(members, stage)
            backup = Path(temp) / "previous"
            if destination.exists():
                destination.rename(backup)
            try:
                stage.rename(destination)
            except OSError:
                if backup.exists():
                    backup.rename(destination)
                raise
        except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
            return ImportResult(False, destination, f"game import failed: {exc}")
    return ImportResult(True, destination, verification=verdict)


def _set_name(primary: str) -> str:
    """The directory name a multi-file game gets.

    The primary's stem, because that is the name the sheet carries and the one
    a person recognises. `102 Dalmatians ….gdi` and its five `trackNN.bin`
    files become `102 Dalmatians …/`.
    """
    return Path(primary.replace("\\", "/")).stem


def map_remote_path(path, mappings, client_id=None):
    """Translate a download client's path into one this process can open.

    The client reports paths in ITS filesystem. When it runs in a different
    container the same file has a different path here -- or the volume is not
    mounted at all, which is a mount problem a mapping cannot paper over, and
    the caller finds that out because the translated path still does not exist.

    A mapping with a download-client id applies only to that configured
    client. Client-specific mappings take precedence over shared mappings;
    within either scope the longest matching prefix wins. Entries without an
    id remain shared, preserving existing settings.
    """
    text = str(path)
    best = None
    for entry in mappings or []:
        if not isinstance(entry, dict):
            continue
        mapped_client = str(entry.get("client_id") or "")
        if mapped_client and mapped_client != str(client_id or ""):
            continue
        remote = str(entry.get("remote", "")).rstrip("/\\")
        local = str(entry.get("local", "")).rstrip("/\\")
        if not remote or not local:
            continue
        if text == remote or text.startswith(remote + "/") or text.startswith(remote + "\\"):
            priority = (bool(mapped_client), len(remote))
            if best is None or priority > best[0]:
                best = (priority, remote, local)
    if best is None:
        return _checked(Path(text), text, mapped=False)
    _, remote, local = best
    rest = text[len(remote):].lstrip("/\\")
    return _checked(Path(local) / rest if rest else Path(local), text, mapped=True)


def _checked(result: Path, reported: str, *, mapped: bool) -> Path:
    """Warn, once translation is done, if the result is not openable here.

    This is the only point that knows both paths, and the difference between
    them is the whole diagnosis. Without it the operator sees a download that
    completed and never imported, and nothing that names the container path
    ROMarr actually tried -- which is the one string that makes a wrong volume
    mount obvious.

    A warning rather than a raise: the caller reports the failure per download,
    and one unopenable path must not stop the others importing.
    """
    if not reported or result.exists():
        return result
    if mapped:
        log.warning(
            "download client reported %s, which a remote path mapping turns "
            "into %s -- and that does not exist here. Check the mapping's local "
            "side against what is really mounted.", reported, result)
    else:
        log.warning(
            "download client reported %s, which does not exist here and no "
            "remote path mapping covers it. Mount the client's completed "
            "directory at that exact path, or add a mapping under Settings -> "
            "Media Management.", reported)
    return result
