"""Operator policy over the scorer.

Two things every *arr has and ROMarr did not: a way to say "prefer this, never
that", and a way to say "never offer me this exact release again".

Both exist elsewhere as flat lists -- a set of words, a set of ids. The
difference here is that ROMarr's scorer already explains itself release by
release, so both of these can be *visible*:

  * a preferred term appears in `Judgement.why()` with the points it added, so
    an operator can see their own policy working rather than infer it from a
    changed outcome;
  * a blocklist entry carries the reason it was blocked and when, so "why will
    it never take this one" has an answer that is not "look in the logs".

"Why did it take that one" and "why will it never take this one" are the two
questions anybody actually asks about an *arr, and a flat list answers
neither.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: A term wrapped in slashes is a regular expression, the way Radarr's release
#: profiles work. The cases that need one are real: `(Rev 1)` but not
#: `(Rev 10)` cannot be expressed as a substring.
_REGEX_TERM = re.compile(r"^/(.*)/$", re.DOTALL)


def _matches(term: str, haystack: str) -> bool:
    """Whether `term` -- literal or `/regex/` -- appears in `haystack`."""
    term = str(term or "")
    if not term:
        return False
    pattern = _REGEX_TERM.match(term)
    if pattern:
        try:
            return re.search(pattern.group(1), haystack, re.IGNORECASE) is not None
        except re.error as exc:
            # A bad pattern is an operator typo, and taking every search down
            # with it would turn a one-character mistake into a dead install.
            log.warning("ignoring unparseable release-profile term %r: %s",
                        term, exc)
            return False
    return term.lower() in haystack


#: How much a matching / opposing video standard moves a release. Larger than
#: the gap between USA and Europe on the built-in region ladder (20), so a stated
#: preference wins over it, but far below a verified dump (50) plus availability.
VIDEO_STANDARD_POINTS = 30

#: NTSC: North America and Japan. PAL: Europe and Australasia. Word-bounded so
#: "usa" never matches inside another word; the single letters are the
#: GoodTools codes, which only count inside brackets.
_NTSC_MARKERS = re.compile(
    r"(?<![a-z0-9])(?:ntsc(?:[- ]?[ujm])?|usa|japan)(?![a-z0-9])"
    r"|[(\[](?:u|j|ju|uj)[)\]]")
_PAL_MARKERS = re.compile(
    r"(?<![a-z0-9])(?:pal(?:[- ]?[a-z])?|europe|australia|germany|france|spain|italy"
    r"|netherlands|sweden)(?![a-z0-9])"
    r"|[(\[](?:e|eu|eur)[)\]]")


#: Format preference weights: your first choice is worth the most, each step
#: down is worth less, never below half a step.
FORMAT_FIRST_POINTS = 30
FORMAT_STEP_POINTS = 10


def _clean_formats(raw) -> dict[str, list[str]]:
    """{platform: [ext, ...]} from stored settings, tolerating any shape."""
    out: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return out
    for slug, exts in raw.items():
        if not isinstance(exts, (list, tuple)):
            continue
        seen: list[str] = []
        for e in exts:
            word = str(e or "").strip().lower().lstrip(".")
            if re.fullmatch(r"[a-z0-9]{1,8}", word) and word not in seen:
                seen.append(word)
        if seen:
            out[str(slug)] = seen
    return out


DEFAULT_REGIONS = ["usa", "world", "europe", "japan"]
REGION_FIRST_POINTS = 40
REGION_STEP_POINTS = 10

#: canonical region -> other spellings that name it in a release title.
_REGION_WORDS = {
    "usa": ("ntsc-u", "united states", "north america"),
    "world": ("global",),
    "europe": ("pal", "eur"),
    "japan": ("ntsc-j", "jpn"),
    "australia": (), "germany": (), "france": (), "spain": (), "italy": (),
    "korea": (), "brazil": (), "canada": (), "asia": (), "china": (),
    "netherlands": (), "sweden": (), "taiwan": (), "russia": (),
}
#: GoodTools / No-Intro compact codes; a combined code names every region in it.
_REGION_LETTERS = {"u": "usa", "e": "europe", "j": "japan", "w": "world"}
_CODE_WORDS = {"us": "usa", "eu": "europe", "jp": "japan"}
_REGION_ALIAS = {
    "us": "usa", "u": "usa", "ntsc-u": "usa", "north america": "usa", "united states": "usa",
    "global": "world", "w": "world",
    "eu": "europe", "eur": "europe", "pal": "europe", "e": "europe",
    "jp": "japan", "jpn": "japan", "ntsc-j": "japan", "j": "japan",
}


def _clean_regions(raw) -> list[str]:
    """Canonical region names from "USA, World, Europe", best first."""
    if raw is None:
        return list(DEFAULT_REGIONS)
    items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    out: list[str] = []
    for item in items:
        name = str(item or "").strip().lower()
        if not name:
            continue
        name = _REGION_ALIAS.get(name, name)
        if name not in out:
            out.append(name)
    return out


@dataclass
class ReleaseProfile:
    """Preferred, excluded and required terms.

    `preferred` carries its own weight per term rather than a single global
    bonus, because "I mildly like this" and "I will take nothing else" are
    different instructions and one number cannot express both.
    """

    #: (term, points). Negative is a penalty, which is how "avoid but do not
    #: refuse" is written.
    preferred: list[tuple[str, int]] = field(default_factory=list)
    #: Any match refuses the release outright.
    excluded: list[str] = field(default_factory=list)
    #: Every term must appear, or the release is refused.
    required: list[str] = field(default_factory=list)
    #: "ntsc", "pal" or "" (no preference). North America and Japan are NTSC;
    #: Europe and Australia are PAL. Ranking only, unless `video_strict`.
    video_standard: str = ""
    #: Refuse a release that names only the other standard, instead of just
    #: ranking it lower. A release naming both (USA, Europe) or neither is kept.
    video_strict: bool = False
    #: Per console, formats in order of preference ("chd" before "iso"), as
    #: file-extension words. Ranking only: a release naming none of them is not
    #: penalised, because most release titles do not name a format at all.
    formats: dict[str, list[str]] = field(default_factory=dict)
    #: "Preferred regions, best first" as canonical region names. The first is
    #: worth 40 points, then 30, 20, 10 (never below 5). Replaces the built-in
    #: ladder, which is the same order, so the default changes nothing.
    regions: list[str] = field(default_factory=lambda: list(DEFAULT_REGIONS))
    #: With region_mode "strict": refuse a release that names regions, none of
    #: which you listed. A release naming no region is kept either way.
    region_strict: bool = False

    @classmethod
    def from_settings(cls, settings: dict) -> "ReleaseProfile":
        """Build from stored settings, tolerating whatever shape they are in.

        Preferred terms are stored as a list of `{term, score}` because a UI
        edits them as rows, and a tuple in JSON comes back as a list.
        """
        preferred = []
        for entry in settings.get("preferred_terms") or []:
            if isinstance(entry, dict):
                term = str(entry.get("term") or "")
                try:
                    points = int(entry.get("score") or 0)
                except (TypeError, ValueError):
                    points = 0
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                term, points = str(entry[0]), int(entry[1] or 0)
            else:
                term, points = str(entry), 25
            if term:
                preferred.append((term, points))
        standard = str(settings.get("video_standard") or "").strip().lower()
        return cls(
            preferred=preferred,
            excluded=[str(t) for t in (settings.get("excluded_terms") or []) if t],
            required=[str(t) for t in (settings.get("required_terms") or []) if t],
            video_standard=standard if standard in ("ntsc", "pal") else "",
            video_strict=bool(settings.get("video_standard_strict")),
            formats=_clean_formats(settings.get("preferred_formats")),
            regions=_clean_regions(settings.get("preferred_regions")),
            region_strict=str(settings.get("region_mode") or "") == "strict",
        )

    def _video(self, lowered: str) -> bool | None:
        """Whether a release matches the preferred video standard.

        True / False when it names exactly one standard, None when it names
        both or neither -- a (USA, Europe) dump runs on either console, and a
        title with no region tells us nothing.
        """
        if not self.video_standard:
            return None
        ntsc = bool(_NTSC_MARKERS.search(lowered))
        pal = bool(_PAL_MARKERS.search(lowered))
        if ntsc == pal:
            return None
        return ntsc if self.video_standard == "ntsc" else pal

    def refusal(self, lowered: str) -> str:
        """Why this release is refused outright, or "" if it is not."""
        if self.region_strict and self.regions:
            named = self._named_regions(lowered)
            if named and not (named & set(self.regions)):
                return ("region " + "/".join(sorted(named))
                        + " is not in your preferred regions")
        if self.video_strict and self._video(lowered) is False:
            other = "PAL" if self.video_standard == "ntsc" else "NTSC"
            return (f"{other} release refused: you require "
                    f"{self.video_standard.upper()}")
        for term in self.excluded:
            if _matches(term, lowered):
                return f"excluded by release profile ({term!r})"
        for term in self.required:
            if not _matches(term, lowered):
                return f"missing a required term ({term!r})"
        return ""

    def _named_regions(self, lowered: str) -> set[str]:
        named: set[str] = set()
        for region, words in _REGION_WORDS.items():
            if any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", lowered)
                   for w in (region,) + words):
                named.add(region)
        for code in re.findall(r"[(\[]([a-z]{1,3})[)\]]", lowered):
            if code in _CODE_WORDS:
                named.add(_CODE_WORDS[code])
            elif set(code) <= set(_REGION_LETTERS):
                named.update(_REGION_LETTERS[c] for c in code)
        return named

    def region_points(self, lowered: str) -> tuple[int, str] | None:
        """Points for the release's best-ranked region on YOUR list, or None."""
        if not self.regions:
            return None
        named = self._named_regions(lowered)
        ranks = [self.regions.index(r) for r in named if r in self.regions]
        if not ranks:
            return (0, "")
        rank = min(ranks)
        return (max(REGION_FIRST_POINTS - rank * REGION_STEP_POINTS, 5), self.regions[rank])

    def _format_points(self, lowered: str, platform_slug: str) -> tuple[int, str] | None:
        """Points for the best-ranked preferred format the release names."""
        order = self.formats.get(platform_slug or "")
        if not order:
            return None
        for rank, ext in enumerate(order):
            if re.search(r"(?<![a-z0-9])" + re.escape(ext) + r"(?![a-z0-9])", lowered):
                return (max(FORMAT_FIRST_POINTS - rank * FORMAT_STEP_POINTS, FORMAT_STEP_POINTS // 2),
                        f"format: {ext.upper()} is your #{rank + 1} for this console")
        return None

    def adjustments(self, lowered: str, platform_slug: str = "") -> list[tuple[int, str]]:
        """Point changes this profile makes, ready for `Judgement.reasons`."""
        out = []
        for term, points in self.preferred:
            if points and _matches(term, lowered):
                out.append((points, f"release profile prefers {term!r}"))
        fmt = self._format_points(lowered, platform_slug)
        if fmt:
            out.append(fmt)
        match = self._video(lowered)
        if match is not None:
            std = self.video_standard.upper()
            out.append((VIDEO_STANDARD_POINTS if match else -VIDEO_STANDARD_POINTS,
                        f"video standard: {'is' if match else 'is not'} {std}"))
        return out

    def __bool__(self) -> bool:
        return bool(self.preferred or self.excluded or self.required
                    or self.video_standard or self.formats or self.region_strict
                    or self.regions != DEFAULT_REGIONS)


_INFOHASH = re.compile(r"btih:([0-9a-fA-F]{40}|[0-9a-zA-Z]{32})")


def normalise_infohash(value: str) -> str:
    """Canonicalize hex and base32 v1 torrent hashes, including old queue rows."""
    import base64
    value = str(value or "").strip().lower()
    if len(value) == 32:
        try:
            return base64.b32decode(value.upper()).hex()
        except ValueError:
            pass
    return value


def release_id(release) -> str:
    """A stable identity for one release.

    The infohash when there is one, because indexers rewrite titles freely and
    two results for the same torrent have to block as one. Otherwise the
    indexer, title and size together -- enough that a re-run of the same search
    recognises the same entry, and specific enough that a different dump of the
    same game is not caught by mistake.
    """
    found = _INFOHASH.search(str(getattr(release, "download_url", "") or ""))
    if found:
        return f"btih:{normalise_infohash(found.group(1))}"
    return (f"{getattr(release, 'indexer', '')}|"
            f"{getattr(release, 'title', '')}|"
            f"{getattr(release, 'size', 0)}").lower()


class Blocklist:
    """Releases that must never be taken again, and why."""

    def __init__(self):
        self._entries: dict[str, dict] = {}

    def add(self, release, reason: str = "") -> dict:
        return self.add_entry(
            release_id(release),
            title=getattr(release, "title", ""),
            indexer=getattr(release, "indexer", ""),
            size=getattr(release, "size", 0),
            reason=reason)

    def add_entry(self, entry_id: str, *, title: str = "", indexer: str = "",
                  size: int = 0, reason: str = "") -> dict:
        """Block an identity rather than a release object.

        A dead download is retired long after the `Release` that started it
        has been forgotten -- all that survives is the queue row. The row
        carries the id `release_id` computed at grab time, so blocking by id
        matches exactly the same thing a later search will compute, which
        recomputing from a reconstructed object would not: an id taken from
        an infohash cannot be rebuilt out of a title and a size.
        """
        entry = {
            "id": str(entry_id),
            "title": title,
            "indexer": indexer,
            "size": size,
            "reason": reason or "blocked by the operator",
            "blocked_at": int(time.time()),
        }
        self._entries[entry["id"]] = entry
        return entry

    def remove(self, entry_id: str) -> bool:
        return self._entries.pop(str(entry_id), None) is not None

    def reason_for(self, release) -> str:
        entry = self._entries.get(release_id(release))
        return entry["reason"] if entry else ""

    def __contains__(self, release) -> bool:
        return release_id(release) in self._entries

    def as_items(self) -> list[dict]:
        return sorted(self._entries.values(),
                      key=lambda e: -e.get("blocked_at", 0))

    @classmethod
    def from_items(cls, items) -> "Blocklist":
        out = cls()
        for item in items or []:
            if isinstance(item, dict) and item.get("id"):
                out._entries[str(item["id"])] = dict(item)
        return out

    def __len__(self) -> int:
        return len(self._entries)
