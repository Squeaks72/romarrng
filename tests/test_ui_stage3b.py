"""Soundtrack and Switch cards, the two library pages, the queue and the settings pages."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from romarr.ui import JS, NAV, page

SOURCE = page()


def _nav():
    return {key: (label, count) for _, items in NAV for key, label, count in items}


def _block(start: str, end: str) -> str:
    a = SOURCE.index(start)
    return SOURCE[a:SOURCE.index(end, a)]


def test_nav_has_the_switch_and_soundtrack_pages():
    nav = _nav()
    assert nav["switchupdates"] == ("Switch Updates & DLC", "switchgaps")
    assert nav["soundtracks"] == ("Soundtracks", None)
    groups = {name: [k for k, _, _ in items] for name, items in NAV}
    assert "switchupdates" in groups["Library"] and "soundtracks" in groups["Library"]
    # Rendered as real links, one per nav entry, with the badge hook for the count.
    assert "'/api/v1/switch/ignore'" in SOURCE
    assert 'data-page="switchupdates"' in SOURCE and 'data-ct="switchgaps"' in SOURCE
    assert "switchupdates:'Switch Updates & DLC'" in SOURCE and "soundtracks:'Soundtracks'" in SOURCE


def test_game_page_fills_both_cards_and_the_banner():
    assert "if(d.in_library&&d.rom_id) soundtrackCard(d,renderEpoch)" in SOURCE
    assert "switchCard(d,renderEpoch,relBox,relOut)" in SOURCE
    assert "Stage 3b hook" not in SOURCE
    card = _block("function switchCard(", "// ---- Soundtracks:")
    for needle in ("Updates &amp; DLC", "Heads up:", "alert-bar", "/api/v1/switch/updates?game=",
                   "swuPost(", "renderReleases(relOut,b.dataset.q,d.platform)",
                   "Ignore all ${i.dlc_missing.length} missing DLC", "Restore", "swu-find", "swu-ign",
                   "Search for the update", "Installed <b>", "latest known"):
        assert needle in card, needle
    assert "ignored:!b.dataset.restore" in card


def test_soundtrack_card():
    card = _block("function soundtrackCard(", "// Duplicates:")
    for needle in ("/api/v1/soundtracks/game?id=", "/api/v1/soundtracks/search?id=",
                   "/api/v1/soundtracks/download", "/api/v1/soundtracks/undo",
                   "/api/v1/soundtracks/library/search?q=", "/api/v1/soundtracks/library/add",
                   "/api/v1/soundtracks/jobs", "Use an album from your music library",
                   "Search by hand:", "Open ↗", "snd-dl", "Undo (remove"):
        assert needle in card, needle
    # A job is over only once it left "running" AND `finished` is stamped.
    assert "job.state!=='running'&&job.finished" in card
    # 409 held_by: ask, then resend with force.
    assert "g.held_by&&confirm(" in card and "ask(true)" in card and "force" in card


def test_soundtracks_page_has_duplicates_tab():
    page_js = _block("RENDER.soundtracks=", "// ---- The game page")
    for needle in ("Duplicates", "/api/v1/soundtracks/dups'", "/dups/scan", "/dups/merge",
                   "/dups/unmerge", 'type="radio"', "name=\"keep-${gi}\"", "confirm(", "Merged",
                   "/api/v1/soundtracks/jobs", "Undo (restore its copy)"):
        assert needle in page_js, needle


def test_switch_updates_page():
    body = _block("RENDER.switchupdates=", "// The \"Updates & DLC\" card")
    for needle in ("/api/v1/switch/updates", "?refresh=1", "Rescan", "SWU_GAPS", "Installed", "Latest",
                   "dlc_ignored", "Switch 2 titles", "unknown to TitleDB"):
        assert needle in body, needle


def test_library_banner_tile_badges_and_nav_count():
    lib = _block("RENDER.library=", "function bindLibraryChips")
    assert "/api/v1/switch/gaps" in lib and "games_with_gaps" in lib
    assert 'class="alert-bar"' in lib and 'href="#switchupdates"' in lib
    assert '<span class="gap"' in lib
    assert ".tile .gap{" in SOURCE and ".alert-bar{" in SOURCE
    # The nav badge reads counts.switchgaps through the generic data-ct loop in refreshCounts.
    assert "document.querySelectorAll('[data-ct]')" in SOURCE


def test_queue_page_shows_progress_and_refreshes():
    q = _block("const fmtEta=", "RENDER.history=")
    for needle in ("QBIT_STATE", "stalled — no peers", "not in qBittorrent", "class=\"pbar\"", "class=\"pmeta\"",
                   "ETA ${fmtEta(i.eta)}", "fmtSpeed(i.speed)", "id=\"q-refresh\"",
                   "setInterval(", "data-qprog", "gameHref(i.platform"):
        assert needle in q, needle
    assert ".pbar{" in SOURCE and ".pmeta{" in SOURCE


def test_profiles_page_has_video_standard_and_formats_editor():
    prof = _block("RENDER.profiles=", "RENDER.clients=")
    for needle in ("prof-video-std", "prof-video-strict", "File formats by console", "format-prefs",
                   "pickerHtml('fmt-add'", "bindPicker($('#page'),'fmt-add'", "patch.preferred_formats=out",
                   "patch.video_standard=vStd", "video_standard_strict:vStrict", "data-fmt-del"):
        assert needle in prof, needle
    # Region names are saved lower case (see docs/port/DECISIONS.md).
    assert "s.trim().toLowerCase()" in prof
    assert "['usa','world','europe','japan']" in prof


def test_general_media_and_hub_additions():
    gen = _block("RENDER.general=", "\nRENDER.")
    assert 'data-k="romm_public_url"' in gen and "RomM address for links" in gen
    assert "<b>Unpacking.</b>" in SOURCE and "ZIPs nested inside a ZIP" in SOURCE
    assert "hs.isolation==='uid'" in SOURCE and "This host has no Landlock" in SOURCE


def test_settings_never_display_or_resend_masked_secrets():
    assert "const SECRET_MASK='********'" in SOURCE
    sp = _block("function settingsPage(", "const fld=")
    assert "el.value===''||el.value===SECRET_MASK" in sp and "return;" in sp
    fld = _block("const fld=", "const chk=")
    assert "val===SECRET_MASK" in fld and "value=\"${secret?'':esc(val)}\"" in fld


def test_no_translation_machinery_was_added():
    for banned in ("interfaceMarkup", "interfaceTemplateMarkup", "statusMarkup", "appMessageMarkup",
                   "translateLabel", "data-i18n", "toastAppMessage", "regionalDate"):
        assert banned not in SOURCE, banned


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_generated_javascript_parses(tmp_path):
    f = tmp_path / "ui.js"
    f.write_text(JS)
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
