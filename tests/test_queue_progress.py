"""The Queue shows live progress and ETA from the download client."""

from __future__ import annotations

from romarr.clients import QBittorrent, QbitConfig


class _Resp:
    ok = True
    status_code = 200

    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    def get(self, url, **kw):
        return _Resp(self.rows)

    def post(self, url, **kw):
        return _Resp([])


def _client(rows):
    return QBittorrent(QbitConfig(base_url="http://q", category="romarr"), session=_Session(rows))


def test_progress_is_percent_eta_and_speed_keyed_by_hash():
    c = _client([{"hash": "ABC123", "progress": 0.4567, "eta": 600, "dlspeed": 2_000_000,
                  "state": "downloading", "total_size": 5000}])
    got = c.progress()["abc123"]
    assert got["progress"] == 45.7 and got["eta"] == 600 and got["speed"] == 2_000_000


def test_qbittorrent_infinite_eta_becomes_none():
    c = _client([{"hash": "h", "progress": 0.1, "eta": 8640000, "dlspeed": 0}])
    assert c.progress()["h"]["eta"] is None


def test_a_release_added_by_url_is_matched_to_the_torrent_by_name():
    from romarr.app import ROMarr
    rows = {"aaa": {"name": "[PS2] ICO [ENG|NTSC] [DVD-Convert]"},
            "bbb": {"name": "ICO PS2 [FULLCD]"},
            "ccc": {"name": "Something Else Entirely"}}
    m = ROMarr.match_torrent_by_name
    assert m("ICO [ENG|NTSC] [DVD-Convert]", rows, set()) == "aaa"     # tag in front
    assert m("ICO PS2 [FULLCD]", rows, set()) == "bbb"                 # exact
    assert m("A Totally Unrelated Game", rows, set()) is None          # no false match


def test_queue_view_shows_progress_for_a_row_with_no_recorded_hash():
    from romarr.app import ROMarr
    from romarr.store import QueueItem
    svc = ROMarr.__new__(ROMarr)
    item = QueueItem("Ico", "ps2", "ICO [PS2] [PAL]", 2, "grabbed", "", download_id="",
                     download_client="c1")

    class Client:
        configured = True
        romarr_id = "c1"
        name = "q"

        def progress(self):
            return {"d4559742": {"name": "ICO [PS2] [PAL]", "progress": 8.0, "eta": 600,
                                 "speed": 1000, "dl_state": "downloading", "total": 1}}
    svc.clients = [Client()]
    from unittest.mock import PropertyMock, patch
    with patch.object(ROMarr, "queue", new_callable=PropertyMock, return_value=[item]):
        view = svc.queue_view(refresh=True)
    assert view[0]["progress"] == 8.0 and view[0]["dl_state"] == "downloading"


class _AddResp(_Resp):
    def __init__(self, text):
        super().__init__([])
        self.text = text


class _AddSession(_Session):
    def __init__(self, text):
        super().__init__([])
        self._text = text

    def post(self, url, **kw):
        return _AddResp(self._text)


def test_qbittorrent_fails_body_is_not_a_successful_add():
    c = QBittorrent(QbitConfig(base_url="http://q", category="romarr"), session=_AddSession("Fails."))
    assert c.add("https://indexer/x.torrent") is False
    assert c.last_reject == "not_accepted"


def test_qbittorrent_ok_body_is_a_successful_add():
    c = QBittorrent(QbitConfig(base_url="http://q", category="romarr"), session=_AddSession("Ok."))
    assert c.add("magnet:?xt=urn:btih:" + "a" * 40) is True


def _view(item, rows):
    from unittest.mock import PropertyMock, patch
    from romarr.app import ROMarr
    svc = ROMarr.__new__(ROMarr)

    class Client:
        configured = True
        romarr_id = "c1"
        name = "q"

        def progress(self):
            return rows
    svc.clients = [Client()]
    with patch.object(ROMarr, "queue", new_callable=PropertyMock, return_value=[item]):
        return svc.queue_view(refresh=True)[0]


def test_a_row_with_a_qbittorrent_tag_finds_its_torrent_by_tag():
    from romarr.store import QueueItem
    item = QueueItem("Ico", "ps2", "whatever the indexer called it", 2, "grabbed", "",
                     download_id="qbit-tag:romarr-abc", download_client="c1")
    row = _view(item, {"h1": {"name": "other name", "tags": ["romarr-abc"], "progress": 50.0,
                              "eta": 10, "speed": 5, "dl_state": "downloading", "total": 1}})
    assert row["progress"] == 50.0 and "waiting" not in row


def test_a_row_with_a_recorded_infohash_matches_exactly():
    from romarr.store import QueueItem
    item = QueueItem("Ico", "ps2", "x", 2, "grabbed", "", release_id="btih:" + "a" * 40,
                     download_client="c1")
    row = _view(item, {"a" * 40: {"name": "unrelated", "tags": [], "progress": 12.5,
                                  "eta": None, "speed": 0, "dl_state": "stalledDL", "total": 1}})
    assert row["progress"] == 12.5


def test_a_row_the_client_does_not_list_is_marked_waiting():
    from romarr.store import QueueItem
    item = QueueItem("Ico", "ps2", "Ico PAL", 2, "grabbed", "", download_client="c1")
    row = _view(item, {"h": {"name": "Completely different", "tags": [], "progress": 1.0,
                             "eta": None, "speed": 0, "dl_state": "x", "total": 1}})
    assert row.get("waiting") is True and "progress" not in row


# ---- grab(): the duplicate guard and a "Fails." answer ------------------------

def _grab_service(tmp_path, client):
    from romarr.app import ROMarr
    svc = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json")})
    svc.clients = [client]
    return svc


class _Pick:
    title = "ICO [PS2] [PAL]"
    protocol = "torrent"
    seeders = 5
    size = 1000
    indexer = "idx"
    download_url = "magnet:?xt=urn:btih:" + "b" * 40
    file_selection_required = False


class _FailsClient:
    protocol = "torrent"
    name = "qBittorrent"
    configured = True
    last_job_id = ""
    last_error = ""
    last_reject = "not_accepted"
    calls = 0

    def add(self, url, **kw):
        type(self).calls += 1
        return False


def test_fails_body_is_a_failed_grab_that_is_not_blocklisted(tmp_path):
    svc = _grab_service(tmp_path, _FailsClient())
    out = svc.grab(_Pick(), "Ico", "ps2")
    assert out["ok"] is False and "did not accept" in out["error"]
    row = svc.store.queue[-1]
    assert row.state == "failed" and row.release_fault is False


def test_the_same_release_is_not_grabbed_twice(tmp_path):
    class Ok(_FailsClient):
        last_reject = ""
        last_job_id = "qbit-tag:romarr-1"
        calls = 0

        def add(self, url, **kw):
            type(self).calls += 1
            return True
    svc = _grab_service(tmp_path, Ok())
    assert svc.grab(_Pick(), "Ico", "ps2")["ok"] is True
    again = svc.grab(_Pick(), "Ico", "ps2")
    assert again["duplicate"] is True and Ok.calls == 1
    assert len([q for q in svc.store.queue if q.state == "grabbed"]) == 1
