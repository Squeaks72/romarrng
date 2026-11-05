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
