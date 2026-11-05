"""Long lists use a searchable picker, not a wall of buttons or a 49-row select."""

from __future__ import annotations

from romarr import ui


def _page() -> str:
    return getattr(ui, "PAGE", None) or getattr(ui, "INDEX_HTML", None) or ""


def test_library_has_no_platform_chip_wall():
    src = open(ui.__file__, encoding="utf-8").read()
    assert "data-plat=" not in src
    assert "pickerHtml('lib-plat'" in src


def test_add_new_uses_the_picker_and_keeps_the_input_id():
    src = open(ui.__file__, encoding="utf-8").read()
    # The hidden input carries the id, so `$('#a-plat').value` still works.
    assert "pickerHtml('a-plat'" in src and "$('#a-plat').value" in src
    assert "pickerHtml('ad-plat'" in src  # the Add dialog


def test_picker_is_keyboard_operable():
    src = open(ui.__file__, encoding="utf-8").read()
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f"e.key==='{key}'" in src
