"""Default-deny filesystem access for ROM Hub plugin subprocesses.

ROM Hub's seccomp boundary blocks network sockets and process execution, but
seccomp cannot restrict paths. Landlock adds that missing path-aware layer
without creating namespaces, which the deployed Docker profile does not allow.

Only the Python runtime, the installed plugin, verified data-asset files, and a
per-process scratch directory are reachable. Every other filesystem path is
denied by default. This module is loaded by the trusted plugin bootstrap before
ROM Hub imports any plugin code.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
import sysconfig
from pathlib import Path


_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

_EXECUTE = 1 << 0
_WRITE_FILE = 1 << 1
_READ_FILE = 1 << 2
_READ_DIR = 1 << 3
_REMOVE_DIR = 1 << 4
_REMOVE_FILE = 1 << 5
_MAKE_CHAR = 1 << 6
_MAKE_DIR = 1 << 7
_MAKE_REG = 1 << 8
_MAKE_SOCK = 1 << 9
_MAKE_FIFO = 1 << 10
_MAKE_BLOCK = 1 << 11
_MAKE_SYM = 1 << 12
_REFER = 1 << 13
_TRUNCATE = 1 << 14
_IOCTL_DEV = 1 << 15

_READ_ONLY = _EXECUTE | _READ_FILE | _READ_DIR
_WRITABLE = (
    _READ_ONLY | _WRITE_FILE | _REMOVE_DIR | _REMOVE_FILE | _MAKE_CHAR
    | _MAKE_DIR | _MAKE_REG | _MAKE_SOCK | _MAKE_FIFO | _MAKE_BLOCK
    | _MAKE_SYM | _REFER | _TRUNCATE | _IOCTL_DEV
)


class LandlockUnavailable(RuntimeError):
    """The kernel cannot enforce the requested filesystem policy."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
        ("reserved", ctypes.c_uint32),
    ]


def _syscall_numbers() -> tuple[int, int, int]:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "aarch64", "arm64"}:
        # Linux assigns the same Landlock syscall numbers on these ABIs.
        return 444, 445, 446
    raise LandlockUnavailable(
        f"Landlock syscall numbers are not configured for {machine or 'unknown'}"
    )


def _libc():
    if sys.platform != "linux" or not hasattr(os, "O_PATH"):
        raise LandlockUnavailable("Landlock requires Linux with O_PATH support")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def abi_version() -> int:
    """Return the kernel's Landlock ABI version, or raise if it is unavailable."""
    libc = _libc()
    create, _, _ = _syscall_numbers()
    version = libc.syscall(create, None, 0, _CREATE_RULESET_VERSION)
    if version < 1:
        error = ctypes.get_errno()
        raise LandlockUnavailable(
            f"Landlock is unavailable (errno {error})"
        )
    return int(version)


def probe() -> tuple[bool, str]:
    """Check kernel support without restricting the calling ROMarr process."""
    try:
        return True, f"Landlock ABI {abi_version()}"
    except Exception as exc:  # noqa: BLE001 - shown as an operator diagnostic
        return False, str(exc) or exc.__class__.__name__


def _runtime_paths() -> set[Path]:
    """Trusted interpreter paths required after the ruleset is installed."""
    paths: set[Path] = set()
    roots = set()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        value = sysconfig.get_paths().get(key)
        if value:
            path = Path(value)
            roots.add(path)
            if path.exists():
                paths.add(path.resolve())

    for value in sys.path:
        if not value:
            continue
        path = Path(value)
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if any(resolved == root or root in resolved.parents for root in roots):
            paths.add(resolved)
        elif resolved.suffix == ".zip" and resolved.name.startswith("python"):
            # CPython may place its stdlib archive beside the configured
            # stdlib directory rather than inside it.
            if any(str(resolved).startswith(str(root.parent)) for root in roots):
                paths.add(resolved)

    # Wheels may depend on system shared libraries outside Python's own
    # directories. These contain executable runtime code, not application
    # configuration or user data.
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64-linux-gnu", "amd64": "x86_64-linux-gnu",
            "aarch64": "aarch64-linux-gnu", "arm64": "aarch64-linux-gnu"}.get(machine)
    for value in ("/usr/lib", "/usr/local/lib", "/lib"):
        path = Path(value)
        if path.is_dir():
            paths.add(path.resolve())
    if arch:
        for value in (f"/usr/lib/{arch}", f"/lib/{arch}"):
            path = Path(value)
            if path.is_dir():
                paths.add(path.resolve())

    # Public trust roots and randomness devices are runtime inputs; private
    # keys and other files under /etc and /dev remain inaccessible.
    for value in ("/etc/ssl/certs/ca-certificates.crt", "/etc/localtime",
                  "/dev/null", "/dev/urandom", "/dev/random"):
        path = Path(value)
        if path.exists():
            paths.add(path.resolve())
    return paths


def _rights_for_abi(abi: int) -> int:
    rights = _WRITABLE
    if abi < 2:
        rights &= ~_REFER
    if abi < 3:
        rights &= ~_TRUNCATE
    if abi < 5:
        rights &= ~_IOCTL_DEV
    return rights


def _add_rule(libc, add_rule: int, ruleset_fd: int, path: Path,
              rights: int) -> None:
    try:
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except OSError as exc:
        raise LandlockUnavailable(
            f"cannot prepare filesystem rule for {path}: {exc}"
        ) from exc
    try:
        rule = _PathBeneathAttr(rights, fd, 0)
        result = libc.syscall(
            add_rule, ruleset_fd, _RULE_PATH_BENEATH,
            ctypes.byref(rule), 0,
        )
        if result != 0:
            error = ctypes.get_errno()
            raise LandlockUnavailable(
                f"cannot add filesystem rule for {path} (errno {error})"
            )
    finally:
        os.close(fd)


def _ancestors(path: Path) -> list[Path]:
    """Directories that must be traversable to reach a permitted path."""
    current = path if path.is_dir() else path.parent
    result = []
    while True:
        result.append(current)
        if current == current.parent:
            break
        current = current.parent
    return result


def install(plugin_dir: str | Path, asset_paths: list[str | Path],
            scratch_dir: str | Path) -> None:
    """Confine this subprocess to runtime, plugin, verified assets, and scratch."""
    libc = _libc()
    create, add_rule, restrict_self = _syscall_numbers()
    abi = abi_version()
    handled = _rights_for_abi(abi)
    runtime = _runtime_paths()

    try:
        plugin = Path(plugin_dir).resolve(strict=True)
        scratch = Path(scratch_dir).resolve(strict=True)
    except OSError as exc:
        raise LandlockUnavailable(f"plugin runtime path is unavailable: {exc}") from exc
    if not plugin.is_dir() or not scratch.is_dir():
        raise LandlockUnavailable("plugin and scratch paths must be directories")

    assets = []
    for value in asset_paths:
        try:
            asset = Path(value).resolve(strict=True)
        except OSError as exc:
            raise LandlockUnavailable(f"verified data asset is unavailable: {exc}") from exc
        if not asset.is_file():
            raise LandlockUnavailable("verified data assets must be regular files")
        assets.append(asset)

    all_paths = runtime | {plugin, scratch} | set(assets)
    traversal = set()
    for path in all_paths:
        traversal.update(_ancestors(path))
    attr = _RulesetAttr(handled)
    ruleset_fd = libc.syscall(create, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset_fd < 0:
        error = ctypes.get_errno()
        raise LandlockUnavailable(f"cannot create Landlock ruleset (errno {error})")

    try:
        for path in sorted(traversal, key=lambda item: len(item.parts)):
            _add_rule(libc, add_rule, ruleset_fd, path, _EXECUTE)
        for path in sorted(runtime):
            rights = _READ_ONLY if path.is_dir() else _READ_FILE
            _add_rule(libc, add_rule, ruleset_fd, path, rights)
        _add_rule(libc, add_rule, ruleset_fd, plugin,
                  _EXECUTE | _READ_FILE | _READ_DIR)
        for asset in assets:
            _add_rule(libc, add_rule, ruleset_fd, asset, _READ_FILE)
        _add_rule(libc, add_rule, ruleset_fd, scratch, _rights_for_abi(abi))

        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise LandlockUnavailable(
                f"PR_SET_NO_NEW_PRIVS failed (errno {error})"
            )
        result = libc.syscall(restrict_self, ruleset_fd, 0)
        if result != 0:
            error = ctypes.get_errno()
            raise LandlockUnavailable(
                f"cannot enforce Landlock ruleset (errno {error})"
            )
    finally:
        os.close(ruleset_fd)
