"""The extras HTTP API end to end: a live ROMarr, a loopback RomM, a fake indexer and download client."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from romarr import extras as ex
from romarr.app import ROMarr, make_handler
from romarr.libraries import Game
from extras_support import PASSWORD, TOKEN, FakeRomm2

KEY = "api-key-for-tests"


@pytest.fixture
def env(tmp_path, monkeypatch):
    romm = FakeRomm2()
    monkeypatch.setattr(ROMarr, "_refresh_counts", lambda self: None)
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json"), "ROMARR_API_KEY": KEY,
                      "ROMM_URL": romm.url, "ROMM_USERNAME": "tim", "ROMM_PASSWORD": PASSWORD})
    service._library_cache = ([Game(id="42", name="Chrono Trigger", platform="Super Nintendo", platform_slug="snes")],
                              time.monotonic(), "")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", service, romm
    httpd.shutdown()
    httpd.server_close()
    romm.close()


def call(base, path, body=None, key=KEY, raw=None, method=None):
    req = urllib.request.Request(base + path, method=method or ("POST" if (body is not None or raw is not None) else "GET"))
    if key:
        req.add_header("X-Api-Key", key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    if raw is not None:
        req.add_header("Content-Type", "application/octet-stream")
        req.data = raw
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def wait_done(base, kind, gid="42"):
    for _ in range(200):
        _, d = call(base, f"/api/v1/extras/game?id={gid}&kind={kind}")
        job = d.get("job")
        if job and job["state"] != "running" and job.get("finished"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_every_extras_route_needs_the_api_key(env):
    base, *_ = env
    for path in ("/api/v1/extras/game?id=42&kind=dlc", "/api/v1/extras/torrents?id=42&kind=dlc", "/api/v1/extras/jobs",
                 "/api/v1/extras/archive/search?id=42&kind=manual"):
        assert call(base, path, key=None)[0] == 401, path
    for path in ("/api/v1/extras/link", "/api/v1/extras/undo", "/api/v1/extras/torrents/grab", "/api/v1/extras/archive/add"):
        assert call(base, path, {"id": "42", "kind": "dlc"}, key=None)[0] == 401, path
    assert call(base, "/api/v1/extras/upload?id=42&kind=manual&name=a.pdf", raw=b"%PDF", key=None)[0] == 401


def test_status_for_every_kind_and_bad_input(env):
    base, _s, romm = env
    romm.seed(42, "Pack.7z", "dlc")
    code, d = call(base, "/api/v1/extras/game?id=42&kind=dlc")
    assert code == 200 and d["count"] == 1 and d["files"][0]["name"] == "Pack.7z" and d["label"] == "DLC"
    assert call(base, "/api/v1/extras/game?id=42&kind=manual")[1]["count"] == 0
    assert call(base, "/api/v1/extras/game?id=42&kind=nope")[0] == 400
    assert call(base, "/api/v1/extras/game?id=abc&kind=dlc")[0] == 400
    assert call(base, "/api/v1/extras/game?id=999&kind=dlc")[0] == 404


def test_upload_from_the_browser_then_undo(env):
    base, _s, romm = env
    code, job = call(base, "/api/v1/extras/upload?id=42&kind=manual&name=Chrono%20Trigger%20Manual.pdf", raw=b"%PDF-1.4 hello")
    assert code == 200 and job["state"] in ("running", "done")
    assert wait_done(base, "manual")["state"] == "done"
    assert romm.held(42, "manual") == {"Chrono Trigger Manual.pdf": b"%PDF-1.4 hello"}
    d = call(base, "/api/v1/extras/game?id=42&kind=manual")[1]
    assert d["undoable"] == 1 and d["count"] == 1
    code, out = call(base, "/api/v1/extras/undo", {"id": "42", "kind": "manual"})
    assert code == 200 and out["removed"] == 1 and romm.held(42, "manual") == {}
    assert TOKEN not in json.dumps(d)


def test_upload_refuses_the_wrong_type_an_empty_body_and_a_path_name(env):
    base, _s, romm = env
    assert call(base, "/api/v1/extras/upload?id=42&kind=manual&name=scan.jpg", raw=b"x")[0] == 400
    assert call(base, "/api/v1/extras/upload?id=42&kind=dlc&name=setup.exe", raw=b"MZ")[0] == 400
    assert call(base, "/api/v1/extras/upload?id=42&kind=dlc&name=a.7z", raw=b"")[0] == 400
    assert call(base, "/api/v1/extras/upload?id=999&kind=dlc&name=a.7z", raw=b"x")[0] == 404
    code, _ = call(base, "/api/v1/extras/upload?id=42&kind=dlc&name=..%2F..%2Fevil.7z", raw=b"x")
    assert code == 200
    wait_done(base, "dlc")
    assert set(romm.held(42, "dlc")) == {"evil.7z"}


def test_a_second_job_for_the_same_game_and_kind_is_a_409(env):
    base, service, _romm = env
    service.extras_store()._begin_job("42", "dlc", "Chrono Trigger", "x")
    code, d = call(base, "/api/v1/extras/upload?id=42&kind=dlc&name=a.7z", raw=b"x")
    assert code == 409 and "already running" in d["error"]
    assert call(base, "/api/v1/extras/undo", {"id": "42", "kind": "dlc"})[0] == 409
    assert service.extras_store().jobs()


def test_link_validation_and_private_addresses(env):
    base, *_ = env
    assert call(base, "/api/v1/extras/link", {"id": "42", "kind": "manual", "url": "ftp://x/y.pdf"})[0] == 400
    code, _ = call(base, "/api/v1/extras/link", {"id": "42", "kind": "manual", "url": "http://127.0.0.1:1/a.pdf"})
    assert code == 200
    job = wait_done(base, "manual")
    assert job["state"] == "error" and "private network" in job["message"]


def test_archive_routes_are_for_manuals_and_use_the_scrubbed_item(env, monkeypatch):
    base, *_ = env
    assert call(base, "/api/v1/extras/archive/search?id=42&kind=dlc")[0] == 400
    monkeypatch.setattr(ex, "polite_get", lambda url, **k: '{"response": {"docs": [{"identifier": "ct", "title": "Chrono Trigger Manual"}]}}'
                        if "advancedsearch" in url else '{"files": [{"name": "m.pdf", "source": "original", "size": "4"}]}')
    code, d = call(base, "/api/v1/extras/archive/search?id=42&kind=manual")
    assert code == 200 and d["items"][0]["id"] == "ct"
    code, d = call(base, "/api/v1/extras/archive/files?id=42&kind=manual&item=ct")
    assert code == 200 and d["files"][0]["name"] == "m.pdf"
    assert call(base, "/api/v1/extras/archive/files?id=42&kind=manual&item=..%2Fx")[0] == 400
    assert call(base, "/api/v1/extras/archive/add", {"id": "42", "kind": "manual", "item": "ct", "name": "x.exe"})[0] == 400


def test_torrent_search_and_grab_go_through_the_extras_category(env, monkeypatch):
    base, service, _romm = env

    class Rel:
        title, size, seeders, indexer, protocol, info_url = "Chrono Trigger DLC pack", 100, 9, "idx", "torrent", ""
        download_url = "magnet:?xt=urn:btih:abc"

    class Client:
        name, configured, last_error, last_job_id = "qBittorrent", True, "", "qbit-tag:TAG1"
        added = []

        def add(self, url, category=None):
            self.added.append((url, category))
            return True

    client = Client()
    from romarr import app as appmod
    monkeypatch.setattr(service.prowlarr, "search", lambda term: [Rel()])
    monkeypatch.setattr(appmod, "pick_client", lambda proto, clients: client)
    monkeypatch.setattr(appmod, "QBittorrent", Client)
    code, d = call(base, "/api/v1/extras/torrents?id=42&kind=dlc")
    assert code == 200 and d["term"] == "Chrono Trigger DLC" and d["items"][0]["title"] == "Chrono Trigger DLC pack"
    code, g = call(base, "/api/v1/extras/torrents/grab", {"id": "42", "kind": "dlc", "release": d["items"][0]["id"]})
    assert code == 200 and g["ok"] and client.added == [("magnet:?xt=urn:btih:abc", "romarr-extras")]
    w = call(base, "/api/v1/extras/game?id=42&kind=dlc")[1]["watch"]
    assert w["tag"] == "TAG1" and w["state"] == "downloading"
    assert call(base, "/api/v1/extras/game?id=42&kind=update")[1]["watch"] is None
    code, g = call(base, "/api/v1/extras/torrents/grab", {"id": "42", "kind": "dlc", "release": "expired"})
    assert g["ok"] is False and "expired" in g["error"]
    assert call(base, "/api/v1/extras/torrents/cancel", {"id": "42", "kind": "dlc"})[1]["ok"]
    assert service.extras_store().active_watches() == []
