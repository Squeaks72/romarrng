"""Landlock filesystem confinement is enforced inside the plugin child."""

from __future__ import annotations

import os
import subprocess
import sys
import importlib.util

import pytest

from romarr.plugin_runtime.landlock import probe
from romarr.plugin_runtime.scratch import probe as probe_scratch, tmpfs_root


def test_plugin_scratch_uses_a_finite_tmpfs():
    supported, detail = probe_scratch()
    assert supported, detail
    root = tmpfs_root()
    assert root.is_dir()


def test_plugin_child_reads_only_plugin_assets_and_private_scratch(tmp_path):
    supported, detail = probe()
    if not supported:
        pytest.skip(f"Landlock is unavailable: {detail}")

    plugin = tmp_path / "plugins" / "fixture"
    plugin.mkdir(parents=True)
    (plugin / "plugin.py").write_text("trusted plugin fixture", encoding="utf-8")
    asset = tmp_path / "verified-asset.bin"
    asset.write_bytes(b"verified asset")
    private = tmp_path / "host-config.json"
    private.write_text('{"secret":"host-only"}', encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)

    code = r'''
import os
from pathlib import Path
from romarr.plugin_runtime.landlock import install
plugin, asset, private, scratch = map(Path, os.environ["LANDLOCK_PATHS"].split("\n"))
install(plugin, [asset], scratch)
assert (plugin / "plugin.py").read_text() == "trusted plugin fixture"
assert asset.read_bytes() == b"verified asset"
(scratch / "result.txt").write_text("scratch is writable")
for path in (private, Path("/proc/self/environ")):
    try:
        path.read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError(f"host path remained readable: {path}")
try:
    (plugin / "plugin.py").write_text("modified")
except PermissionError:
    pass
else:
    raise AssertionError("installed plugin source remained writable")
'''
    env = os.environ.copy()
    env["LANDLOCK_PATHS"] = "\n".join(map(str, (plugin, asset, private, scratch)))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-c", code], cwd=os.getcwd(),
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (scratch / "result.txt").read_text() == "scratch is writable"


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or importlib.util.find_spec("pyseccomp") is None,
    reason="the metadata and process syscall guard requires Linux pyseccomp",
)
def test_plugin_syscall_guard_blocks_metadata_changes_and_process_forks(
    tmp_path,
):
    protected = tmp_path / "protected-config.json"
    protected.write_text("secret", encoding="utf-8")
    protected.chmod(0o600)
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)

    code = r'''
import ctypes, errno, os, threading
from pathlib import Path
from romarr.plugin_runtime.syscall_guard import install
protected, scratch = map(Path, os.environ["GUARD_PATHS"].split("\n"))
install()
for path, mode in ((protected, 0o644), (scratch, 0)):
    try:
        os.chmod(path, mode)
    except PermissionError as exc:
        assert exc.errno == errno.EPERM
    else:
        raise AssertionError(f"chmod succeeded for {path}")
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
ctypes.set_errno(0)
result = libc.syscall(452, -100, os.fsencode(protected), 0o644, 0)
if result == 0:
    raise AssertionError("fchmodat2 changed protected file permissions")
assert ctypes.get_errno() in (errno.EPERM, errno.ENOSYS), \
    f"fchmodat2 returned unexpected errno {ctypes.get_errno()}"

# io_uring can submit socket operations without calling socket/connect. Check
# all entry points so an inherited ring cannot be used to evade the boundary.
params = ctypes.create_string_buffer(120)
for number, args in (
    (425, (1, ctypes.byref(params))),
    (426, (-1, 0, 0, 0, None, 0)),
    (427, (-1, 0, None, 0)),
):
    ctypes.set_errno(0)
    result = libc.syscall(number, *args)
    if result >= 0:
        if number == 425:
            os.close(result)
        raise AssertionError(f"io_uring syscall {number} was allowed")
    assert ctypes.get_errno() in (errno.EPERM, errno.ENOSYS), \
        f"io_uring syscall {number} returned unexpected errno {ctypes.get_errno()}"
try:
    os.fork()
except OSError as exc:
    assert exc.errno == errno.EPERM
else:
    raise AssertionError("plugin created a child process")
completed = []
thread = threading.Thread(target=lambda: completed.append(True))
thread.start()
thread.join(timeout=2)
assert completed == [True], "ordinary threads must remain available"
'''
    env = os.environ.copy()
    env["GUARD_PATHS"] = f"{protected}\n{scratch}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-c", code], cwd=os.getcwd(),
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert protected.stat().st_mode & 0o777 == 0o600
    assert scratch.stat().st_mode & 0o777 == 0o700
