"""GET/PUT /api/v1/config must never return a credential."""

from __future__ import annotations

from romarr.app import MASKED_ITEM_FIELDS, SECRET_MASK
from romarr.app import mask_item


def test_mask_item_masks_only_declared_fields():
    item = {"id": "1", "name": "IGDB", "client_id": "abc", "token": "tok", "enable": True}
    got = mask_item(item, MASKED_ITEM_FIELDS["metadata_providers"])
    assert got["token"] == SECRET_MASK and got["client_id"] == SECRET_MASK
    assert got["name"] == "IGDB" and got["enable"] is True


def test_empty_secret_stays_empty_not_masked():
    got = mask_item({"token": ""}, ("token",))
    assert got["token"] == ""


def test_notification_urls_are_secrets():
    assert "url" in MASKED_ITEM_FIELDS["connections"]
