"""Tests for the WebcardLX data coordinator."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tripp_lite_webcardlx.api import (
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXInvalidAuth,
    WebcardLXUnsupportedModel,
)
from custom_components.tripp_lite_webcardlx.const import DOMAIN
from custom_components.tripp_lite_webcardlx.coordinator import WebcardLXDataUpdateCoordinator


class FakeClient:
    """Fake API client for coordinator tests."""

    def __init__(self) -> None:
        self.devices = [
            {"device_id": 1, "model": "SU1000XLA", "serial_number": "SERIAL"},
            {"device_id": 2, "model": "SMART1500"},
        ]
        self.variables = [
            {
                "id": "1",
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Battery",
                "value": "100",
            },
            {
                "id": "2",
                "device_id": 2,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Other",
                "value": "1",
            },
            {"id": "3", "device_id": 1, "password": True, "value": "secret"},
            {"id": "4", "device_id": 1, "label": "API Token", "value": "secret"},
        ]
        self.control_variables = [{"id": "1", "device_id": 1, "editable": True}]
        self.loads = [
            {"id": "1", "device_id": 1, "device_type": "DEVICE_TYPE_UPS"},
            {"id": "2", "device_id": 2, "device_type": "DEVICE_TYPE_UPS"},
            {"id": "3", "device_id": 1, "device_type": "DEVICE_TYPE_PDU"},
            {"device_id": 1, "device_type": "DEVICE_TYPE_UPS"},
        ]
        self.load_groups = [{"id": "g1", "device_id": 1}, {"id": "g2", "device_id": 2}, {}]
        self.actions_supported = {"turn_on_device_supported": {"supported_on_set": True}}
        self.schedules_supported = {"scheduling_supported": True}
        self.alarm_summary = {"total_alarm_count": 1}
        self.alarms = [{"id": "a1"}, {"id": ""}, {"no": "id"}]
        self.events = [{"id": "e1"}, {"id": None}, {"no": "id"}]
        self.ready = {"ready": True}
        self.system_details = {"firmware_version": "1.0"}
        self.system_uptime = {"system_uptime": "5"}
        self.error: Exception | None = None
        self.optional_errors: dict[str, Exception] = {}

    async def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def async_get_devices(self) -> list[dict[str, object]]:
        await self._maybe_raise()
        return self.devices

    async def async_get_variables(self) -> list[dict[str, object]]:
        return self.variables

    async def async_get_control_variables(self) -> list[dict[str, object]]:
        return self.control_variables

    async def async_get_loads(self) -> list[dict[str, object]]:
        if "loads" in self.optional_errors:
            raise self.optional_errors["loads"]
        return self.loads

    async def async_get_load_groups(self) -> list[dict[str, object]]:
        return self.load_groups

    async def async_get_supported_actions(self) -> dict[str, object]:
        if "actions_supported" in self.optional_errors:
            raise self.optional_errors["actions_supported"]
        return self.actions_supported

    async def async_get_supported_schedules(self) -> dict[str, object]:
        return self.schedules_supported

    async def async_get_alarm_summary(self) -> dict[str, object]:
        return self.alarm_summary

    async def async_get_alarms(self) -> list[dict[str, object]]:
        return self.alarms

    async def async_get_events(self) -> list[dict[str, object]]:
        if "events" in self.optional_errors:
            raise self.optional_errors["events"]
        return self.events

    async def async_get_ready(self) -> dict[str, object]:
        return self.ready

    async def async_get_system_details(self) -> dict[str, object]:
        return self.system_details

    async def async_get_system_uptime(self) -> dict[str, object]:
        return self.system_uptime


def make_coordinator(
    hass: HomeAssistant,
    client: FakeClient,
    data: dict[str, object] | None = None,
    options: dict[str, object] | None = None,
) -> WebcardLXDataUpdateCoordinator:
    """Create a coordinator with a real HA config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data or {"scan_interval": 45},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return WebcardLXDataUpdateCoordinator(hass, entry, client)


async def test_fetch_data_filters_and_merges_supported_ups_data(hass: HomeAssistant) -> None:
    """Test normalized coordinator payload."""
    client = FakeClient()
    coordinator = make_coordinator(hass, client)

    data = await coordinator._async_fetch_data()

    assert coordinator.update_interval.total_seconds() == 45
    assert set(data["devices"]) == {"1"}
    assert data["variables"]["1:1"]["editable"] is True
    assert "2:2" not in data["variables"]
    assert "1:3" not in data["variables"]
    assert "1:4" not in data["variables"]
    assert set(data["loads"]) == {"1:1"}
    assert set(data["load_groups"]) == {"1:g1"}
    assert set(data["alarms"]) == {"a1"}
    assert set(data["events"]) == {"e1"}
    assert data["actions_supported"] == client.actions_supported
    assert data["schedules_supported"] == client.schedules_supported
    assert data["ready"] == {"ready": True}
    assert data["system_details"] == {"firmware_version": "1.0"}
    assert data["system_uptime"] == {"system_uptime": "5"}


async def test_fetch_data_can_allow_unsupported_model_fallback(hass: HomeAssistant) -> None:
    """Test that any UPS device is accepted regardless of model."""
    client = FakeClient()
    client.devices = [{"device_id": 8, "model": "SMART1500"}]
    client.variables = [{"id": "8", "device_id": 8, "device_type": "DEVICE_TYPE_UPS"}]
    client.control_variables = []
    client.loads = []
    client.load_groups = []
    coordinator = make_coordinator(hass, client)

    data = await coordinator._async_fetch_data()

    assert set(data["devices"]) == {"8"}
    assert set(data["variables"]) == {"8:8"}


async def test_fetch_data_rejects_unsupported_models(hass: HomeAssistant) -> None:
    """Test unsupported model protection."""
    client = FakeClient()
    client.devices = [{"device_id": 8, "model": "SMART1500"}]
    client.variables = []
    coordinator = make_coordinator(hass, client)

    with pytest.raises(WebcardLXUnsupportedModel):
        await coordinator._async_fetch_data()


async def test_update_data_success_and_error_paths(hass: HomeAssistant) -> None:
    """Test update exception translation."""
    client = FakeClient()
    coordinator = make_coordinator(hass, client)
    coordinator._was_unavailable = True

    assert await coordinator._async_update_data()
    assert coordinator._was_unavailable is False

    client.error = WebcardLXInvalidAuth("bad")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    client.error = WebcardLXCannotConnect("down")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator._was_unavailable is True

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    client.error = WebcardLXUnsupportedModel(["SMART1500"])
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    client.error = WebcardLXApiError(500, "raw body")
    with pytest.raises(UpdateFailed) as api_error:
        await coordinator._async_update_data()
    assert str(api_error.value) == "WebcardLX API error 500"


async def test_optional_endpoint_failure_and_recovery(hass: HomeAssistant) -> None:
    """Test optional endpoint failures return defaults and recover."""
    client = FakeClient()
    client.optional_errors = {
        "loads": WebcardLXCannotConnect("down"),
        "actions_supported": WebcardLXApiError(403, "forbidden"),
        "events": WebcardLXApiError(500, "bad"),
    }
    coordinator = make_coordinator(hass, client)

    data = await coordinator._async_fetch_data()

    assert data["loads"] == {}
    assert data["actions_supported"] == {}
    assert data["events"] == {}
    assert coordinator._optional_failures == {"loads", "actions_supported", "events"}

    client.optional_errors = {}
    coordinator._next_static_refresh = 0
    coordinator._next_events_refresh = 0
    data = await coordinator._async_fetch_data()

    assert set(data["loads"]) == {"1:1"}
    assert data["actions_supported"] == client.actions_supported
    assert set(data["events"]) == {"e1"}
    assert coordinator._optional_failures == set()

    client.optional_errors = {"loads": WebcardLXCannotConnect("down")}
    data = await coordinator._async_fetch_data()

    assert set(data["loads"]) == {"1:1"}
    assert coordinator._optional_failures == {"loads"}

    async def invalid_auth() -> None:
        raise WebcardLXInvalidAuth("bad")

    with pytest.raises(WebcardLXInvalidAuth):
        await coordinator._async_optional("auth", invalid_auth, {})
