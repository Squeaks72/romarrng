"""A request must match a release as a whole word, not as a fragment of one."""

from __future__ import annotations

import pytest

from romarr.selection import title_matches


@pytest.mark.parametrize("release,wanted", [
    ("Iconoclasts Update v1 15 NSW-SUXXORS", "Ico"),
    ("Mariokart Wii", "Mario"),
    ("Metroidvania Collection", "Metroid"),
])
def test_a_word_inside_a_longer_word_is_not_a_match(release, wanted):
    assert title_matches(release, wanted) is False


@pytest.mark.parametrize("release,wanted", [
    ("ICO [PS2] [PAL]", "Ico"),
    ("Ico.PS2.NTSC", "Ico"),
    ("Luigis Mansion 3 Multiplayer Pack", "Luigi's Mansion"),
    ("Spiderman 2 PS2", "Spider-Man 2"),
    ("Pacman World", "Pac Man World"),
    ("Super Mario World (USA)", "Super Mario World"),
])
def test_real_spellings_still_match(release, wanted):
    assert title_matches(release, wanted) is True
