"""NTSC / PAL preference: ranks, never surprises."""

from __future__ import annotations

from romarr.profiles import ReleaseProfile, VIDEO_STANDARD_POINTS


def _p(std, strict=False):
    return ReleaseProfile.from_settings({"video_standard": std, "video_standard_strict": strict})


def test_no_preference_changes_nothing():
    p = _p("")
    assert not p and p.adjustments("game (europe) ps2") == []


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


# ---- preferred regions drive scoring -------------------------------------------

def _r(order, mode=""):
    return ReleaseProfile.from_settings({"preferred_regions": order, "region_mode": mode})


def test_default_region_list_is_the_old_ladder():
    p = _r(["USA", "World", "Europe", "Japan"])
    assert p.region_points("game (usa)")[0] == 40
    assert p.region_points("game (europe)")[0] == 20
    assert p.region_points("game (japan)")[0] == 10


def test_a_custom_order_changes_the_ranking():
    p = _r(["Japan", "USA"])
    assert p.region_points("game (japan)")[0] == 40
    assert p.region_points("game (usa)")[0] == 30
    assert p.region_points("game (europe)")[0] == 0


def test_combined_codes_count_for_their_best_listed_region():
    p = _r(["Europe", "USA"])
    assert p.region_points("game (ue)")[0] == 40   # Europe is first on this list


def test_strict_mode_refuses_regions_outside_the_list_only():
    p = _r(["USA"], mode="strict")
    assert "not in your preferred regions" in p.refusal("game (europe)")
    assert p.refusal("game (usa, europe)") == ""
    assert p.refusal("game") == ""
    assert _r(["USA"]).refusal("game (europe)") == ""


def test_the_scorer_uses_the_profile_region_order():
    from romarr.selection import judge
    from romarr.indexers import Release
    from romarr.platforms import resolve

    def rel(t):
        return Release(title=t, download_url="magnet:?xt=urn:btih:" + "a" * 40, seeders=10,
                       size=600_000_000, protocol="torrent", indexer="x", categories=[1000])
    plat = resolve("psx")
    jp = judge(rel("Final Fantasy VII (Japan) PS1 ISO"), "Final Fantasy VII", plat,
               profile=_r(["Japan", "USA"]))
    us = judge(rel("Final Fantasy VII (USA) PS1 ISO"), "Final Fantasy VII", plat,
               profile=_r(["Japan", "USA"]))
    assert jp.points > us.points
