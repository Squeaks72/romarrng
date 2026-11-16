"""Downloads that no console can read as-is are unpacked at import."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from romarr.library import import_rom, is_archive_name
from romarr.platforms import resolve

needs_bsdtar = pytest.mark.skipif(shutil.which("bsdtar") is None, reason="bsdtar not installed")


@pytest.fixture(autouse=True)
def _work(monkeypatch, tmp_path):
    monkeypatch.setenv("ROMARR_DATA", str(tmp_path / "state" / "romarr.json"))


def _iso(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "Game (USA).iso").write_bytes(b"x" * (9 * 1024 * 1024))   # upstream refuses a PS2 image under 8 MB
    return src


def test_compound_suffixes_are_archives():
    for name in ("a.tar.gz", "a.TGZ", "a.tar.xz", "a.7z", "a.zip", "a.rar", "a.tar"):
        assert is_archive_name(name)
    assert not is_archive_name("a.iso") and not is_archive_name("a.chd")


@needs_bsdtar
def test_tar_gz_is_unpacked_not_imported_as_the_archive(tmp_path):
    src = _iso(tmp_path)
    dl = tmp_path / "dl" / "Game.tar.gz"
    dl.parent.mkdir()
    subprocess.run(["bsdtar", "-czf", str(dl), "-C", str(src), "Game (USA).iso"], check=True)
    results = import_rom(dl, resolve("ps2"), tmp_path / "lib")
    assert [r.ok for r in results] == [True]
    assert results[0].destination.name == "Game (USA).iso"


def test_arcade_zips_are_left_alone(tmp_path):
    dl = tmp_path / "dl" / "pacman.zip"
    dl.parent.mkdir()
    with zipfile.ZipFile(dl, "w") as z:
        z.writestr("pacman.6e", b"a" * 50)
    results = import_rom(dl, resolve("arcade"), tmp_path / "lib")
    assert results[0].ok and results[0].destination.name == "pacman.zip"
