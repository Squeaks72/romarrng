"""Add New, the game page, the Missing tabs and the global search palette."""

from __future__ import annotations

import re

from romarr.ui import NAV, page

SOURCE = page()


def _nav_keys() -> list[str]:
    return [key for _, items in NAV for key, _, _ in items]


def test_interactive_search_is_not_a_separate_nav_entry():
    assert "search" not in _nav_keys()
    assert 'data-page="search"' not in SOURCE
    assert "Interactive Search" not in [label for _, items in NAV for _, label, _ in items]


def test_search_hash_is_an_alias_for_add():
    # go() rewrites #search to #add, and the old renderer forwards to Add New.
    assert "if(page==='search'){ page='add'" in SOURCE
    assert "RENDER.search=async()=>RENDER.add()" in SOURCE


def test_router_takes_arguments_and_keeps_library_lit_for_a_game():
    assert "let ROUTE_ARGS=[]" in SOURCE
    assert "split('/')" in SOURCE
    assert "page==='game'?'library':page" in SOURCE
    assert "addEventListener('hashchange'" in SOURCE
    assert "game:'Game'" in SOURCE


def test_game_page_has_its_pieces_and_the_slots_for_stage_3b():
    for needle in ("RENDER.game=", "Open in RomM", "/api/v1/game/detail",
                   "/api/v1/wanted/monitor", 'id="g-alert"', 'id="g-swu"',
                   'id="g-snd"', 'id="g-rel"', "shelfEditor(", "managed in RomM"):
        assert needle in SOURCE, needle
    assert "async function renderReleases(out,game,platform)" in SOURCE


def test_library_tiles_open_the_game_page_not_the_shelf_editor():
    lib = SOURCE[SOURCE.index("RENDER.library="):SOURCE.index("function bindLibraryChips")]
    assert "data-shelf" not in lib and "shelfEditor" not in lib
    assert "go('game/'+encodeURIComponent(g.platform_slug" in SOURCE


def test_add_dialog_offers_monitor_and_when_added():
    for needle in ("/api/v1/lookup", "/api/v1/wanted/add", 'id="ad-mon"',
                   '<option value="auto">', '<option value="manual">', '<option value="none">',
                   "Add it by exact title", "ADD_PREFILL"):
        assert needle in SOURCE, needle


def test_missing_page_has_monitor_toggle_and_tabs():
    assert "let MISSING_VIEW='all'" in SOURCE
    for tab in ("'all','All'", "'monitored','Monitored'", "'wishlist','Wishlist'"):
        assert tab in SOURCE
    assert "data-mon-game" in SOURCE and "gameHref(w.platform,'',w.game)" in SOURCE


def test_palette_is_wired_to_keys_and_the_top_bar():
    assert "function openPalette()" in SOURCE
    assert "(e.ctrlKey||e.metaKey)" in SOURCE and "e.key==='/'" in SOURCE
    assert 'id="palette-btn"' in SOURCE
    assert "const PALETTE_KEYWORDS" in SOURCE
    # Every keyword key that names a page must be one the nav (or the Switch
    # page that stage 3b adds) can reach.
    keys = re.search(r"const PALETTE_KEYWORDS=\{(.*?)\n\};", SOURCE, re.S).group(1)
    for k in re.findall(r"^\s{2}([a-z]+):'", keys, re.M):
        assert k in _nav_keys() or k == "switchupdates", k
    assert "to add it" in SOURCE  # the fallback that prefills Add New


def test_filter_box_shows_on_games_only():
    assert "$('#search').classList.toggle('hide', page!=='library')" in SOURCE
