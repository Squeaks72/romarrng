"""DLC, update, manual and the other folder extras: filters, RomM upload, torrents, links, undo."""

from __future__ import annotations

import http.server
import os
import threading
import time
import zipfile

import pytest

from romarr import extras as ex
from romarr.soundtracks import JobBusy, RommError
from extras_support import TOKEN, FakeRomm2

GAME = {"id": "42", "name": "Chrono Trigger", "platform_slug": "snes", "platform_name": "SNES"}


@pytest.fixture
def romm():
    r = FakeRomm2()
    yield r
    r.close()


@pytest.fixture
def api(romm):
    return ex.ExtrasApi(romm.url, lambda refresh=False: TOKEN)


@pytest.fixture
def store(tmp_path):
    return ex.Extras(tmp_path / "e.db")


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


# ---------------------------------------------------------------- filters --

def test_allowed_file_blocks_programs_leftovers_and_hidden_files():
    assert ex.allowed_file("dlc", "Pack 1.nsp")
    assert ex.allowed_file("update", "patch_v1.1.7z")
    for bad in ("setup.exe", "run.BAT", "x.lnk", "release.nfo", "a.sfv", ".hidden", "Thumbs.db", "x.part"):
        assert not ex.allowed_file("dlc", bad), bad


def test_manual_folder_takes_only_documents():
    assert ex.allowed_file("manual", "Manual.PDF") and ex.allowed_file("manual", "notes.txt") and ex.allowed_file("manual", "a.md")
    assert not ex.allowed_file("manual", "scan.jpg") and not ex.allowed_file("manual", "pack.zip")


def test_pick_files_keeps_text_only_when_there_is_no_pdf():
    both = [("Manual.pdf", "/a", 1), ("readme.txt", "/b", 1)]
    assert [f[0] for f in ex.pick_files("manual", both)] == ["Manual.pdf"]
    assert [f[0] for f in ex.pick_files("manual", [("readme.txt", "/b", 1)])] == ["readme.txt"]


def test_clean_name_is_never_a_path():
    assert ex.clean_name("../../etc/passwd") == "passwd"
    assert ex.clean_name("a\\b\\c.pdf") == "c.pdf"


def test_torrent_files_skips_junk_names_collisions_and_symlinks_out(tmp_path):
    root = tmp_path / "torrent"
    put(root / "Game DLC" / "pack1.7z", b"1")
    put(root / "Game DLC" / "release.nfo")
    put(root / "Game DLC" / "setup.exe")
    put(root / "Disc 1" / "data.bin", b"a")
    put(root / "Disc 2" / "data.bin", b"b")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    os.symlink(outside, root / "link.7z")
    files, zips = ex.torrent_files(str(root), "dlc")
    names = sorted(f[0] for f in files)
    assert names == ["Disc 1 - data.bin", "Disc 2 - data.bin", "pack1.7z"]
    assert zips == []


def test_torrent_files_on_a_single_file_and_a_missing_path(tmp_path):
    f = put(tmp_path / "Update 1.1.zip", b"zz")
    assert [x[0] for x in ex.torrent_files(f, "update")[0]] == ["Update 1.1.zip"]
    assert ex.torrent_files(str(tmp_path / "nope"), "dlc") == ([], [])


# ------------------------------------------------------------ RomM upload --

def test_upload_is_chunked_with_the_target_folder_and_headers(api, romm, tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "CHUNK", 10)
    data = bytes(range(25))
    path = put(tmp_path / "pack.7z", data)
    api.upload_file(api.rom("42"), "dlc", "pack.7z", path, len(data))
    start = next(r for r in romm.requests if r[1] == "/api/roms/upload/start")
    assert start[2]["x-upload-platform"] == "7" and start[2]["x-upload-total-size"] == "25" and start[2]["x-upload-total-chunks"] == "3"
    assert b'"folder": "dlc"' in start[3] and b'"rom_id": 42' in start[3] and b'"overwrite": false' in start[3]
    assert romm.held(42, "dlc") == {"pack.7z": data}
    puts = [r for r in romm.requests if r[0] == "PUT"]
    assert [p[2]["x-chunk-index"] for p in puts] == ["0", "1", "2"]


def test_an_empty_file_uploads_with_no_chunks(api, romm, tmp_path):
    path = put(tmp_path / "empty.txt", b"")
    api.upload_file(api.rom("42"), "manual", "empty.txt", path, 0)
    assert romm.held(42, "manual") == {"empty.txt": b""}


def test_a_failed_chunk_is_retried_once(api, romm, tmp_path):
    romm.fail_chunk_once = True
    path = put(tmp_path / "a.pdf", b"pdfdata")
    api.upload_file(api.rom("42"), "manual", "a.pdf", path, 7)
    assert romm.held(42, "manual") == {"a.pdf": b"pdfdata"}


def test_an_upload_that_fails_is_cancelled(api, romm, tmp_path, monkeypatch):
    path = put(tmp_path / "a.pdf", b"pdfdata")
    monkeypatch.setattr(api, "_request", lambda *a, **k: (_ for _ in ()).throw(RommError(500, "boom"))
                        if a[1].endswith("complete") else type(api).__mro__[1]._request(api, *a, **k))
    with pytest.raises(RommError):
        api.upload_file(api.rom("42"), "manual", "a.pdf", path, 7)
    assert any(s["state"] == "cancelled" for s in romm.sessions.values())


def test_the_token_never_appears_in_errors(api, romm, tmp_path):
    romm.refuse_names.add("a.7z")
    path = put(tmp_path / "a.7z", b"x")
    with pytest.raises(RommError) as e:
        api.upload_file(api.rom("42"), "dlc", "a.7z", path, 1)
    assert e.value.status == 409 and TOKEN not in str(e.value)


# ----------------------------------------------------------- status / jobs --

def test_status_lists_only_the_files_of_that_kind(store, api, romm):
    romm.seed(42, "Pack.7z", "dlc")
    romm.seed(42, "Update.zip", "update")
    romm.seed(42, "Chrono Trigger.sfc", "game")
    s = store.status(GAME, "dlc", api)
    assert [f["name"] for f in s["files"]] == ["Pack.7z"] and s["count"] == 1 and s["kind"] == "dlc"
    assert s["links"] and s["undoable"] == 0 and s["error"] == ""


def test_status_flags_romms_own_scraped_manual(store, api, romm):
    romm.rom["has_manual"] = True
    assert store.status(GAME, "manual", api)["scraped_manual"] is True
    assert store.status(GAME, "dlc", api)["scraped_manual"] is False


def test_unknown_kind_is_refused(store, api):
    with pytest.raises(ValueError):
        store.status(GAME, "soundtrack", api)


def test_add_files_journals_skips_existing_and_undo_removes_only_ours(store, api, romm, tmp_path):
    mine = romm.seed(42, "Mine.7z", "dlc", b"mine")
    a = put(tmp_path / "t" / "New.7z", b"new")
    b = put(tmp_path / "t" / "Mine.7z", b"dup")
    job = store.start_files(GAME, "dlc", api, [("New.7z", a, 3), ("Mine.7z", b, 3)], "upload", cleanup=False, run_async=False)
    done = store.job_for("42", "dlc")
    assert done["state"] == "done" and done["made"] == 1 and done["skipped"] == 1 and job["id"] == done["id"]
    assert romm.held(42, "dlc") == {"Mine.7z": b"mine", "New.7z": b"new"}
    assert store.journal_count("42", "dlc") == 1
    out = store.undo(GAME, "dlc", api)
    assert out == {"removed": 1, "remaining": 0}
    assert romm.held(42, "dlc") == {"Mine.7z": b"mine"} and mine in romm.files[42]


def test_undo_of_one_kind_leaves_the_other_kinds_alone(store, api, romm, tmp_path):
    p1 = put(tmp_path / "a" / "x.7z", b"1")
    p2 = put(tmp_path / "a" / "y.zip", b"2")
    store.start_files(GAME, "dlc", api, [("x.7z", p1, 1)], "upload", cleanup=False, run_async=False)
    store.start_files(GAME, "update", api, [("y.zip", p2, 1)], "upload", cleanup=False, run_async=False)
    store.undo(GAME, "dlc", api)
    assert romm.held(42, "dlc") == {} and romm.held(42, "update") == {"y.zip": b"2"}


def test_a_file_romm_already_removed_counts_as_gone(store, api, romm, tmp_path):
    p = put(tmp_path / "a" / "x.7z", b"1")
    store.start_files(GAME, "dlc", api, [("x.7z", p, 1)], "upload", cleanup=False, run_async=False)
    romm.files[42].clear()
    assert store.undo(GAME, "dlc", api) == {"removed": 0, "remaining": 0}


def test_undo_explains_a_permission_refusal_and_keeps_the_journal(store, api, romm, tmp_path):
    p = put(tmp_path / "a" / "x.7z", b"1")
    store.start_files(GAME, "dlc", api, [("x.7z", p, 1)], "upload", cleanup=False, run_async=False)
    romm.deny_delete = True
    with pytest.raises(ValueError, match="permission to delete"):
        store.undo(GAME, "dlc", api)
    assert store.journal_count("42", "dlc") == 1


def test_manual_undo_uses_the_manual_endpoint(store, api, romm, tmp_path):
    p = put(tmp_path / "a" / "m.pdf", b"%PDF")
    store.start_files(GAME, "manual", api, [("m.pdf", p, 4)], "upload", cleanup=False, run_async=False)
    store.undo(GAME, "manual", api)
    assert any(r[0] == "DELETE" and "/manuals/files/" in r[1] for r in romm.requests)


def test_a_refused_file_is_skipped_not_fatal(store, api, romm, tmp_path):
    romm.refuse_names.add("bad.7z")
    a, b = put(tmp_path / "a" / "bad.7z"), put(tmp_path / "a" / "good.7z")
    store.start_files(GAME, "dlc", api, [("bad.7z", a, 1), ("good.7z", b, 1)], "upload", cleanup=False, run_async=False)
    j = store.job_for("42", "dlc")
    assert j["state"] == "done" and j["made"] == 1 and j["skipped"] == 1 and set(romm.held(42, "dlc")) == {"good.7z"}


def test_a_file_of_the_wrong_type_is_refused_before_a_job_starts(store, api):
    with pytest.raises(ValueError, match="nothing to add"):
        store.start_files(GAME, "manual", api, [("scan.jpg", "/x", 1)], "upload", run_async=False)
    assert store.job_for("42", "manual") is None


def test_a_rom_whose_name_would_change_is_left_alone(store, api, romm, tmp_path):
    romm.rom.update(has_multiple_files=False, fs_name="Radical Red 4.1.gba")
    p = put(tmp_path / "a" / "x.7z")
    store.start_files(GAME, "dlc", api, [("x.7z", p, 1)], "upload", cleanup=False, run_async=False)
    j = store.job_for("42", "dlc")
    assert j["state"] == "error" and "save matching" in j["message"] and romm.held(42, "dlc") == {}


def test_staged_files_are_deleted_after_the_upload(store, api, tmp_path):
    p = put(tmp_path / "stage" / "m.pdf", b"%PDF")
    store.start_files(GAME, "manual", api, [("m.pdf", p, 4)], "upload", run_async=False)
    assert not os.path.exists(p)


def test_only_one_job_per_game_and_kind_runs_at_a_time(store, api):
    store._begin_job("42", "dlc", "Chrono Trigger", "x")
    with pytest.raises(JobBusy):
        store._begin_job("42", "dlc", "Chrono Trigger", "x")
    store._begin_job("42", "update", "Chrono Trigger", "x")       # another kind is a different job
    with pytest.raises(JobBusy):
        store.undo(GAME, "dlc", None)


def test_a_403_on_upload_asks_for_write_permission(store, api, romm, tmp_path, monkeypatch):
    p = put(tmp_path / "a" / "x.7z")
    monkeypatch.setattr(ex.ExtrasApi, "upload_file", lambda *a, **k: (_ for _ in ()).throw(RommError(403, "no")))
    store.start_files(GAME, "dlc", api, [("x.7z", p, 1)], "upload", cleanup=False, run_async=False)
    assert "roms.write" in store.job_for("42", "dlc")["message"]


# -------------------------------------------------------------------- links --

class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/m.pdf":
            self._send(200, b"%PDF-1.4 manual", "application/pdf")
        elif self.path == "/page":
            self._send(200, b"<html></html>", "text/html")
        elif self.path == "/go":
            self.send_response(302)
            self.send_header("Location", "/m.pdf")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/dl":
            self._send(200, b"%PDF-1.4 named", "application/octet-stream",
                       {"Content-Disposition": 'attachment; filename="Chrono Trigger (USA).pdf"'})
        elif self.path == "/exe":
            self._send(200, b"MZ", "application/octet-stream", {"Content-Disposition": 'attachment; filename="setup.exe"'})
        elif self.path == "/big":
            self._send(200, b"x" * 100, "application/pdf")
        else:
            self._send(404, b"no", "text/plain")

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    monkeypatch.setattr(ex, "ALLOW_PRIVATE_HOSTS", True)
    monkeypatch.setattr(ex, "_wait_turn", lambda *a, **k: None)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_a_link_to_a_pdf_is_fetched_and_uploaded(store, api, romm, site):
    store.start_link(GAME, "manual", api, site + "/m.pdf", run_async=False)
    j = store.job_for("42", "manual")
    assert j["state"] == "done", j
    assert romm.held(42, "manual") == {"m.pdf": b"%PDF-1.4 manual"} and store.journal_count("42", "manual") == 1
    assert os.listdir(store.tmp_dir) == []


def test_redirects_are_followed_and_content_disposition_names_the_file(store, api, romm, site):
    store.start_link(GAME, "manual", api, site + "/go", run_async=False)
    store.start_link(GAME, "manual", api, site + "/dl", run_async=False)
    assert set(romm.held(42, "manual")) == {"m.pdf", "Chrono Trigger (USA).pdf"}


def test_a_web_page_a_program_and_a_wrong_type_are_refused(store, api, romm, site):
    for path, word in (("/page", "web page"), ("/exe", "not a type"), ("/m.pdf", None)):
        store.start_link(GAME, "dlc" if path == "/m.pdf" else "manual", api, site + path, run_async=False)
    msgs = [j["message"] for j in store.jobs()]
    assert any("web page" in m for m in msgs) and any("not a type" in m for m in msgs)
    assert romm.held(42, "manual") == {}
    assert os.listdir(store.tmp_dir) == [] if os.path.isdir(store.tmp_dir) else True


def test_a_site_error_and_a_non_http_link_are_reported(store, api, site):
    store.start_link(GAME, "manual", api, site + "/missing", run_async=False)
    assert "404" in store.job_for("42", "manual")["message"]
    with pytest.raises(ValueError):
        store.start_link(GAME, "manual", api, "ftp://example.com/x.pdf", run_async=False)
    with pytest.raises(ValueError):
        store.start_link(GAME, "manual", api, "file:///etc/passwd", run_async=False)


def test_a_file_over_the_limit_is_refused_and_removed(tmp_path, site):
    with pytest.raises(ValueError, match="larger"):
        ex.fetch_link(site + "/big", str(tmp_path / "tmp"), "manual", limit=10)
    assert not (tmp_path / "tmp").exists() or os.listdir(tmp_path / "tmp") == []


def test_a_body_that_outgrows_its_declared_size_is_cut_off_and_removed(tmp_path, monkeypatch):
    class R:
        is_redirect, status_code, ok = False, 200, True
        headers = {"Content-Type": "application/pdf"}

        def iter_content(self, n):
            yield b"x" * 8
            yield b"x" * 8

        def close(self):
            pass
    monkeypatch.setattr(ex, "_wait_turn", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_check_host", lambda h: None)
    monkeypatch.setattr(ex.requests, "get", lambda url, **k: R())
    with pytest.raises(ValueError, match="larger"):
        ex.fetch_link("https://example.com/a.pdf", str(tmp_path / "tmp"), "manual", limit=10)
    assert os.listdir(tmp_path / "tmp") == []


def test_private_addresses_are_refused_without_any_request(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(ex.requests, "get", lambda *a, **k: seen.append(a))
    for url in ("http://127.0.0.1/x.pdf", "http://localhost/x.pdf", "http://192.168.0.125:6865/x.pdf",
                "http://169.254.169.254/latest/meta-data/x.pdf", "http://[::1]/x.pdf"):
        with pytest.raises(ValueError, match="private network|look up"):
            ex.fetch_link(url, str(tmp_path), "manual")
    assert seen == []


def test_a_redirect_onto_the_local_network_is_refused(tmp_path, monkeypatch):
    class R:
        is_redirect, status_code, ok = True, 302, False
        headers = {"Location": "http://192.168.0.1/admin.pdf"}

        def close(self):
            pass
    calls = []
    monkeypatch.setattr(ex, "_wait_turn", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_check_host", lambda h: (_ for _ in ()).throw(ValueError("private network")) if h.startswith("192.") else None)
    monkeypatch.setattr(ex.requests, "get", lambda url, **k: (calls.append(url), R())[1])
    with pytest.raises(ValueError, match="private network"):
        ex.fetch_link("https://example.com/x.pdf", str(tmp_path), "manual")
    assert calls == ["https://example.com/x.pdf"]


# ---------------------------------------------------------- Internet Archive --

def test_archive_manual_search_ranks_by_title_and_drops_unrelated(monkeypatch):
    docs = '{"response": {"docs": [{"identifier": "ct-manual", "title": "Chrono Trigger (USA) Manual", "item_size": 10},' \
           '{"identifier": "cooking", "title": "Cooking Instruction Booklet", "item_size": 1}]}}'
    seen = []
    monkeypatch.setattr(ex, "polite_get", lambda url, **k: (seen.append(url), docs)[1])
    out = ex.archive_manual_search("Chrono Trigger")
    assert [x["id"] for x in out] == ["ct-manual"] and out[0]["url"].endswith("/details/ct-manual")
    assert "mediatype%3Atexts" in seen[0]


def test_archive_item_files_offers_only_documents_originals_first(monkeypatch):
    meta = '{"files": [{"name": "scan.jpg", "source": "original"}, {"name": "b.pdf", "source": "derivative", "size": "5"},' \
           '{"name": "a manual.pdf", "source": "original", "size": "9"}, {"name": "x.exe"}]}'
    monkeypatch.setattr(ex, "polite_get", lambda url, **k: meta)
    out = ex.archive_item_files("ct-manual")
    assert [f["name"] for f in out] == ["a manual.pdf", "b.pdf"]
    assert out[0]["url"] == "https://archive.org/download/ct-manual/a%20manual.pdf" and out[0]["size"] == 9
    with pytest.raises(ValueError):
        ex.archive_item_files("../etc")


def test_archive_add_validates_and_uploads(store, api, romm, monkeypatch):
    got = []

    def fake_fetch(url, tmp_dir, kind, progress=None, limit=0):
        got.append(url)
        os.makedirs(tmp_dir, exist_ok=True)
        p = os.path.join(tmp_dir, "dl-x")
        open(p, "wb").write(b"%PDF")
        return "a manual.pdf", p, 4
    monkeypatch.setattr(ex, "fetch_link", fake_fetch)
    store.start_archive(GAME, "manual", api, "ct-manual", "a manual.pdf", run_async=False)
    assert got == ["https://archive.org/download/ct-manual/a%20manual.pdf"]
    assert romm.held(42, "manual") == {"a manual.pdf": b"%PDF"}
    for bad in (("../x", "a.pdf"), ("ct", "a.exe"), ("ct", "")):
        with pytest.raises(ValueError):
            store.start_archive(GAME, "manual", api, *bad, run_async=False)


def test_kind_links_cover_the_manual_sites():
    names = [l["name"] for l in ex.kind_links("manual", "Chrono Trigger", "SNES")]
    assert "Internet Archive" in names and "Replacement Docs" in names
    assert all("Chrono" in l["url"] or "Chrono" in __import__("urllib.parse").parse.unquote_plus(l["url"])
               for l in ex.kind_links("dlc", "Chrono Trigger", "SNES"))


# ----------------------------------------------------------------- torrents --

def row(tag, progress, path="", state="uploading"):
    return {"tags": tag, "progress": progress, "content_path": path, "name": "Rel", "state": state, "num_seeds": 3}


def run(store, api, rows, game=GAME):
    return store.process_watches(rows, lambda k: (game, api), lambda p: p)


def test_a_watched_torrent_is_followed_then_its_files_are_added(store, api, romm, tmp_path):
    store.add_watch("42", "dlc", "tagA", "Chrono Trigger DLC")
    run(store, api, [row("tagA", 0.4)])
    w = store.watch_for("42", "dlc")
    assert w["state"] == "downloading" and "40%" in w["message"]
    root = tmp_path / "t"
    put(root / "dlc1.7z", b"1")
    put(root / "release.nfo")
    put(root / "setup.exe")
    run(store, api, [row("tagA", 1.0, str(root))])
    w = store.watch_for("42", "dlc")
    assert w["state"] == "added" and "Added 1 file" in w["message"]
    assert romm.held(42, "dlc") == {"dlc1.7z": b"1"} and store.journal_count("42", "dlc") == 1
    assert store.active_watches() == []
    assert os.path.exists(root / "dlc1.7z")           # the torrent's own files are never touched


def test_a_manual_torrent_takes_pdfs_including_from_zips(store, api, romm, tmp_path):
    root = tmp_path / "t"
    put(root / "scan.jpg")
    with zipfile.ZipFile(root / "pack.zip", "w") as z:
        z.writestr("books/Manual.pdf", b"%PDF-zip")
        z.writestr("books/readme.txt", b"hi")
        z.writestr("setup.exe", b"MZ")
    store.add_watch("42", "manual", "tagM", "Manual pack")
    run(store, api, [row("tagM", 1.0, str(root))])
    assert romm.held(42, "manual") == {"books - Manual.pdf": b"%PDF-zip"}
    assert os.listdir(store.tmp_dir) == []


def test_a_torrent_with_nothing_usable_fails_with_a_reason(store, api, tmp_path):
    root = tmp_path / "t"
    put(root / "setup.exe")
    store.add_watch("42", "update", "tagU", "Wrong release")
    run(store, api, [row("tagU", 1.0, str(root))])
    w = store.watch_for("42", "update")
    assert w["state"] == "failed" and "Nothing in the torrent fits" in w["message"]


def test_a_torrent_path_ROMarr_cannot_see_explains_the_mapping(store, api, tmp_path):
    store.add_watch("42", "dlc", "tagP", "Rel")
    run(store, api, [row("tagP", 1.0, "/downloads/not-mounted")])
    assert "remote path mapping" in store.watch_for("42", "dlc")["message"]


def test_a_torrent_with_hundreds_of_files_is_not_filed(store, api, romm, tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "MAX_TORRENT_FILES", 3)
    root = tmp_path / "t"
    for i in range(5):
        put(root / f"f{i}.bin")
    store.add_watch("42", "dlc", "tagB", "Rel")
    run(store, api, [row("tagB", 1.0, str(root))])
    assert store.watch_for("42", "dlc")["state"] == "failed" and romm.held(42, "dlc") == {}


def test_a_busy_game_keeps_the_torrent_waiting(store, api, tmp_path):
    root = tmp_path / "t"
    put(root / "a.7z")
    store.add_watch("42", "dlc", "tagW", "Rel")
    store._begin_job("42", "dlc", "x", "x")
    run(store, api, [row("tagW", 1.0, str(root))])
    assert store.watch_for("42", "dlc")["state"] == "downloading"


def test_a_torrent_that_vanishes_is_given_up_on_after_a_while(store, api, monkeypatch):
    wid = store.add_watch("42", "dlc", "tagG", "Rel")
    run(store, api, [])
    assert store.watch_for("42", "dlc")["state"] == "downloading"
    monkeypatch.setattr(ex, "WATCH_LOST_AFTER", -1)
    run(store, api, [])
    assert store.watch_for("42", "dlc")["state"] == "lost" and wid


def test_a_new_watch_replaces_the_old_one_for_that_game_and_kind_only(store):
    store.add_watch("42", "dlc", "t1", "one")
    store.add_watch("42", "update", "t2", "two")
    store.add_watch("42", "dlc", "t3", "three")
    assert sorted((w["kind"], w["tag"]) for w in store.active_watches()) == [("dlc", "t3"), ("update", "t2")]
    store.cancel_watch("42", "dlc")
    assert [w["kind"] for w in store.active_watches()] == ["update"]


def test_waiting_for_the_library_keeps_a_finished_torrent_pending(store, api, tmp_path):
    store.add_watch("42", "dlc", "tagL", "Rel")

    def resolve(k):
        raise LookupError("library not loaded")
    store.process_watches([row("tagL", 1.0, str(tmp_path))], resolve, lambda p: p)
    w = store.watch_for("42", "dlc")
    assert w["state"] == "downloading" and "waiting for the RomM library" in w["message"]
