"""The global search palette."""

from __future__ import annotations

from romarr import ui


def _src():
    return open(ui.__file__, encoding="utf-8").read()


def test_palette_is_keyboard_reachable_and_in_the_top_bar():
    src = _src()
    assert 'id="palette-btn"' in src
    assert "e.key==='k'" in src and "e.key==='/'" in src
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f"e.key==='{key}'" in src


def test_no_library_match_offers_add_first_and_prefills_add_new():
    src = _src()
    assert "kind:'add'" in src and "[add,...pageHits]" in src
    assert "ADD_PREFILL" in src and "$('#a-q').value=ADD_PREFILL" in src


def test_settings_are_searchable_by_keyword():
    src = _src()
    assert "PALETTE_KEYWORDS" in src and "ntsc" in src
