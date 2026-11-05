"""Long lists use a searchable picker, not a wall of buttons or a 49-row select."""

from __future__ import annotations

from romarr import ui


def _page() -> str:
    return getattr(ui, "PAGE", None) or getattr(ui, "INDEX_HTML", None) or ""


def test_library_has_no_platform_chip_wall():
    src = open(ui.__file__, encoding="utf-8").read()
    assert "data-plat=" not in src
    assert "pickerHtml('lib-plat'" in src


def test_add_and_search_use_the_picker_and_keep_the_input_ids():
    src = open(ui.__file__, encoding="utf-8").read()
    # The hidden input carries the id, so `$('#g-plat').value` still works.
    assert "pickerHtml('g-plat'" in src and "pickerHtml('s-plat'" in src
    assert "$('#g-plat').value" in src and "$('#s-plat').value" in src


def test_picker_is_keyboard_operable():
    src = open(ui.__file__, encoding="utf-8").read()
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f"e.key==='{key}'" in src
