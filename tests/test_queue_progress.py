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
                     download_client_id="c1")

    class Client:
        configured = True
        config_id = "c1"
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
