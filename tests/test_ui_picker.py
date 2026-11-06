"""Long lists use a searchable picker, not a wall of buttons or a 49-row select."""

from __future__ import annotations

from romarr import ui


def _src() -> str:
    return open(ui.__file__, encoding="utf-8").read()


def test_library_has_no_platform_chip_wall():
    src = _src()
    assert "data-plat=" not in src
    assert "pickerHtml('lib-plat'" in src


def test_add_new_uses_the_picker_and_keeps_the_input_id():
    src = _src()
    # The hidden input carries the id, so `$('#a-plat').value` still works.
    assert "pickerHtml('a-plat'" in src and "$('#a-plat').value" in src
    assert "pickerHtml('ad-plat'" in src  # the Add dialog


def test_picker_is_keyboard_operable():
    src = _src()
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f"e.key==='{key}'" in src


def test_library_header_is_compact():
    src = _src()
    assert 'class="libstats"' in src and 'class="lfrow"' in src
    assert ".libstats{" in src and ".lfrow{" in src and ".pp-panel{" in src
