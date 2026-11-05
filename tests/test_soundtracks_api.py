"""The soundtrack HTTP API end to end: a live ROMarr, a loopback RomM, patched source fetches."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from romarr import soundtracks as st
from romarr.app import ROMarr, make_handler
from romarr.libraries import Game
from soundtracks_support import (ARCHIVE_META, ARCHIVE_SEARCH, PASSWORD, TOKEN, ZOPHAR_PAGE,
                                 ZOPHAR_SEARCH, FakeRomm, make_zip)

KEY = "api-key-for-tests"


@pytest.fixture
def env(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    romm = FakeRomm()
    # The background library refresh would race the library injected below.
    monkeypatch.setattr(ROMarr, "_refresh_counts", lambda self: None)
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json"), "ROMARR_API_KEY": KEY,
                      "ROMM_URL": romm.url, "ROMM_USERNAME": "tim", "ROMM_PASSWORD": PASSWORD})
    service._library_cache = ([Game(id="42", name="Chrono Trigger", platform="Super Nintendo", platform_slug="snes"),
                               Game(id="77", name="Some Other Thing", platform="Switch", platform_slug="switch")],
                              time.monotonic(), "")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    blob = make_zip({"disc/01 Opening.mp3": b"aaa", "disc/02 Town.mp3": b"bbb", "cover.jpg": b"x"})

    def fetch(url, binary=False, gap=1.0):
        if "zophar.net/music/search" in url:
            return ZOPHAR_SEARCH
        if "zophar.net/music/snes-spc/chrono-trigger" in url:
            return ZOPHAR_PAGE
        if "advancedsearch" in url:
            return ARCHIVE_SEARCH
        if "archive.org/metadata" in url:
            return ARCHIVE_META
        raise AssertionError(url)
    monkeypatch.setattr(st, "polite_get", fetch)
    monkeypatch.setattr(st, "stream", lambda url, on_total=None: iter([blob]))
    yield f"http://127.0.0.1:{httpd.server_address[1]}", service, romm, caplog
    httpd.shutdown()
    httpd.server_close()
    romm.close()


def call(base, path, body=None, key=KEY):
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    if key:
        req.add_header("X-Api-Key", key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def wait_done(base, gid="42"):
    for _ in range(200):
        _, raw = call(base, f"/api/v1/soundtracks/game?id={gid}")
        job = json.loads(raw).get("job")
        if job and job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_every_soundtrack_route_needs_the_api_key(env):
    base, *_ = env
    for path in ("/api/v1/soundtracks/game?id=42", "/api/v1/soundtracks/search?id=42", "/api/v1/soundtracks/jobs"):
        assert call(base, path, key=None)[0] == 401
    assert call(base, "/api/v1/soundtracks/download", {"id": "42"}, key=None)[0] == 401
    assert call(base, "/api/v1/soundtracks/undo", {"id": "42"}, key=None)[0] == 401


def test_status_search_download_and_undo_round_trip(env):
    base, service, romm, caplog = env
    code, raw = call(base, "/api/v1/soundtracks/game?id=42")
    status = json.loads(raw)
    assert code == 200 and status["track_count"] == 1 and status["undoable"] == 0

    code, raw = call(base, "/api/v1/soundtracks/search?id=42")
    found = json.loads(raw)
    assert code == 200 and found["candidates"][0]["id"] == "/music/snes-spc/chrono-trigger"
    assert found["candidates"][0]["formats"] == ["mp3", "original"] and len(found["links"]) == 7

    code, raw = call(base, "/api/v1/soundtracks/download",
                     {"id": "42", "candidate": {"provider": "zophar", "id": "/music/snes-spc/chrono-trigger"}, "format": "mp3"})
    assert code == 200 and json.loads(raw)["state"] == "running"
    job = wait_done(base)
    assert job["state"] == "done" and job["made"] == 2
    assert sorted(romm.tracks[42].values()) == ["01 Opening.mp3", "02 Town.mp3", "Mine Already.mp3"]
    items = json.loads(call(base, "/api/v1/soundtracks/jobs")[1])["items"]
    assert [i["game_id"] for i in items] == ["42"]

    code, raw = call(base, "/api/v1/soundtracks/undo", {"id": "42"})
    assert code == 200 and json.loads(raw) == {"removed": 2, "remaining": 0}
    assert list(romm.tracks[42].values()) == ["Mine Already.mp3"]

    # the upload used a write-scoped login from the library entry; the read-only token is untouched
    assert romm.issued_scopes.count("roms.read roms.write") == 1      # one write login, cached for the rest
    assert all(r[2].get("authorization") == "Bearer " + TOKEN for r in romm.requests if r[1].startswith("/api/roms"))


def test_neither_the_token_nor_the_password_appears_anywhere_a_client_or_log_can_see(env):
    base, service, romm, caplog = env
    out = [call(base, "/api/v1/soundtracks/game?id=42")[1], call(base, "/api/v1/soundtracks/search?id=42")[1]]
    out.append(call(base, "/api/v1/soundtracks/download",
                    {"id": "42", "candidate": {"provider": "zophar", "id": "/music/snes-spc/chrono-trigger"}, "format": "mp3"})[1])
    wait_done(base)
    romm.fail_delete = {1001}
    out.append(call(base, "/api/v1/soundtracks/undo", {"id": "42"})[1])           # RomM 500s, echoing the credential
    out.append(call(base, "/api/v1/soundtracks/jobs")[1])
    out.append(call(base, "/api/v1/soundtracks/game?id=42")[1])
    out.append(caplog.text)
    for text in out:
        assert TOKEN not in text and PASSWORD not in text


def test_errors_are_plain_statuses(env):
    base, service, romm, _ = env
    assert call(base, "/api/v1/soundtracks/game?id=999")[0] == 404          # not in the library
    assert call(base, "/api/v1/soundtracks/game?id=abc")[0] == 400
    assert call(base, "/api/v1/soundtracks/game")[0] == 400
    assert call(base, "/api/v1/soundtracks/download", {"id": "42"})[0] == 400
    assert call(base, "/api/v1/soundtracks/download",
                {"id": "42", "candidate": {"provider": "zophar", "id": "http://evil.example/"}, "format": "mp3"})[0] == 400
    code, raw = call(base, "/api/v1/soundtracks/undo", {"id": "42"})
    assert code == 200 and json.loads(raw)["removed"] == 0                 # nothing was added, nothing is removed
    assert not [r for r in romm.requests if r[0] == "DELETE"]


def test_a_second_download_for_the_same_game_is_refused_with_409(env, monkeypatch):
    base, service, romm, _ = env
    gate = threading.Event()
    real = st.zophar_plan
    store = service.soundtrack_store()
    store.providers["zophar"] = (st.zophar_search, lambda cid: (gate.wait(5), real(cid))[1])
    body = {"id": "42", "candidate": {"provider": "zophar", "id": "/music/snes-spc/chrono-trigger"}, "format": "mp3"}
    assert call(base, "/api/v1/soundtracks/download", body)[0] == 200
    assert call(base, "/api/v1/soundtracks/download", body)[0] == 409
    assert call(base, "/api/v1/soundtracks/undo", {"id": "42"})[0] == 409
    gate.set()
    assert wait_done(base)["state"] == "done"


def test_no_romm_library_means_a_clear_409_not_a_crash(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json")})
    service._library_cache = ([Game(id="1", name="X", platform="Switch", platform_slug="switch")], time.monotonic(), "")
    with pytest.raises(RuntimeError, match="RomM library"):
        service.soundtrack_game("1")


def test_game_detail_carries_the_rom_id_for_the_card(env):
    _, service, *_ = env
    assert service.game_detail("snes", "42")["rom_id"] == "42"
    assert service.game_detail("snes", "", "Not Owned")["rom_id"] == ""


def test_the_database_sits_beside_the_data_file(env, tmp_path):
    _, service, *_ = env
    service.soundtrack_store()
    assert (tmp_path / "romarr-soundtracks.db").exists()


def test_write_token_uses_the_write_scope_and_prefers_a_configured_api_token():
    from romarr.clients import Romm, RommConfig
    romm = FakeRomm()
    try:
        r = Romm(RommConfig(base_url=romm.url, username="tim", password=PASSWORD))
        assert r.write_token() == TOKEN and r.write_token() == TOKEN
        assert romm.issued_scopes == ["roms.read roms.write"]                   # asked once, then cached
        assert Romm(RommConfig(base_url=romm.url, api_token="operator-token")).write_token() == "operator-token"
        assert Romm(RommConfig(base_url=romm.url)).write_token() is None
    finally:
        romm.close()
