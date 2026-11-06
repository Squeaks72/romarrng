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
from typing import Any

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


def _mentions(haystack: str, marker: str) -> bool:
    """Whether `marker` appears in `haystack` as a whole word or phrase."""
    padded = f" {re.sub(r'[^a-z0-9 ]+', ' ', haystack)} "
    return f" {marker} " in re.sub(r"\s+", " ", padded)


#: Canonical region markers: (substring markers, compact codes)
_REGION_MARKERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "usa": (("usa", "(u)", "[u]", "ntsc-u", "united states", "america"),
            ("u", "us", "ue", "uj", "ju", "jue", "uej", "jeu")),
    "world": (("world", "(w)", "global"), ("w",)),
    "europe": (("europe", "(e)", "pal"), ("e", "eu", "eur", "ue", "uej", "jeu", "jue")),
    "japan": (("japan", "(j)", "ntsc-j"), ("j", "jp", "jpn", "ju", "uj", "jue", "uej", "jeu")),
    "australia": (("australia", "(a)", "aus"), ("a", "au")),
    "germany": (("germany", "(g)", "german", "deu"), ("de",)),
    "france": (("france", "(f)", "french", "fra"), ("fr",)),
    "spain": (("spain", "(s)", "spanish", "esp"), ("es",)),
    "italy": (("italy", "(i)", "italian", "ita"), ("it",)),
    "china": (("china", "chinese", "chs", "cht"), ("cn", "zh")),
    "korea": (("korea", "korean", "kor"), ("kr", "ko")),
    "brazil": (("brazil", "portuguese", "pt-br", "ptbr"), ("br", "pt")),
}


def _region_matches(region_key: str, lowered: str) -> bool:
    """Whether `region_key` matches in `lowered` release title."""
    rk = region_key.lower().strip()
    if rk in _REGION_MARKERS:
        substrings, codes = _REGION_MARKERS[rk]
        if any(s in lowered for s in substrings):
            return True
        if any(_mentions(lowered, c) for c in codes):
            return True
    else:
        if rk in lowered or _mentions(lowered, rk):
            return True
        if f"({rk})" in lowered or f"[{rk}]" in lowered:
            return True
    return False


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


@dataclass
class ReleaseProfile:
    """Preferred, excluded and required terms, sizing limits, and scoring preferences.

    `preferred` carries its own weight per term rather than a single global
    bonus, because "I mildly like this" and "I will take nothing else" are
    different instructions and one number cannot express both.

    Sizing, region preferences, and scoring can also be customized globally
    or on a per-platform basis.
    """

    #: (term, points). Negative is a penalty, which is how "avoid but do not
    #: refuse" is written.
    preferred: list[tuple[str, int]] = field(default_factory=list)
    #: Any match refuses the release outright.
    excluded: list[str] = field(default_factory=list)
    #: Every term must appear, or the release is refused.
    required: list[str] = field(default_factory=list)
    #: Minimum release size in megabytes; 0 or None disables the floor check.
    min_size_mb: float | None = None
    #: Maximum release size in megabytes; 0 or None uses system/medium ceiling.
    max_size_mb: float | None = None
    #: Minimum seeders required on torrents (None or <=1 means normal check).
    min_seeders: int | None = None
    #: Preferred regions in ranking order.
    preferred_regions: list[str] = field(default_factory=list)
    #: Custom scores per region: {"japan": 100, "usa": 40, "europe": 20}.
    region_scores: dict[str, int] = field(default_factory=dict)
    #: Size preference tie-breaker: "auto" | "smaller" | "larger" | "none".
    size_preference: str = "auto"
    #: Optional bonus points awarded for matching size preference (0 to disable).
    size_weight: int = 0
    #: Region mode: "prefer" | "strict"
    region_mode: str = "prefer"
    #: Fan translation policy: "exclude" | "prefer" | "fill" | "keep_both"
    translation_policy: str = "exclude"
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
    _settings_ref: dict | None = None

    @property
    def min_size_bytes(self) -> int:
        if self.min_size_mb is not None and self.min_size_mb > 0:
            return int(self.min_size_mb * 1024 * 1024)
        return 0

    @property
    def max_size_bytes(self) -> int:
        if self.max_size_mb is not None and self.max_size_mb > 0:
            return int(self.max_size_mb * 1024 * 1024)
        return 0

    @classmethod
    def from_settings(cls, settings: dict, platform: Any = None) -> "ReleaseProfile":
        """Build from stored settings, tolerating whatever shape they are in.

        If `platform` is provided, platform-specific overrides from
        `platform_profiles` in `settings` are merged over global defaults.
        """
        platform_cfg = {}
        if platform:
            slug = getattr(platform, "slug", str(platform)).lower().strip()
            platform_profiles = settings.get("platform_profiles") or {}
            if isinstance(platform_profiles, dict):
                platform_cfg = platform_profiles.get(slug) or {}

        # Preferred terms: platform terms merged with global terms
        preferred = []
        raw_preferred = list(platform_cfg.get("preferred_terms") or []) + list(settings.get("preferred_terms") or [])
        seen_terms = set()
        for entry in raw_preferred:
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
            if term and term not in seen_terms:
                seen_terms.add(term)
                preferred.append((term, points))

        # Excluded terms
        excluded = [str(t) for t in (platform_cfg.get("excluded_terms") or []) if t]
        for t in (settings.get("excluded_terms") or []):
            if t and str(t) not in excluded:
                excluded.append(str(t))

        # Required terms
        required = [str(t) for t in (platform_cfg.get("required_terms") or []) if t]
        for t in (settings.get("required_terms") or []):
            if t and str(t) not in required:
                required.append(str(t))

        def _to_float(v, default=None):
            if v is None or v == "":
                return default
            try:
                num = float(v)
                return num if num > 0 else default
            except (ValueError, TypeError):
                return default

        min_size = _to_float(platform_cfg.get("min_size_mb"),
                             _to_float(settings.get("min_size_mb")))
        max_size = _to_float(platform_cfg.get("max_size_mb"),
                             _to_float(settings.get("max_size_mb")))

        min_seeders = platform_cfg.get("min_seeders")
        if min_seeders is None or min_seeders == "":
            min_seeders = settings.get("min_seeders")
        try:
            min_seeders = int(min_seeders) if min_seeders is not None else None
        except (ValueError, TypeError):
            min_seeders = None

        preferred_regions = platform_cfg.get("preferred_regions")
        if not preferred_regions:
            preferred_regions = settings.get("preferred_regions") or []
        preferred_regions = [str(r).strip() for r in preferred_regions if str(r).strip()]

        raw_region_scores = platform_cfg.get("region_scores")
        if not raw_region_scores:
            raw_region_scores = settings.get("region_scores") or {}
        region_scores: dict[str, int] = {}
        if isinstance(raw_region_scores, dict):
            for k, v in raw_region_scores.items():
                try:
                    region_scores[str(k).lower().strip()] = int(v)
                except (ValueError, TypeError):
                    pass
        elif isinstance(raw_region_scores, (list, tuple)):
            for entry in raw_region_scores:
                if isinstance(entry, dict):
                    reg = str(entry.get("region") or entry.get("term") or "").lower().strip()
                    try:
                        sc = int(entry.get("score") or 0)
                        if reg:
                            region_scores[reg] = sc
                    except (ValueError, TypeError):
                        pass
                elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                    try:
                        region_scores[str(entry[0]).lower().strip()] = int(entry[1])
                    except (ValueError, TypeError):
                        pass

        size_preference = str(platform_cfg.get("size_preference") or settings.get("size_preference") or "auto").strip().lower()
        if size_preference not in ("auto", "smaller", "larger", "none"):
            size_preference = "auto"

        size_weight = platform_cfg.get("size_weight")
        if size_weight is None:
            size_weight = settings.get("size_weight", 0)
        try:
            size_weight = int(size_weight or 0)
        except (ValueError, TypeError):
            size_weight = 0

        region_mode = str(platform_cfg.get("region_mode") or settings.get("region_mode") or "prefer").strip().lower()
        translation_policy = str(platform_cfg.get("translation_policy") or settings.get("translation_policy") or "exclude").strip().lower()

        standard = str(platform_cfg.get("video_standard")
                       or settings.get("video_standard") or "").strip().lower()
        strict_raw = platform_cfg.get("video_standard_strict")
        if strict_raw is None:
            strict_raw = settings.get("video_standard_strict")

        return cls(
            video_standard=standard if standard in ("ntsc", "pal") else "",
            video_strict=bool(strict_raw),
            formats=_clean_formats(settings.get("preferred_formats")),
            preferred=preferred,
            excluded=excluded,
            required=required,
            min_size_mb=min_size,
            max_size_mb=max_size,
            min_seeders=min_seeders,
            preferred_regions=preferred_regions,
            region_scores=region_scores,
            size_preference=size_preference,
            size_weight=size_weight,
            region_mode=region_mode,
            translation_policy=translation_policy,
            _settings_ref=settings,
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

    def _format_points(self, lowered: str, platform_slug: str) -> tuple[int, str] | None:
        """Points for the best-ranked preferred format the release names."""
        order = self.formats.get(platform_slug or "")
        if not order:
            return None
        for rank, ext in enumerate(order):
            if re.search(r"(?<![a-z0-9])" + re.escape(ext) + r"(?![a-z0-9])", lowered):
                return (max(FORMAT_FIRST_POINTS - rank * FORMAT_STEP_POINTS,
                            FORMAT_STEP_POINTS // 2),
                        f"format: {ext.upper()} is your #{rank + 1} for this console")
        return None

    def refusal(self, lowered: str, size: int = 0) -> str:
        """Why this release is refused outright, or "" if it is not."""
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
        if self.min_size_bytes and 0 < size < self.min_size_bytes:
            return f"smaller than release profile minimum size ({self.min_size_mb}MB)"
        if self.max_size_bytes and size > self.max_size_bytes:
            return f"larger than release profile maximum size ({self.max_size_mb}MB)"
        return ""

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

    def region_score_for(self, lowered: str) -> tuple[int, str] | None:
        """Custom points and label for region, or None to fall back to default ladder."""
        if self.region_scores:
            matches: list[tuple[int, str]] = []
            for region_name, points in self.region_scores.items():
                if _region_matches(region_name, lowered):
                    matches.append((points, region_name))
            if matches:
                # Take highest points match if multiple regions matched
                matches.sort(key=lambda x: -x[0])
                pts, name = matches[0]
                return (pts, f"region {name}")
        elif self.preferred_regions:
            for idx, region_name in enumerate(self.preferred_regions):
                if _region_matches(region_name, lowered):
                    pts = max(10, 40 - (idx * 10))
                    return (pts, f"region {region_name.lower()}")
        return None

    def size_score_for(self, size: int, ceiling: int) -> tuple[int, str] | None:
        """Points adjustment based on size preference."""
        if not self.size_weight or size <= 0 or ceiling <= 0:
            return None
        pref = (self.size_preference or "auto").lower()
        if pref == "smaller":
            fraction = max(0.0, min(1.0, 1.0 - (size / ceiling)))
            pts = int(round(self.size_weight * fraction))
            return (pts, f"size preference (smaller is preferred: {pts:+d} pts)")
        elif pref == "larger":
            fraction = max(0.0, min(1.0, size / ceiling))
            pts = int(round(self.size_weight * fraction))
            return (pts, f"size preference (larger is preferred: {pts:+d} pts)")
        return None

    def __bool__(self) -> bool:
        return True


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
        return f"btih:{found.group(1).lower()}"
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
