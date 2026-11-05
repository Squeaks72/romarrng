"""Missing updates and DLC for Switch dumps, read from file names."""

from __future__ import annotations

from romarr.switch_report import analyse, report, scan_folder
from romarr.titled import SwitchTitle, TitleDBIndex


def _index(names=False):
    idx = TitleDBIndex()
    # Base 01007960049A0000: update history v65536 then v131072; one DLC known.
    idx.add(SwitchTitle("01007960049a0000", name="Bayonetta 2" if names else ""))
    idx.add(SwitchTitle("01007960049a0800", versions={"65536": "2022-09-30", "131072": "2022-11-23"}))
    idx.add(SwitchTitle("01007960049a1001", name="Bayonetta 2 DLC" if names else ""))
    idx.names_loaded = names
    return idx


def _make(tmp, files):
    for rel in files:
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_current_game_with_no_gaps(tmp_path):
    _make(tmp_path, ["Bayonetta 2/Bayonetta 2 [01007960049A0000][v0][Base].nsz",
                     "Bayonetta 2/Bayonetta 2 [01007960049A0800][v131072][Update].nsz",
                     "Bayonetta 2/Bayonetta 2 [01007960049A1001][v0][DLC 1].nsz"])
    rep = report({"switch": tmp_path}, _index(names=True))
    row = rep["items"][0]
    assert row["update"] == "current" and row["installed_version"] == 131072
    assert row["dlc_missing"] == [] and rep["summary"]["games_with_gaps"] == 0


def test_outdated_update_and_missing_dlc_are_reported(tmp_path):
    _make(tmp_path, ["Bayonetta 2/Bayonetta 2 [01007960049A0000][v0][Base].nsz",
                     "Bayonetta 2/Bayonetta 2 [01007960049A0800][v65536][Update].nsz"])
    rep = report({"switch": tmp_path}, _index(names=True))
    row = rep["items"][0]
    assert row["update"] == "outdated" and row["latest_version"] == 131072
    assert [d["tid"] for d in row["dlc_missing"]] == ["01007960049A1001"]
    assert rep["summary"]["update_gaps"] == 1 and rep["summary"]["dlc_gaps"] == 1


def test_update_missing_entirely(tmp_path):
    _make(tmp_path, ["Bayonetta 2 [01007960049A0000][v0][Base].nsz"])  # loose file
    row = report({"switch": tmp_path}, _index())["items"][0]
    assert row["update"] == "missing"


def test_titles_unknown_to_titledb_are_not_called_current(tmp_path):
    _make(tmp_path, ["Mystery/Mystery [0100ABCD00010000][v0][Base].nsz"])
    row = report({"switch": tmp_path}, _index())["items"][0]
    assert row["update"] == "unknown"


def test_dlc_list_is_marked_incomplete_without_names(tmp_path):
    _make(tmp_path, ["Bayonetta 2/Bayonetta 2 [01007960049A0000][v0][Base].nsz"])
    rep = report({"switch": tmp_path}, _index(names=False))
    assert rep["summary"]["dlc_lists_complete"] is False


def test_media_folders_and_non_dumps_are_ignored(tmp_path):
    _make(tmp_path, ["covers/a [01007960049A0000][v0][Base].nsz", "Game/readme.txt"])
    assert scan_folder(tmp_path) == []


def test_switch_2_is_never_compared_with_switch_1_history(tmp_path):
    # A Switch 2 Edition pack carries a Switch 1 title ID; comparing it with
    # that title's Switch 1 updates would invent a gap.
    _make(tmp_path, ["Bayonetta 2 Switch 2 Edition [01007960049A0000].nup"])
    row = report({"switch-2": tmp_path}, _index(names=True))["items"][0]
    assert row["update"] == "unknown" and row["dlc_total"] is None


def test_a_title_with_no_version_history_is_unknown_not_current(tmp_path):
    idx = _index()
    idx.add(SwitchTitle("0100aaaa00010000"))
    _make(tmp_path, ["X/X [0100AAAA00010000][v0][Base].nsz"])
    assert report({"switch": tmp_path}, idx)["items"][0]["update"] == "unknown"


def test_ignored_dlc_is_removed_from_the_view_and_counts():
    from romarr.app import ROMarr as Service
    svc = Service.__new__(Service)
    svc.store = type("S", (), {"settings": {"ignored_dlc": ["01007960049A1001"]}, "save": lambda self: None})()
    svc.switch_updates = lambda refresh=False: {
        "items": [{"game": "G", "platform": "switch", "update": "current", "dlc_total": 2,
                   "dlc_installed": 0, "dlc_complete_list": True,
                   "dlc_missing": [{"tid": "01007960049A1001", "name": "A"},
                                   {"tid": "01007960049A1002", "name": "B"}]}],
        "summary": {"games": 1, "unknown_to_titledb": 0, "dlc_lists_complete": True}}
    view = svc.switch_view()
    row = view["items"][0]
    assert [d["tid"] for d in row["dlc_missing"]] == ["01007960049A1002"]
    assert [d["tid"] for d in row["dlc_ignored"]] == ["01007960049A1001"]
    assert row["dlc_total"] == 1 and view["summary"]["dlc_gaps"] == 1


def test_gap_map_never_builds_the_report_inline():
    from romarr.app import ROMarr as Service
    svc = Service.__new__(Service)
    svc._switch_cache = None
    svc._switch_building = True            # a build is already running
    svc.store = type("S", (), {"settings": {}, "save": lambda self: None})()
    assert svc.switch_gap_map() == {"ready": False, "games": {}, "summary": {}}
