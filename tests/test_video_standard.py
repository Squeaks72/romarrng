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
