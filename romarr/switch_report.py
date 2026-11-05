"""Which Switch games are missing updates or DLC -- switch-library-manager's job.

The library is read from disk, not from RomM: a dump's file name carries its
title ID and version (`Game [01007960049A0800][v131072][Update].nsz`), which is
what TitleDB is keyed by. RomM owns the metadata; this only answers "what is
newer than what I have".

TitleDB's ``versions.json`` knows every update a title has ever had, but only
the DLC that received a version; the full add-on list comes from a region names
file (see titled.py, ``TITLED_NAMES=1``). Without it the report still covers
updates, and says its DLC column is incomplete rather than claiming "no DLC".

Switch 2 titles are mostly absent from TitleDB. Those report ``unknown``, which
is the honest answer, not "current".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .titled import TitleDBIndex, base_tid_of, classify_tid

_TID = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])")
_VER = re.compile(r"\[v(\d+)\]", re.I)
_SKIP = {"3dboxes", "covers", "screenshots", "manuals", "media", "images",
         "soundtrack", "walkthrough"}
_EXT = {".nsp", ".nsz", ".xci", ".xcz", ".nup"}


@dataclass
class Dump:
    tid: str
    kind: str          # base | update | dlc
    version: int
    file: str


@dataclass
class FolderScan:
    """One game as it sits on disk: a folder, or a loose file."""

    name: str
    path: str
    dumps: list[Dump] = field(default_factory=list)


def _dump_for(file: Path) -> Dump | None:
    if file.suffix.lower() not in _EXT:
        return None
    m = _TID.search(file.name)
    if not m:
        return None
    tid = m.group(1).upper()
    kind = classify_tid(tid)
    if kind not in ("base", "update", "dlc"):
        return None
    v = _VER.search(file.name)
    return Dump(tid, kind, int(v.group(1)) if v else 0, file.name)


def scan_folder(root: Path) -> list[FolderScan]:
    """Read every game under a platform folder (e.g. /roms/switch)."""
    out: list[FolderScan] = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith(".") or entry.name.lower() in _SKIP:
            continue
        files = ([p for p in entry.rglob("*") if p.is_file()]
                 if entry.is_dir() else [entry])
        dumps = [d for d in (_dump_for(f) for f in files) if d]
        if dumps:
            name = entry.name if entry.is_dir() else entry.stem
            out.append(FolderScan(name=name, path=str(entry), dumps=dumps))
    return out


def analyse(scan: FolderScan, index: TitleDBIndex | None,
            platform: str = "switch") -> list[dict]:
    """One row per base title found in a folder."""
    groups: dict[str, list[Dump]] = {}
    for d in scan.dumps:
        base = base_tid_of(d.tid) or d.tid
        groups.setdefault(base.upper(), []).append(d)
    rows = []
    for base, dumps in groups.items():
        have_base = [d for d in dumps if d.kind == "base"]
        updates = [d for d in dumps if d.kind == "update"]
        dlcs = {d.tid for d in dumps if d.kind == "dlc"}
        installed = max([d.version for d in updates] + [d.version for d in have_base] + [0])
        row = {"game": scan.name, "path": scan.path, "base_tid": base,
               "base_present": bool(have_base), "installed_version": installed,
               "latest_version": None, "update": "unknown",
               "dlc_installed": len(dlcs), "dlc_total": None, "dlc_missing": [],
               "dlc_complete_list": False, "name": ""}
        # Switch 2 files here are `.nup` upgrade packs. Many carry a Switch 1
        # title ID, so TitleDB's Switch 1 update history would be compared with
        # a different product and report a gap that is not real. No Switch 2
        # version database exists to check against, so say "unknown".
        if index is not None and platform != "switch-2":
            update_tid = base[:-3] + "800"
            ut = index.lookup_by_id(update_tid)
            bt = index.lookup_by_id(base)
            if bt is not None and bt.name:
                row["name"] = bt.name
            if ut is not None and ut.versions:
                latest = ut.latest_version
                row["latest_version"] = latest
                row["update"] = "current" if installed >= latest else (
                    "outdated" if updates or installed else "missing")
            elif bt is not None and bt.versions:
                row["latest_version"] = bt.latest_version or None
                row["update"] = "current" if bt.latest_version <= installed else "outdated"
            fam = index.family_of(base).get("dlc", [])
            if fam:
                total = {t.title_id.upper() for t in fam}
                row["dlc_total"] = len(total | dlcs)
                row["dlc_complete_list"] = bool(index.names_loaded)
                missing = [t for t in fam if t.title_id.upper() not in dlcs]
                row["dlc_missing"] = [{"tid": t.title_id.upper(), "name": t.name}
                                      for t in sorted(missing, key=lambda t: t.title_id)]
            elif index.names_loaded:
                row["dlc_total"] = len(dlcs)
                row["dlc_complete_list"] = True
        rows.append(row)
    return rows


def report(roots: dict[str, Path], index: TitleDBIndex | None) -> dict:
    items = []
    for slug, root in roots.items():
        for scan in scan_folder(root):
            for row in analyse(scan, index, slug):
                row["platform"] = slug
                items.append(row)
    gaps = [i for i in items if i["update"] in ("missing", "outdated") or i["dlc_missing"]]
    return {
        "items": items,
        "summary": {
            "games": len(items),
            "update_gaps": sum(1 for i in items if i["update"] in ("missing", "outdated")),
            "dlc_gaps": sum(len(i["dlc_missing"]) for i in items),
            "games_with_gaps": len(gaps),
            "unknown_to_titledb": sum(1 for i in items if i["update"] == "unknown"),
            "dlc_lists_complete": bool(index and index.names_loaded),
            "titledb_titles": len(index) if index else 0,
        },
    }
