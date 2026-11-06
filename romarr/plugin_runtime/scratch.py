"""Find a finite tmpfs for short-lived Hub plugin scratch data."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _unescape_mount_path(value: str) -> str:
    return (value.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def _mounted_tmpfs(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        mounts = Path("/proc/self/mounts").read_text(encoding="utf-8")
    except OSError:
        return False
    candidates = []
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mountpoint = Path(_unescape_mount_path(fields[1]))
        if (resolved == mountpoint or mountpoint in resolved.parents):
            candidates.append((len(mountpoint.parts), fields[2]))
    if not candidates:
        return False
    return max(candidates)[1] == "tmpfs"


def tmpfs_root() -> Path:
    """Return a writable tmpfs path or fail closed when none is mounted."""
    candidates = []
    try:
        candidates.append(Path(tempfile.gettempdir()))
    except Exception:  # noqa: BLE001 - fall back to the standard Linux paths
        pass
    candidates.extend((Path("/tmp"), Path("/dev/shm")))
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        if _mounted_tmpfs(resolved):
            try:
                stats = os.statvfs(resolved)
            except OSError:
                continue
            if stats.f_blocks > 0 and stats.f_frsize > 0:
                return resolved
    raise RuntimeError(
        "ROM Hub plugins require a finite tmpfs mount for their scratch files"
    )


def probe() -> tuple[bool, str]:
    try:
        root = tmpfs_root()
        stats = os.statvfs(root)
        capacity = stats.f_blocks * stats.f_frsize
        return True, f"bounded plugin scratch at {root} ({capacity} bytes)"
    except Exception as exc:  # noqa: BLE001 - shown in the Hub status row
        return False, str(exc) or exc.__class__.__name__
