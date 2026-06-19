"""Tests for diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.const import CONF_PASSWORD

from custom_components.tripp_lite_webcardlx.const import DOMAIN
from custom_components.tripp_lite_webcardlx.coordinator import WebcardLXRuntimeData
from custom_components.tripp_lite_webcardlx.diagnostics import async_get_config_entry_diagnostics


async def test_config_entry_diagnostics_redacts_sensitive_data() -> None:
    """Test diagnostics payload redaction."""
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={
            "access_token": "token",
            "nested": {
                "Authorization": "Bearer token",
                "serial_number": "SERIAL",
                "value": "safe",
            },
            "variables": {
                "1:1": {
                    "label": "API Token",
                    "value": "secret-token",
                    "raw_value": "secret-token",
                }
            },
            "events": [{"message": "raw alarm text", "value": "safe"}],
        },
    )
    entry = SimpleNamespace(
        data={CONF_PASSWORD: "secret", "url": "https://ups.local"},
        runtime_data=WebcardLXRuntimeData(client=SimpleNamespace(), coordinator=coordinator),
    )

    diagnostics = await async_get_config_entry_diagnostics(SimpleNamespace(), entry)

    assert diagnostics["domain"] == DOMAIN
    assert diagnostics["entry"][CONF_PASSWORD] == "**REDACTED**"
    assert diagnostics["entry"]["url"] == "**REDACTED**"
    assert diagnostics["last_update_success"] is True
    assert diagnostics["data"]["access_token"] == "**REDACTED**"
    assert diagnostics["data"]["nested"]["Authorization"] == "**REDACTED**"
    assert diagnostics["data"]["nested"]["serial_number"] == "**REDACTED**"
    assert diagnostics["data"]["nested"]["value"] == "safe"
    assert diagnostics["data"]["variables"]["1:1"]["value"] == "**REDACTED**"
    assert diagnostics["data"]["variables"]["1:1"]["raw_value"] == "**REDACTED**"
    assert diagnostics["data"]["events"][0]["message"] == "**REDACTED**"
    assert diagnostics["data"]["events"][0]["value"] == "safe"
