"""Diagnostics support for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_URL, DOMAIN
from .coordinator import WebcardLXRuntimeData
from .helpers import is_sensitive_attributes

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_URL,
    "access_token",
    "refresh_token",
    "Authorization",
    "authorization",
    "configured_asset_tag",
    "configured_device_id",
    "contact",
    "email",
    "event_text",
    "location",
    "mac",
    "mac_address",
    "message",
    "phone",
    "serial",
    "serial_number",
    "text",
    "url",
    "username",
}

VALUE_KEYS_TO_REDACT = {
    "current_value",
    "default_value",
    "new_value",
    "raw_value",
    "value",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    return {
        "domain": DOMAIN,
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "last_update_success": runtime_data.coordinator.last_update_success,
        "data": async_redact_data(
            _redact_sensitive_resource_values(runtime_data.coordinator.data),
            TO_REDACT,
        ),
    }


def _redact_sensitive_resource_values(value: Any) -> Any:
    """Redact generic value fields when surrounding attributes are sensitive."""
    if isinstance(value, Mapping):
        sensitive = is_sensitive_attributes(value)
        return {
            key: (
                "**REDACTED**"
                if sensitive and str(key) in VALUE_KEYS_TO_REDACT
                else _redact_sensitive_resource_values(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_resource_values(item) for item in value]
    return value
