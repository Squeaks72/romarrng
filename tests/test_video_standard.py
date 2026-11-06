"""NTSC / PAL preference: ranks, never surprises."""

from __future__ import annotations

from romarr.profiles import ReleaseProfile, VIDEO_STANDARD_POINTS


def _p(std, strict=False):
    return ReleaseProfile.from_settings({"video_standard": std, "video_standard_strict": strict})


def test_no_preference_changes_nothing():
    p = _p("")
    assert p.adjustments("game (europe) ps2") == []


def test_ntsc_preference_ranks_usa_up_and_europe_down():
    p = _p("ntsc")
    assert p.adjustments("game (usa) ps2")[0][0] == VIDEO_STANDARD_POINTS
    assert p.adjustments("game (europe) ps2")[0][0] == -VIDEO_STANDARD_POINTS
    assert p.adjustments("game ntsc-u")[0][0] == VIDEO_STANDARD_POINTS
    assert p.adjustments("game pal")[0][0] == -VIDEO_STANDARD_POINTS


def test_pal_preference_is_the_mirror_image():
    p = _p("pal")
    assert p.adjustments("game (europe)")[0][0] == VIDEO_STANDARD_POINTS
    assert p.adjustments("game (usa)")[0][0] == -VIDEO_STANDARD_POINTS


def test_a_release_naming_both_or_neither_is_untouched():
    p = _p("ntsc")
    assert p.adjustments("game (usa, europe)") == []
    assert p.adjustments("game ps2 iso") == []


def test_goodtools_codes_count_only_in_brackets():
    p = _p("ntsc")
    assert p.adjustments("game (u) [!]")[0][0] > 0
    assert p.adjustments("among us")  == []   # bare "us" is not a region


def test_strict_refuses_only_the_opposite_standard():
    p = _p("ntsc", strict=True)
    assert "PAL" in p.refusal("game (europe)")
    assert p.refusal("game (usa)") == ""
    assert p.refusal("game (usa, europe)") == ""
    assert p.refusal("game") == ""
    assert _p("ntsc", strict=False).refusal("game (europe)") == ""


def test_garbage_setting_is_ignored():
    assert _p("secam").video_standard == ""


# ---- file formats by console -------------------------------------------------

def _f(**formats):
    return ReleaseProfile.from_settings({"preferred_formats": formats})


def test_first_choice_format_beats_second_for_that_console():
    p = _f(psx=["chd", "iso"])
    chd = p.adjustments("game ps1 chd", "psx")
    iso = p.adjustments("game ps1 iso", "psx")
    assert chd[0][0] == 30 and iso[0][0] == 20


def test_format_preference_only_applies_to_its_console():
    p = _f(psx=["chd"])
    assert p.adjustments("game chd", "wii") == []
    assert p.adjustments("game chd", "") == []


def test_release_naming_no_format_is_not_penalised():
    assert _f(psx=["chd"]).adjustments("game ps1 usa", "psx") == []


def test_extensions_are_normalised_and_junk_dropped():
    p = ReleaseProfile.from_settings({"preferred_formats": {"psx": [".CHD", "chd", "bad format!", "ISO"], "x": "nope"}})
    assert p.formats == {"psx": ["chd", "iso"]}


def test_format_words_are_word_bounded():
    p = _f(psx=["iso"])
    assert p.adjustments("game isometric", "psx") == []


# ---- preferred regions (upstream's own region ladder) --------------------------

def _r(order, mode="prefer"):
    return ReleaseProfile.from_settings({"preferred_regions": order, "region_mode": mode})


def _judge(title, profile):
    from romarr.selection import judge
    from romarr.indexers import Release
    from romarr.platforms import resolve
    rel = Release(title=title, download_url="magnet:?xt=urn:btih:" + "a" * 40, seeders=10,
                  size=600_000_000, protocol="torrent", indexer="x", categories=[1000])
    return judge(rel, "Final Fantasy VII", resolve("psx"), profile=profile)


def test_the_scorer_uses_the_profile_region_order():
    jp = _judge("Final Fantasy VII (Japan) PS1 ISO", _r(["Japan", "USA"]))
    us = _judge("Final Fantasy VII (USA) PS1 ISO", _r(["Japan", "USA"]))
    assert jp.points > us.points


def test_strict_region_mode_refuses_regions_outside_the_list():
    p = _r(["USA"], mode="strict")
    assert _judge("Final Fantasy VII (Europe) PS1 ISO", p).points < 0
    assert _judge("Final Fantasy VII (USA) PS1 ISO", p).points > 0


def test_video_standard_moves_the_score_through_judge():
    base = _judge("Final Fantasy VII (Europe) PS1 ISO", ReleaseProfile.from_settings({}))
    ntsc = _judge("Final Fantasy VII (Europe) PS1 ISO", _p("ntsc"))
    assert ntsc.points == base.points - VIDEO_STANDARD_POINTS
    strict = _judge("Final Fantasy VII (Europe) PS1 ISO", _p("ntsc", strict=True))
    assert strict.points < 0


def test_format_preference_moves_the_score_for_its_console_only():
    p = _f(psx=["chd", "iso"])
    chd = _judge("Final Fantasy VII (USA) PS1 CHD", p)
    iso = _judge("Final Fantasy VII (USA) PS1 ISO", p)
    assert chd.points - iso.points == 10

