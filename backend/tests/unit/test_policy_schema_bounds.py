"""Security review fix: policy import/values payloads are size-bounded."""

import msgspec
import pytest

from perevoditarr.modules.policy.schemas import (
    PolicyImportRequest,
    PolicyValuesRequest,
)


def _import_payload(preset_count: int) -> bytes:
    presets = [{"name": f"preset-{index}"} for index in range(preset_count)]
    return msgspec.json.encode({"schemaVersion": 1, "presets": presets})


def test_import_within_bounds_decodes() -> None:
    decoded = msgspec.json.decode(_import_payload(200), type=PolicyImportRequest)
    assert len(decoded.presets) == 200


def test_import_beyond_bounds_is_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        _ = msgspec.json.decode(_import_payload(201), type=PolicyImportRequest)


def test_language_lists_are_bounded() -> None:
    payload = msgspec.json.encode({"targetLanguages": ["da"] * 65})
    with pytest.raises(msgspec.ValidationError):
        _ = msgspec.json.decode(payload, type=PolicyValuesRequest)
