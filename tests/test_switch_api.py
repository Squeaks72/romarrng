"""The Switch Updates & DLC endpoints, over loopback against a temp library."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from romarr.app import ROMarr, make_handler
from romarr.libraries import Game
from romarr.titled import SwitchTitle, TitleDBIndex

BASE = "01007960049A0000"
DLC = "01007960049A1001"


def _index():
    idx = TitleDBIndex()
    idx.add(SwitchTitle("01007960049a0000", name="Bayonetta 2"))
    idx.add(SwitchTitle("01007960049a0800", versions={"65536": "2022-09-30", "131072": "2022-11-23"}))
    idx.add(SwitchTitle("01007960049a1001", name="Bayonetta 2 DLC"))
    idx.names_loaded = True
    return idx


@pytest.fixture
def server(tmp_path):
    lib = tmp_path / "lib"
    folder = lib / "switch" / "Bayonetta 2"
    folder.mkdir(parents=True)
    (folder / f"Bayonetta 2 [{BASE}][v0][Base].nsz").write_bytes(b"x")
    (folder / "Bayonetta 2 [01007960049A0800][v65536][Update].nsz").write_bytes(b"x")
    svc = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json"), "ROMARR_API_KEY": "k",
                  "LIBRARY_PATH": str(lib)})
    svc.titled = _index()
    svc._library_cache = ([Game(id="7", name="Bayonetta 2", platform="Nintendo Switch",
                                platform_slug="switch")], 0.0, "")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", svc
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None):
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    req.add_header("X-Api-Key", "k")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_updates_report_lists_outdated_game_and_missing_dlc(server):
    base, _ = server
    rep = call(base, "/api/v1/switch/updates?refresh=1")
    row = rep["items"][0]
    assert row["update"] == "outdated" and row["rom_id"] == "7"
    assert [m["tid"] for m in row["dlc_missing"]] == [DLC]
    assert rep["summary"]["games_with_gaps"] == 1
    assert call(base, "/api/v1/switch/updates?game=nothing")["items"] == []


def test_ignoring_a_dlc_takes_it_out_of_the_gaps(server):
    base, svc = server
    call(base, "/api/v1/switch/updates?refresh=1")
    out = call(base, "/api/v1/switch/ignore", {"tids": [DLC, "not-a-tid"], "ignored": True})
    assert out == {"ok": True, "ignored_total": 1}
    row = call(base, "/api/v1/switch/updates")["items"][0]
    assert row["dlc_missing"] == [] and [m["tid"] for m in row["dlc_ignored"]] == [DLC]
    call(base, "/api/v1/switch/ignore", {"tids": [DLC], "ignored": False})
    assert call(base, "/api/v1/switch/updates")["items"][0]["dlc_missing"]


def test_gaps_endpoint_answers_from_the_cache_without_blocking(server):
    base, svc = server
    svc.switch_updates = lambda refresh=False: (_ for _ in ()).throw(AssertionError("blocked"))
    svc._switch_building = True          # pretend a build is already running
    assert call(base, "/api/v1/switch/gaps")["ready"] is False
    svc._switch_building = False
    svc.switch_updates = ROMarr.switch_updates.__get__(svc)
    svc.switch_updates(refresh=True)
    gaps = call(base, "/api/v1/switch/gaps")
    assert gaps["ready"] is True and gaps["games"] == {"7": ["update", "dlc"]}


def test_counts_carry_the_gap_badge(server):
    _, svc = server
    svc.switch_updates(refresh=True)
    assert svc.counts()["switchgaps"] == 1
