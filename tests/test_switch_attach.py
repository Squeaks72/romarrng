"""Updates and DLC for a game on disk land inside that game's folder (RomM categories)."""

from __future__ import annotations

from romarr.library import switch_attach_dir


def _make(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


def test_update_goes_into_the_games_update_folder(tmp_path):
    _make(tmp_path, "Bayonetta 2/Bayonetta 2 [01007960049A0000][v0][Base].nsz")
    got = switch_attach_dir("Bayonetta 2 [01007960049A0800][v196608][Update].nsp", tmp_path)
    assert got == tmp_path / "Bayonetta 2" / "update"


def test_dlc_goes_into_the_games_dlc_folder(tmp_path):
    _make(tmp_path, "Game/Game [01006F8002326000][v0][Base].nsz")
    got = switch_attach_dir("Game DLC [01006F800232712D][v0].nsp", tmp_path)
    assert got == tmp_path / "Game" / "dlc"


def test_nothing_is_attached_when_the_base_game_is_absent(tmp_path):
    _make(tmp_path, "Other/Other [0100AAAA00010000][v0][Base].nsz")
    assert switch_attach_dir("X [01007960049A0800][v1][Update].nsp", tmp_path) is None


def test_base_games_are_never_attached(tmp_path):
    _make(tmp_path, "G/G [01007960049A0000][v0][Base].nsz")
    assert switch_attach_dir("G [01007960049A0000][v0][Base].nsp", tmp_path) is None


def test_media_folders_are_not_mistaken_for_games(tmp_path):
    _make(tmp_path, "covers/G [01007960049A0000][v0][Base].png")
    assert switch_attach_dir("G [01007960049A0800][v1][Update].nsp", tmp_path) is None
