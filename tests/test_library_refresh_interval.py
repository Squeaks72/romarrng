"""How often the library is re-read in the background.

Each refresh walks the whole library on the server, so the default is an hour
and an environment variable can change it, but never to less than a minute.
"""

import importlib

import romarr.app as app_module


def reload_with(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ROMARR_LIBRARY_REFRESH_SECONDS", raising=False)
    else:
        monkeypatch.setenv("ROMARR_LIBRARY_REFRESH_SECONDS", value)
    return importlib.reload(app_module).ROMarr.COUNT_TTL


def test_the_default_is_an_hour(monkeypatch):
    try:
        assert reload_with(monkeypatch, None) == 3600
    finally:
        monkeypatch.delenv("ROMARR_LIBRARY_REFRESH_SECONDS", raising=False)
        importlib.reload(app_module)


def test_the_interval_can_be_set_but_not_below_a_minute(monkeypatch):
    try:
        assert reload_with(monkeypatch, "1800") == 1800
        assert reload_with(monkeypatch, "5") == 60
        assert reload_with(monkeypatch, "") == 3600
    finally:
        monkeypatch.delenv("ROMARR_LIBRARY_REFRESH_SECONDS", raising=False)
        importlib.reload(app_module)
