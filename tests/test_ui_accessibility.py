"""Focused static QA for ROMarr's shared browser UI contracts."""
from __future__ import annotations

import re
import unittest
from collections import Counter
from html.parser import HTMLParser

from romarr.ui import CSS, JS, THEME_BOOT, page


class ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.landmarks: list[tuple[str, dict[str, str | None]]] = []
        self.nav_links = 0
        self.labels: list[dict[str, object]] = []
        self._labels: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag in {"main", "nav", "aside"}:
            self.landmarks.append((tag, values))
        if tag == "a" and "nav" in str(values.get("class", "")).split():
            self.nav_links += 1
        if tag == "label":
            label = {"for": values.get("for"), "contains_control": False}
            self._labels.append(label)
            self.labels.append(label)
        if tag in {"input", "select", "textarea", "button"}:
            for label in self._labels:
                label["contains_control"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag != "label":
            return
        if self._labels:
            self._labels.pop()


def color(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def luminance(value: str) -> float:
    channels = [channel / 255 for channel in color(value)]
    linear = [channel / 12.92 if channel <= 0.04045
              else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    a, b = sorted((luminance(first), luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def theme_tokens(mode: str) -> dict[str, str]:
    selector = (r":root\{([^}]*)\}" if mode == "dark" else
                r":root\[data-theme=\"" + re.escape(mode) + r"\"\]\{([^}]*)\}")
    block = re.search(selector, CSS, re.S)
    if not block:
        raise AssertionError(f"missing theme block: {mode}")
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,6})", block.group(1)))


class AccessibilityQATests(unittest.TestCase):
    def test_shell_has_landmarks_skip_link_and_keyboard_navigation(self) -> None:
        rendered = page()
        parsed = ShellParser()
        parsed.feed(rendered)
        self.assertIn('href="#main-content"', rendered)
        self.assertIn('id="main-content" tabindex="-1"', rendered)
        self.assertEqual([tag for tag, _ in parsed.landmarks], ["aside", "nav", "main"])
        self.assertEqual(parsed.nav_links, 31)
        self.assertFalse([key for key, count in Counter(parsed.ids).items() if count > 1])
        self.assertFalse([label for label in parsed.labels
                          if not label["for"] and not label["contains_control"]])

    def test_secondary_and_status_text_meets_wcag_aa_on_theme_surfaces(self) -> None:
        surfaces = ("--bg", "--surface", "--surface-2", "--surface-3", "--rail", "--rail-2")
        for mode in ("dark", "light", "sepia"):
            tokens = theme_tokens(mode)
            for foreground in ("--dim", "--ok", "--warn", "--bad", "--info"):
                for background in surfaces:
                    with self.subTest(mode=mode, foreground=foreground, background=background):
                        self.assertGreaterEqual(contrast(tokens[foreground], tokens[background]), 4.5)
            for foreground, background in (("--ok-ink", "--ok"), ("--warn-ink", "--warn"),
                                           ("--bad-ink", "--bad"), ("--info-ink", "--info")):
                with self.subTest(mode=mode, foreground=foreground, background=background):
                    self.assertGreaterEqual(contrast(tokens[foreground], tokens[background]), 4.5)

    def test_accent_text_accounts_for_every_surface_and_active_nav_tint(self) -> None:
        for token in ("--bg", "--surface", "--surface-2", "--surface-3", "--rail", "--rail-2"):
            self.assertIn(token, THEME_BOOT)
        self.assertIn("backgrounds.push", THEME_BOOT)
        self.assertIn("legible(accent,backgrounds)", THEME_BOOT)

    def test_navigation_and_mobile_drawer_have_accessible_state_and_focus(self) -> None:
        self.assertIn("aria-current','page'", JS)
        self.assertIn("aria-expanded", JS)
        self.assertIn("main.inert=true", JS)
        self.assertIn("setMobileNavOpen(false)", JS)
        self.assertIn("focusables[focusables.length-1]", JS)
        self.assertIn("history.replaceState", JS)

    def test_dialogs_restore_focus_trap_tabs_and_announce_modal_state(self) -> None:
        self.assertIn("setAttribute('aria-modal','true')", JS)
        self.assertIn("document.addEventListener('keydown'", JS)
        self.assertIn("event.key==='Escape'", JS)
        self.assertIn("event.key==='Tab'", JS)
        self.assertIn("target.focus({preventScroll:true})", JS)
        self.assertIn("main.inert=true", JS)

    def test_dynamic_forms_get_real_labels_and_help_descriptions(self) -> None:
        self.assertIn("function enhanceFormLabels", JS)
        self.assertIn("label.htmlFor=control.id", JS)
        self.assertIn("setAttribute('aria-describedby',help.id)", JS)
        self.assertIn("enhanceFormLabels(node)", JS)

    def test_async_feedback_and_filters_expose_announced_state(self) -> None:
        self.assertIn("id=\"app-announcement\"", page())
        self.assertIn("role=\"status\" aria-live=\"polite\"", page())
        self.assertIn("status.setAttribute('role','alert')", JS)
        self.assertIn("aria-pressed", JS)
        self.assertIn("data-cap", JS)
        self.assertIn("org-announcement", JS)

    def test_library_and_catalogue_discard_stale_responses(self) -> None:
        self.assertIn("let mobileNavPreviousOverflow='', routeEpoch=0", JS)
        self.assertIn("renderEpoch!==routeEpoch", JS)
        self.assertIn("request!==libraryRequest", JS)
        self.assertIn("d._catalogueRequest!==catalogueRequest", JS)
        self.assertIn("Page could not be loaded", JS)
        self.assertIn("aria-busy", JS)

    def test_reduced_motion_preference_is_respected(self) -> None:
        self.assertIn("@media(prefers-reduced-motion:reduce)", CSS)


if __name__ == "__main__":
    unittest.main()
