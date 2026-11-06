"""Plugins run as a separate uid when the kernel has no Landlock (Unraid).

The boundary is the file mode of /config/romarr.json: owned by ROMarr's user,
0600. The plugin uid cannot read it, so a plugin cannot read any credential.
"""

from __future__ import annotations

from romarr import hub


def _no_landlock(monkeypatch):
    from romarr.plugin_runtime import landlock
    monkeypatch.setattr(landlock, "probe", lambda: (False, "ENOSYS"))


def test_no_landlock_and_no_launcher_still_refuses(monkeypatch):
    _no_landlock(monkeypatch)
    ok, why = hub.sandbox_state()
    assert ok is False
    assert "uid isolation unavailable" in why


def test_uid_mode_is_reported_available_when_launcher_works(monkeypatch):
    _no_landlock(monkeypatch)
    monkeypatch.setattr(hub, "uid_isolation_state", lambda: (True, "ok"))
    assert hub._uid_mode() is True


def test_uid_mode_is_off_when_landlock_works(monkeypatch):
    from romarr.plugin_runtime import landlock
    monkeypatch.setattr(landlock, "probe", lambda: (True, "ok"))
    monkeypatch.setattr(hub, "uid_isolation_state", lambda: (True, "ok"))
    assert hub._uid_mode() is False


def test_plugins_do_not_get_the_library_password_by_default(monkeypatch):
    monkeypatch.setenv("LIBRARY_URL", "http://romm")
    monkeypatch.setenv("LIBRARY_USERNAME", "tim")
    monkeypatch.setenv("LIBRARY_PASSWORD", "hunter2")
    monkeypatch.delenv("ROMARR_PLUGIN_BACKEND_CREDENTIALS", raising=False)
    env = hub._backend_env()
    assert "ROMM_PASSWORD" not in env and "ROMM_USER" not in env
    assert env["ROMM_URL"] == "http://romm"


def test_credentials_are_opt_in(monkeypatch):
    monkeypatch.setenv("LIBRARY_URL", "http://romm")
    monkeypatch.setenv("LIBRARY_USERNAME", "tim")
    monkeypatch.setenv("LIBRARY_PASSWORD", "hunter2")
    monkeypatch.setenv("ROMARR_PLUGIN_BACKEND_CREDENTIALS", "1")
    env = hub._backend_env()
    assert env["ROMM_PASSWORD"] == "hunter2" and env["ROMM_USER"] == "tim"


def test_launcher_prefix_is_only_added_in_uid_mode():
    assert hub._PLUGIN_LAUNCHER.startswith("/")
