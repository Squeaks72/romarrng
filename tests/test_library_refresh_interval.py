"""How often the library is re-read in the background.

Each refresh walks the whole library on the server, so the default is an hour
and an environment variable can change it, but never to less than a minute.
"""

from romarr.app import ROMarr, library_refresh_seconds


def test_the_default_is_an_hour():
    assert library_refresh_seconds({}) == 3600
    assert library_refresh_seconds({"ROMARR_LIBRARY_REFRESH_SECONDS": ""}) == 3600


def test_the_interval_can_be_set_but_not_below_a_minute():
    assert library_refresh_seconds({"ROMARR_LIBRARY_REFRESH_SECONDS": "1800"}) == 1800
    assert library_refresh_seconds({"ROMARR_LIBRARY_REFRESH_SECONDS": "5"}) == 60


def test_nonsense_means_the_default():
    assert library_refresh_seconds({"ROMARR_LIBRARY_REFRESH_SECONDS": "often"}) == 3600


def test_the_service_uses_it():
    assert ROMarr.COUNT_TTL >= 60
