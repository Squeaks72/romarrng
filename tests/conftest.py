"""Shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_uid_isolation_by_default(monkeypatch):
    """The setuid plugin launcher exists only inside the built image.

    Tests that care about Landlock-less confinement turn it on explicitly; the
    rest must see the same "no helper" answer on a laptop and in the container.
    """
    from romarr import hub
    monkeypatch.setattr(hub, "uid_isolation_state",
                        lambda: (False, "plugin launcher is not installed"))
