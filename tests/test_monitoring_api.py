"""Add New lookup, monitoring and the game page, end to end over loopback."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from romarr import metadata
from romarr.app import ROMarr, make_handler
from romarr.libraries import Game


@pytest.fixture
def server(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json"), "ROMARR_API_KEY": "k"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", service
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None):
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    req.add_header("X-Api-Key", "k")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_add_wanted_unmonitored_then_monitor(server):
    base, svc = server
    code, out = call(base, "/api/v1/wanted/add",
                     {"game": "Ico", "platform": "ps2", "monitored": False})
    assert code == 200 and out == {"ok": True, "state": "unmonitored"}
    assert svc.store.wanted[0].monitored is False
    code, out = call(base, "/api/v1/wanted/monitor",
                     {"game": "ico", "platform": "ps2", "monitored": True})
    assert code == 200 and svc.store.wanted[0].monitored is True
    code, _ = call(base, "/api/v1/wanted/monitor",
                   {"game": "Nope", "platform": "ps2", "monitored": True})
    assert code == 404


def test_add_wanted_rejects_missing_fields_and_unknown_platform(server):
    base, svc = server
    assert call(base, "/api/v1/wanted/add", {"game": "x"})[0] == 400
    code, out = call(base, "/api/v1/wanted/add", {"game": "x", "platform": "nope-console"})
    assert out["ok"] is False and "unknown platform" in out["error"]


def test_unmonitored_entries_are_skipped_by_the_missing_sweep(server):
    _, svc = server
    svc.store.want("Ico", "ps2", monitored=False)
    asked = []
    svc.request = lambda g, p: asked.append((g, p)) or {"ok": False}
    out = svc.search_missing()
    assert asked == [] and out["skipped"] == 1


def test_rss_watch_ignores_unmonitored_only(server):
    _, svc = server
    svc.store.want("Ico", "ps2", monitored=False)
    assert svc.rss_sync() == "nothing monitored, nothing to match"


def test_lookup_without_igdb_says_unconfigured(server):
    base, _ = server
    assert call(base, "/api/v1/lookup?q=zelda")[1] == {"configured": False, "items": []}
    assert call(base, "/api/v1/lookup?q=")[0] == 400


def test_lookup_reports_state_per_platform(server, monkeypatch):
    base, svc = server
    svc.store.put_item("metadata_providers", {"type": "igdb", "client_id": "a", "token": "b"})
    svc.store.want("Ico", "ps2")
    monkeypatch.setattr("romarr.app.igdb_catalog_platforms",
                        lambda cfg: [{"id": 8, "name": "PlayStation 2"}])
    seen = {}

    def fake_search(cfg, query, limit, offset, ids=None, **kw):
        seen["ids"] = ids
        return ([{"igdbId": 1, "title": "Ico", "summary": "", "coverUrl": "",
                  "releaseDate": "2001-09-24", "genres": ["Adventure"],
                  "platformOptions": [{"id": 8, "name": "PlayStation 2"},
                                      {"id": 9, "name": "PlayStation 3"}]}], None)
    monkeypatch.setattr("romarr.app.igdb_catalog_search", fake_search)
    code, out = call(base, "/api/v1/lookup?q=ico&platform=ps2")
    assert code == 200 and seen["ids"] == [8]
    item = out["items"][0]
    assert item["year"] == 2001
    assert [(o["slug"], o["state"]) for o in item["options"]] == [("ps2", "monitored")]


def test_lookup_failure_is_reported_not_swallowed(server, monkeypatch):
    base, svc = server
    svc.store.put_item("metadata_providers", {"type": "igdb", "client_id": "a", "token": "b"})

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr("romarr.app.igdb_catalog_search", boom)
    out = call(base, "/api/v1/lookup?q=ico")[1]
    assert out["configured"] is True and out["error"] == "IGDB did not answer"


def test_game_detail_builds_the_romm_link_from_settings(server):
    base, svc = server
    svc.store.update_settings({"romm_public_url": "https://romm.example/"})
    svc._library_cache = ([Game(id="42", name="Ico", platform="PlayStation 2",
                                platform_slug="ps2")], 0.0, "")
    svc.store.want("Ico", "ps2")
    code, out = call(base, "/api/v1/game/detail?platform=ps2&id=42")
    assert code == 200 and out["in_library"] is True
    assert out["romm_url"] == "https://romm.example/rom/42"
    assert out["wanted"]["game"] == "Ico"
    code, out = call(base, "/api/v1/game/detail?platform=ps2&title=Unknown")
    assert out["in_library"] is False and out["romm_url"] == ""


def test_igdb_search_is_never_sent_with_sort():
    seen = {}

    def fake(cfg, endpoint, body, strict=False):
        seen["body"] = body
        return []
    orig = metadata.igdb_query
    metadata.igdb_query = fake
    try:
        metadata.igdb_catalog_search({"client_id": "x", "token": "y"}, 'ze"lda', 5, 0, [8])
    finally:
        metadata.igdb_query = orig
    assert 'search "ze\\"lda"' in seen["body"] and "sort " not in seen["body"]
    assert "platforms = (8)" in seen["body"]


def test_queue_endpoint_carries_a_timestamp_and_accepts_refresh(server):
    base, _ = server
    code, out = call(base, "/api/v1/queue?refresh=1")
    assert code == 200 and out["items"] == [] and out["at"]
