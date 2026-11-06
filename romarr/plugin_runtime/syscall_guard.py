"""Additional syscall restrictions for the ROM Hub plugin process."""

from __future__ import annotations

import errno


_CLONE_THREAD = 0x00010000
_RESTRICTED_METADATA_SYSCALLS = (
    "chmod", "fchmod", "fchmodat", "fchmodat2",
    "chown", "fchown", "lchown", "fchownat",
    "utime", "utimes", "futimesat", "utimensat",
    "setxattr", "lsetxattr", "fsetxattr",
    "removexattr", "lremovexattr", "fremovexattr",
)


def install() -> None:
    """Deny filesystem metadata changes and process creation by plugins.

    ROM Hub's own filter denies exec and network calls, but allows metadata
    syscalls and process creation. Landlock cannot restrict chmod, and a forked
    worker could outlive ROM Hub's direct child. This stacked filter keeps
    normal threads working while closing those two gaps.
    """
    try:
        import pyseccomp
    except Exception as exc:  # noqa: BLE001 - fail closed in the bootstrap
        raise RuntimeError("pyseccomp is unavailable for plugin syscall guard") from exc

    denied = pyseccomp.ERRNO(errno.EPERM)
    filter_ = pyseccomp.SyscallFilter(defaction=pyseccomp.ALLOW)
    added = set()
    for name in _RESTRICTED_METADATA_SYSCALLS:
        try:
            filter_.add_rule(denied, name)
        except (ValueError, RuntimeError):
            continue
        added.add(name)
    # libseccomp releases shipped with older distributions may not know the
    # Linux 6.5 fchmodat2 name yet. Its number is stable on the supported
    # x86_64 and aarch64 ABIs, so install the numeric rule in that case.
    if "fchmodat2" not in added:
        try:
            filter_.add_rule(denied, 452)
            added.add("fchmodat2")
        except Exception as exc:  # noqa: BLE001 - mode changes must fail closed
            raise RuntimeError("seccomp cannot deny fchmodat2") from exc
    if not {"chmod", "fchmod", "fchmodat", "fchmodat2"}.issubset(added):
        raise RuntimeError("seccomp cannot deny all chmod syscall variants")

    # glibc's fork() wrapper may use clone(2), and newer runtimes may try
    # clone3(2) first. Threads set CLONE_THREAD and remain in the plugin's
    # process; all other clone requests are denied. Returning ENOSYS for
    # clone3 makes libc fall back to the separately filtered clone(2) path.
    for name in ("fork", "vfork"):
        try:
            filter_.add_rule(denied, name)
        except (ValueError, RuntimeError):
            pass
    try:
        filter_.add_rule(
            denied, "clone",
            pyseccomp.Arg(0, pyseccomp.MASKED_EQ, _CLONE_THREAD, 0),
        )
    except Exception as exc:  # noqa: BLE001 - process creation must fail closed
        raise RuntimeError("seccomp cannot restrict non-thread clone calls") from exc
    try:
        filter_.add_rule(pyseccomp.ERRNO(errno.ENOSYS), "clone3")
    except (ValueError, RuntimeError):
        # clone3 has the same syscall number on the only supported ABIs
        # (x86_64 and aarch64); deny it even with older libseccomp tables.
        try:
            filter_.add_rule(pyseccomp.ERRNO(errno.ENOSYS), 435)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("seccomp cannot deny clone3") from exc

    # An io_uring ring can submit socket/connect operations without making the
    # corresponding direct syscalls. Deny its three entry points; these syscall
    # numbers are also stable on the supported x86_64 and aarch64 ABIs. Older
    # libseccomp tables may not include the names yet.
    for name, number in (
        ("io_uring_setup", 425),
        ("io_uring_enter", 426),
        ("io_uring_register", 427),
    ):
        try:
            filter_.add_rule(denied, name)
        except (ValueError, RuntimeError):
            try:
                filter_.add_rule(denied, number)
            except Exception as exc:  # noqa: BLE001 - network bypass must fail closed
                raise RuntimeError(f"seccomp cannot deny {name}") from exc

    try:
        filter_.load()
    except Exception as exc:  # noqa: BLE001 - bootstrap must refuse plugins
        raise RuntimeError("could not install the plugin syscall guard") from exc
