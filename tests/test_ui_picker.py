"""Add New and the formats page use a searchable picker for long platform lists."""

from __future__ import annotations

from romarr import ui


def _src() -> str:
    return open(ui.__file__, encoding="utf-8").read()


def test_add_new_uses_the_picker_and_keeps_the_input_id():
    src = _src()
    # The hidden input carries the id, so `$('#a-plat').value` still works.
    assert "pickerHtml('a-plat'" in src and "$('#a-plat').value" in src
    assert "pickerHtml('ad-plat'" in src  # the Add dialog


def test_picker_is_keyboard_operable():
    src = _src()
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f"e.key==='{key}'" in src
