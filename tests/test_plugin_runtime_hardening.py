"""The way plugins are started: trusted bootstrap, scratch, and (no Landlock) a separate uid.

rom_hub is not needed: PluginProcess and the broker host are faked with the same
shape the pinned rom-hub has (`broker.host.plugin_environment`, `PluginProcess.start`
launching `[sys.executable, "-m", "rom_hub_sdk.runner"]` with cwd = the plugin dir).
"""

from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

from romarr import hub


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """A fake Hub home with one plugin, and a recorder standing in for Popen."""
    home = tmp_path / "hub"
    plugin_dir = home / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    scratch_root = tmp_path / "tmpfs"
    scratch_root.mkdir()
    monkeypatch.setattr(hub, "HOME", home)
    monkeypatch.setattr("romarr.plugin_runtime.scratch.tmpfs_root", lambda: scratch_root)
    calls = []

    def recorder(args, *rest, **kwargs):
        calls.append((list(args), kwargs))
        return types.SimpleNamespace(args=args)

    monkeypatch.setattr(subprocess, "Popen", recorder)
    monkeypatch.setattr(hub, "_PLUGIN_RUNTIME_INSTALLED", False)

    class Host:
        @staticmethod
        def plugin_environment(base=None):
            return {"PATH": "/usr/bin", "PYTHONIOENCODING": "utf-8"}

    class Process:
        def __init__(self):
            self.plugin_dir = plugin_dir
            self.data_assets = {}

        def start(self):
            return subprocess.Popen([sys.executable, "-m", "rom_hub_sdk.runner"],
                                    cwd=str(self.plugin_dir),
                                    env=Host.plugin_environment())

        def close(self):
            return None

    hub._install_plugin_runtime_hardening(Process, Host)
    return types.SimpleNamespace(process=Process(), calls=calls, scratch_root=scratch_root)


def test_landlock_mode_starts_the_trusted_bootstrap_without_the_launcher(rig, monkeypatch):
    monkeypatch.setattr(hub, "_uid_mode", lambda: False)
    rig.process.start()
    args, kwargs = rig.calls[-1]
    assert args[:3] == [sys.executable, "-S", "-c"]
    env = kwargs["env"]
    assert env["ROMARR_HUB_LANDLOCK"] == "1" and "ROMARR_HUB_ISOLATION" not in env
    assert env["PYTHONNOUSERSITE"] == "1"


def test_uid_mode_goes_through_the_setuid_launcher(rig, monkeypatch):
    monkeypatch.setattr(hub, "_uid_mode", lambda: True)
    monkeypatch.setenv("ROMARR_DATA", "/config/romarr.json")
    rig.process.start()
    args, kwargs = rig.calls[-1]
    assert args[0] == hub._PLUGIN_LAUNCHER and args[1] == sys.executable
    env = kwargs["env"]
    assert env["ROMARR_HUB_ISOLATION"] == "uid"
    assert env["ROMARR_HUB_PROTECT"] == "/config/romarr.json"
    assert "ROMARR_HUB_LANDLOCK" not in env
    # The plugin uid has to be able to use its own scratch.
    scratch = rig.process.__dict__["_romarr_plugin_scratch"]
    assert os.stat(scratch).st_mode & 0o777 == 0o777
    assert env["HOME"] == env["TMPDIR"] == str(scratch)


def test_the_plugin_environment_carries_no_romarr_secrets(rig, monkeypatch):
    monkeypatch.setenv("ROMARR_API_KEY", "super-secret-key")
    monkeypatch.setenv("LIBRARY_PASSWORD", "pw-value")
    monkeypatch.setattr(hub, "_uid_mode", lambda: True)
    rig.process.start()
    blob = repr(rig.calls[-1][1]["env"])
    assert "super-secret-key" not in blob and "pw-value" not in blob


def test_scratch_is_removed_when_the_process_closes(rig, monkeypatch):
    monkeypatch.setattr(hub, "_uid_mode", lambda: False)
    rig.process.start()
    scratch = rig.process._romarr_plugin_scratch
    assert scratch.is_dir()
    rig.process.close()
    assert not scratch.exists()


def test_an_unexpected_runner_command_is_refused(rig, monkeypatch):
    monkeypatch.setattr(hub, "_uid_mode", lambda: False)
    token = hub._PLUGIN_RUNTIME_CONTEXT.set(hub._plugin_runtime_context(rig.process))
    try:
        with pytest.raises(RuntimeError, match="unsupported"):
            subprocess.Popen(["/bin/sh", "-c", "id"], cwd=str(rig.process.plugin_dir))
    finally:
        hub._PLUGIN_RUNTIME_CONTEXT.reset(token)


def test_a_plugin_dir_outside_the_hub_home_is_refused(rig, tmp_path):
    rig.process.plugin_dir = tmp_path
    with pytest.raises(RuntimeError, match="escapes"):
        hub._plugin_runtime_context(rig.process)


def test_other_popen_calls_are_untouched(rig):
    subprocess.Popen(["/bin/true"])
    assert rig.calls[-1][0] == ["/bin/true"]


# ---- uid isolation probe --------------------------------------------------

_REAL_UID_STATE = hub.uid_isolation_state     # conftest stubs the module attribute per test


def _probe(monkeypatch, mode, uid=0, run_out="10001 10001 0\n", returncode=0, access=True):
    monkeypatch.setattr(hub, "_UID_ISOLATION_CACHE", None)
    st = types.SimpleNamespace(st_mode=mode, st_uid=uid)
    monkeypatch.setattr(os, "stat", lambda p: st)
    monkeypatch.setattr(os, "access", lambda p, m: access)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout=run_out, stderr="", returncode=returncode))
    return _REAL_UID_STATE()


def test_uid_isolation_needs_a_setuid_root_launcher(monkeypatch):
    ok, why = _probe(monkeypatch, 0o100755)
    assert not ok and "setuid root" in why
    ok, why = _probe(monkeypatch, 0o104750, uid=1000)
    assert not ok and "setuid root" in why


def test_uid_isolation_refuses_a_launcher_anyone_can_run(monkeypatch):
    ok, why = _probe(monkeypatch, 0o104755)
    assert not ok and "everyone" in why


def test_uid_isolation_is_proven_by_running_it(monkeypatch):
    ok, why = _probe(monkeypatch, 0o104750)
    assert ok and "10001" in why


def test_uid_isolation_fails_if_the_drop_did_not_happen(monkeypatch):
    ok, why = _probe(monkeypatch, 0o104750, run_out="0 0 3\n")
    assert not ok and "did not drop privileges" in why


def test_uid_isolation_fails_closed_if_romarr_cannot_execute_the_launcher(monkeypatch):
    ok, why = _probe(monkeypatch, 0o104750, access=False)
    assert not ok and "not executable by ROMarr" in why


_BOOT = """
import os, sys, types
sys.path.insert(0, {runtime!r})
os.environ.update(ROMARR_HUB_ISOLATION="uid", ROMARR_HUB_PROTECT={state!r},
                  ROMARR_HUB_PLUGIN_DIR="/x", ROMARR_HUB_SCRATCH="/y")
sb = types.ModuleType("rom_hub.sandbox")
class SandboxUnavailable(Exception):
    pass
sb.SandboxUnavailable = SandboxUnavailable
sb.install = lambda: "installed"
root = types.ModuleType("rom_hub")
root.sandbox = sb
sys.modules["rom_hub"] = root
sys.modules["rom_hub.sandbox"] = sb
sg = types.ModuleType("syscall_guard")
sg.install = lambda: None
sys.modules["syscall_guard"] = sg
import sitecustomize
try:
    print("RESULT", sb.install())
except SandboxUnavailable as exc:
    print("RESULT refused", exc)
"""


def test_sitecustomize_fails_closed_unless_the_uid_boundary_holds(tmp_path):
    """In uid mode the child must not be root and must not read the state file.

    This test runs as root in some environments, which alone must make it refuse;
    as an ordinary user a readable state file must.
    """
    state = tmp_path / "romarr.json"
    state.write_text("{}")
    runtime = os.path.join(os.path.dirname(hub.__file__), "plugin_runtime")
    script = tmp_path / "boot.py"
    script.write_text(_BOOT.format(runtime=runtime, state=str(state)))
    out = subprocess.run([sys.executable, "-S", str(script)], capture_output=True,
                         text=True, timeout=30)
    assert "RESULT refused" in out.stdout, out.stdout + out.stderr


def test_hub_status_reports_the_isolation_in_force(monkeypatch, tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from romarr.app import ROMarr, make_handler
    svc = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json"), "ROMARR_API_KEY": "k"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        def status():
            req = urllib.request.Request(
                f"http://127.0.0.1:{httpd.server_address[1]}/api/v1/hub/status")
            req.add_header("X-Api-Key", "k")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        monkeypatch.setattr(hub, "sandbox_state", lambda: (True, "ok"))
        monkeypatch.setattr(hub, "_uid_mode", lambda: True)
        assert status()["isolation"] == "uid"
        monkeypatch.setattr(hub, "_uid_mode", lambda: False)
        assert status()["isolation"] == "landlock"
        monkeypatch.setattr(hub, "sandbox_state", lambda: (False, "nothing works"))
        assert status()["isolation"] == "none"
    finally:
        httpd.shutdown()
        httpd.server_close()
