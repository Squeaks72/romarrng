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
