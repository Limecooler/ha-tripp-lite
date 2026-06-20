"""Tests for integration setup and services."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.tripp_lite_webcardlx as integration
from custom_components.tripp_lite_webcardlx.api import (
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXInvalidAuth,
)
from custom_components.tripp_lite_webcardlx.const import (
    ATTR_ACTION,
    ATTR_ALARM_IDS,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DELAY,
    ATTR_DEVICE_ID,
    ATTR_TOLERANCE,
    ATTR_VALUE,
    CONF_ALLOW_UNSUPPORTED_MODEL,
    CONF_URL,
    DOMAIN,
    LOAD_ACTION_OFF,
    LOAD_ACTION_ON,
    PLATFORMS,
)
from custom_components.tripp_lite_webcardlx.coordinator import WebcardLXRuntimeData


class SetupClient:
    """Fake setup client."""

    error: Exception | None = None
    last: SetupClient | None = None

    def __init__(self, session: object, base_url: str, username: str, password: str) -> None:
        """Initialize fake client."""
        self.base_url = base_url
        self.login_calls = 0
        self.logout_calls = 0
        self.__class__.last = self

    async def async_login(self) -> None:
        """Log in or raise."""
        self.login_calls += 1
        if self.error is not None:
            raise self.error

    async def async_logout(self) -> None:
        """Record logout."""
        self.logout_calls += 1


class SetupCoordinator:
    """Fake setup coordinator."""

    last: SetupCoordinator | None = None
    fail_refresh = False

    def __init__(self, hass: HomeAssistant, entry: MockConfigEntry, client: SetupClient) -> None:
        """Initialize fake coordinator."""
        self.hass = hass
        self.config_entry = entry
        self.client = client
        self.data = {"devices": {"1": {"device_id": 1, "serial_number": "SERIAL"}}}
        self.listeners: list[Any] = []
        self.refreshed = False
        self.__class__.last = self

    async def async_config_entry_first_refresh(self) -> None:
        """Record refresh."""
        self.refreshed = True
        if self.fail_refresh:
            raise RuntimeError("boom")

    def async_add_listener(self, listener: Any) -> Any:
        """Register listener."""
        self.listeners.append(listener)
        return lambda: None


class ServiceClient:
    """Fake service client."""

    def __init__(self) -> None:
        """Initialize fake client."""
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail = False
        self.logout_calls = 0

    async def _record(self, name: str, *args: Any) -> None:
        """Record a call or fail."""
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append((name, args))

    async def async_execute_main_load(self, *args: Any) -> None:
        """Record main load action."""
        await self._record("main_load", *args)

    async def async_execute_load(self, *args: Any) -> None:
        """Record load action."""
        await self._record("load", *args)

    async def async_control_device(self, *args: Any) -> None:
        """Record device action."""
        await self._record("device", *args)

    async def async_acknowledge_alarms(self, *args: Any) -> None:
        """Record alarm action."""
        await self._record("ack_alarms", *args)

    async def async_acknowledge_all_alarms(self) -> None:
        """Record all-alarm action."""
        await self._record("ack_all")

    async def async_update_variable(self, *args: Any) -> None:
        """Record variable update."""
        await self._record("variable", *args)

    async def async_update_device(self, *args: Any) -> None:
        """Record device update."""
        await self._record("device_update", *args)

    async def async_logout(self) -> None:
        """Record logout."""
        self.logout_calls += 1


class ServiceCoordinator:
    """Fake service coordinator."""

    def __init__(self, client: ServiceClient) -> None:
        """Initialize coordinator data."""
        self.client = client
        self.refreshes = 0
        self.data = {
            "devices": {"1": {"device_id": 1, "serial_number": "SERIAL"}},
            "loads": {
                "1:1": {
                    "id": "1",
                    "device_id": 1,
                    "name": "Load 1",
                    "load_number": 1,
                    "controllable": True,
                },
                "1:main": {
                    "id": "main",
                    "device_id": 1,
                    "name": "Main",
                    "load_number": 0,
                    "controllable": True,
                },
            },
            "variables": {
                "1:4": {
                    "id": "4",
                    "device_id": 1,
                    "label": "Low Battery Threshold",
                    "value": "20",
                    "editable": True,
                    "numeric": True,
                }
            },
            "actions_supported": {
                "load_action_supported": {"supported_on_set": True},
                "turn_on_device_supported": {"supported_on_set": True, "devices": [{"id": 1}]},
            },
            "alarms": {"a1": {"id": "a1"}},
        }

    async def async_request_refresh(self) -> None:
        """Record refresh."""
        self.refreshes += 1


@pytest.fixture(autouse=True)
def reset_fakes() -> None:
    """Reset fake class state."""
    SetupClient.error = None
    SetupClient.last = None
    SetupCoordinator.last = None
    SetupCoordinator.fail_refresh = False


def _entry(
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    *,
    version: int = 1,
    minor_version: int = 2,
) -> MockConfigEntry:
    """Create a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="entry",
        data=data
        or {
            CONF_URL: "https://ups.local",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
            CONF_VERIFY_SSL: False,
        },
        options=options or {},
        version=version,
        minor_version=minor_version,
    )


async def test_async_setup_registers_services(hass: HomeAssistant) -> None:
    """Test integration setup registers services."""
    assert await integration.async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, integration.SERVICE_EXECUTE_LOAD_ACTION)
    integration.async_register_services(hass)


async def test_migrate_entry_moves_options(hass: HomeAssistant) -> None:
    """Test config entry migration."""
    entry = _entry(
        {
            CONF_URL: "https://ups.local",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
            CONF_SCAN_INTERVAL: 45,
            CONF_ALLOW_UNSUPPORTED_MODEL: True,
        },
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    assert await integration.async_migrate_entry(hass, entry)
    assert CONF_SCAN_INTERVAL not in entry.data
    assert entry.options[CONF_SCAN_INTERVAL] == 45
    assert entry.options[CONF_ALLOW_UNSUPPORTED_MODEL] is True

    current_entry = _entry()
    current_entry.add_to_hass(hass)
    assert await integration.async_migrate_entry(hass, current_entry)

    future_entry = _entry(version=2)
    future_entry.add_to_hass(hass)
    assert not await integration.async_migrate_entry(hass, future_entry)


async def test_setup_entry_success_and_failure_cleanup(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test setup success and cleanup on failure."""
    monkeypatch.setattr(integration, "WebcardLXClient", SetupClient)
    monkeypatch.setattr(integration, "WebcardLXDataUpdateCoordinator", SetupCoordinator)
    monkeypatch.setattr(integration, "async_get_clientsession", lambda *args, **kwargs: "session")

    forwarded: list[tuple[Any, Any]] = []

    async def forward(entry: Any, platforms: Any) -> None:
        forwarded.append((entry, platforms))

    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", forward)

    entry = _entry()
    entry.add_to_hass(hass)
    assert await integration.async_setup_entry(hass, entry)
    assert SetupClient.last is not None
    assert SetupClient.last.login_calls == 1
    assert SetupCoordinator.last is not None
    assert SetupCoordinator.last.refreshed is True
    assert forwarded == [(entry, PLATFORMS)]

    SetupClient.error = WebcardLXInvalidAuth("bad")
    with pytest.raises(ConfigEntryAuthFailed):
        await integration.async_setup_entry(hass, _entry())

    SetupClient.error = WebcardLXCannotConnect("down")
    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, _entry())

    SetupClient.error = None
    SetupCoordinator.fail_refresh = True
    fail_entry = _entry()
    with pytest.raises(RuntimeError):
        await integration.async_setup_entry(hass, fail_entry)
    assert SetupClient.last is not None
    assert SetupClient.last.logout_calls == 1
    assert getattr(fail_entry, "runtime_data", None) is None

    SetupCoordinator.fail_refresh = False

    async def forward_failed(entry_arg: Any, platforms: Any) -> None:
        raise RuntimeError("forward failed")

    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", forward_failed)
    forward_fail_entry = _entry()
    with pytest.raises(RuntimeError):
        await integration.async_setup_entry(hass, forward_fail_entry)
    assert getattr(forward_fail_entry, "runtime_data", None) is None


async def test_target_based_services(hass: HomeAssistant) -> None:
    """Test services resolve HA targets and validate current coordinator data."""
    await integration.async_setup(hass, {})
    entry = _entry()
    entry.add_to_hass(hass)
    client = ServiceClient()
    coordinator = ServiceCoordinator(client)
    entry.runtime_data = WebcardLXRuntimeData(client=client, coordinator=coordinator)

    device_registry = dr.async_get(hass)
    ha_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "entry_1"), (DOMAIN, "SERIAL")},
    )
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        "entry_1_load_1_switch",
        suggested_object_id="load_1",
        config_entry=entry,
        device_id=ha_device.id,
    )
    entity_registry.async_get_or_create(
        "number",
        DOMAIN,
        "entry_1_variable_4_number",
        suggested_object_id="low_battery_threshold",
        config_entry=entry,
        device_id=ha_device.id,
    )

    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_EXECUTE_LOAD_ACTION,
        {ATTR_ENTITY_ID: "switch.load_1", ATTR_ACTION: "off"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_EXECUTE_DEVICE_ACTION,
        {ATTR_DEVICE_ID: [ha_device.id], ATTR_ACTION: "turn_on", ATTR_DELAY: 7},
        blocking=True,
    )
    assert integration._device_targets_from_call(
        hass,
        SimpleNamespace(data={ATTR_ENTITY_ID: "switch.load_1"}),
    ) == [(entry.runtime_data, "1")]
    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_SET_VARIABLE,
        {ATTR_ENTITY_ID: "number.low_battery_threshold", ATTR_VALUE: 42, ATTR_TOLERANCE: 0.5},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_ACKNOWLEDGE_ALARMS,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_ALARM_IDS: ["a1"]},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_ACKNOWLEDGE_ALL_ALARMS,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_UPDATE_DEVICE_PROPERTIES,
        {"name": "Rack UPS"},
        target={ATTR_DEVICE_ID: [ha_device.id]},
        blocking=True,
    )

    assert ("load", ("1", "1", LOAD_ACTION_OFF)) in client.calls
    assert ("device", ("turn_on", "1", 7, 7)) in client.calls
    assert ("variable", ("4", 42.0, 0.5)) in client.calls
    assert ("ack_alarms", (["a1"],)) in client.calls
    assert ("ack_all", ()) in client.calls
    assert ("device_update", ("1", {"name": "Rack UPS"})) in client.calls
    assert coordinator.refreshes == 6

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            integration.SERVICE_ACKNOWLEDGE_ALARMS,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_ALARM_IDS: ["missing"]},
            blocking=True,
        )


async def test_unload_reload_and_stale_device_cleanup(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test unload/reload hooks and stale device cleanup."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = ServiceClient()
    coordinator = ServiceCoordinator(client)
    entry.runtime_data = WebcardLXRuntimeData(client=client, coordinator=coordinator)

    async def unload_platforms(entry_arg: Any, platforms: Any) -> bool:
        assert entry_arg is entry
        assert platforms == PLATFORMS
        return True

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", unload_platforms)

    assert await integration.async_unload_entry(hass, entry)
    assert client.logout_calls == 1

    # Test that cancel_stale_listener is called before platform unload.
    cancelled: list[bool] = []
    entry.runtime_data = WebcardLXRuntimeData(client=client, coordinator=coordinator)
    entry.runtime_data.cancel_stale_listener = lambda: cancelled.append(True)
    assert await integration.async_unload_entry(hass, entry)
    assert cancelled == [True]
    assert client.logout_calls == 2

    entry.runtime_data = WebcardLXRuntimeData(client=client, coordinator=coordinator)

    async def unload_platforms_failed(entry_arg: Any, platforms: Any) -> bool:
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", unload_platforms_failed)
    assert not await integration.async_unload_entry(hass, entry)
    assert client.logout_calls == 2

    reloaded: list[str] = []

    async def reload_entry(entry_id: str) -> None:
        reloaded.append(entry_id)

    monkeypatch.setattr(hass.config_entries, "async_reload", reload_entry)
    await integration._async_reload_entry(hass, entry)
    assert reloaded == [entry.entry_id]

    device_registry = dr.async_get(hass)
    valid = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "entry_1")},
    )
    child = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "entry_1_load_1")},
    )
    stale = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "stale")},
    )

    await integration._async_remove_stale_devices(hass, entry, coordinator)

    assert device_registry.async_get(valid.id) is not None
    assert device_registry.async_get(child.id) is not None
    assert device_registry.async_get(stale.id) is None

    preserved = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "preserved")},
    )
    coordinator._optional_failures = {"loads"}
    await integration._async_remove_stale_devices(hass, entry, coordinator)
    assert device_registry.async_get(preserved.id) is not None


async def test_service_validation_and_error_branches(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test service target validation and sanitized error wrapping."""
    await integration.async_setup(hass, {})
    entry = _entry()
    entry.add_to_hass(hass)
    client = ServiceClient()
    coordinator = ServiceCoordinator(client)
    entry.runtime_data = WebcardLXRuntimeData(client=client, coordinator=coordinator)
    runtime_data = entry.runtime_data
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="other",
        entry_id="other",
        data={},
    )
    other_entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    ha_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "entry_1")},
    )
    orphan_device = device_registry.async_get_or_create(
        config_entry_id="other",
        identifiers={(DOMAIN, "orphan")},
    )
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        "entry_1_load_1_switch",
        suggested_object_id="load_1",
        config_entry=entry,
    )
    entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        "entry_1_load_main_switch",
        suggested_object_id="main_load",
        config_entry=entry,
    )
    entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        "entry_1_load_missing_switch",
        suggested_object_id="missing_load",
        config_entry=entry,
    )
    entity_registry.async_get_or_create(
        "number",
        DOMAIN,
        "entry_1_variable_4_number",
        suggested_object_id="low_battery_threshold",
        config_entry=entry,
    )
    entity_registry.async_get_or_create(
        "number",
        DOMAIN,
        "entry_1_variable_missing_number",
        suggested_object_id="missing_variable",
        config_entry=entry,
    )

    await hass.services.async_call(
        DOMAIN,
        integration.SERVICE_EXECUTE_LOAD_ACTION,
        {ATTR_ENTITY_ID: "switch.main_load", ATTR_ACTION: "on"},
        blocking=True,
    )
    assert ("main_load", ("1", LOAD_ACTION_ON)) in client.calls

    coordinator.data["loads"]["1:1"]["controllable"] = False
    coordinator.data["actions_supported"]["load_action_supported"] = {"supported_on_set": False}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            integration.SERVICE_EXECUTE_LOAD_ACTION,
            {ATTR_ENTITY_ID: "switch.load_1", ATTR_ACTION: "off"},
            blocking=True,
        )
    coordinator.data["loads"]["1:1"]["controllable"] = True
    coordinator.data["actions_supported"]["load_action_supported"] = {"supported_on_set": True}

    coordinator.data["actions_supported"]["turn_on_device_supported"] = {"supported_on_set": False}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            integration.SERVICE_EXECUTE_DEVICE_ACTION,
            {ATTR_DEVICE_ID: [ha_device.id], ATTR_ACTION: "turn_on", ATTR_DELAY: 0},
            blocking=True,
        )
    coordinator.data["actions_supported"]["turn_on_device_supported"] = {
        "supported_on_set": True,
        "devices": [{"id": 1}],
    }

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            integration.SERVICE_UPDATE_DEVICE_PROPERTIES,
            {ATTR_DEVICE_ID: [ha_device.id]},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            integration.SERVICE_ACKNOWLEDGE_ALL_ALARMS,
            {ATTR_CONFIG_ENTRY_ID: "missing"},
            blocking=True,
        )

    with pytest.raises(ServiceValidationError):
        await integration._load_targets_from_call(
            hass,
            SimpleNamespace(data={ATTR_ENTITY_ID: "sensor.bad"}),
        )
    with pytest.raises(ServiceValidationError):
        await integration._load_targets_from_call(
            hass,
            SimpleNamespace(data={}),
        )
    with pytest.raises(ServiceValidationError):
        await integration._load_targets_from_call(
            hass,
            SimpleNamespace(data={ATTR_ENTITY_ID: "switch.missing_load"}),
        )
    with pytest.raises(ServiceValidationError):
        await integration._variable_targets_from_call(
            hass,
            SimpleNamespace(data={ATTR_ENTITY_ID: "sensor.bad"}),
        )
    with pytest.raises(ServiceValidationError):
        await integration._variable_targets_from_call(
            hass,
            SimpleNamespace(data={}),
        )
    with pytest.raises(ServiceValidationError):
        await integration._variable_targets_from_call(
            hass,
            SimpleNamespace(data={ATTR_ENTITY_ID: "number.missing_variable"}),
        )
    with pytest.raises(ServiceValidationError):
        integration._device_targets_from_call(
            hass,
            SimpleNamespace(data={ATTR_DEVICE_ID: ["missing-device"]}),
        )
    with pytest.raises(ServiceValidationError):
        integration._device_targets_from_call(
            hass,
            SimpleNamespace(data={}),
        )
    with pytest.raises(ServiceValidationError):
        integration._device_targets_from_call(
            hass,
            SimpleNamespace(data={ATTR_DEVICE_ID: [orphan_device.id]}),
        )
    with pytest.raises(ServiceValidationError):
        integration._runtime_data_from_entity_entry(
            hass,
            SimpleNamespace(config_entry_id="missing"),
        )

    assert (
        integration._load_from_unique_id(runtime_data, "entry", "entry_1_load_absent_switch")
        is None
    )
    coordinator.data["variables"]["1:9"] = {
        "id": "9",
        "device_id": 1,
        "label": "Secret",
        "editable": True,
        "password": True,
    }
    assert (
        integration._variable_from_unique_id(
            runtime_data,
            "entry",
            "entry_1_variable_9_number",
            "number",
        )
        is None
    )

    with pytest.raises(ServiceValidationError):
        integration._validated_variable_value("select", {"enum_values": ["A"]}, "B")
    assert integration._validated_variable_value("select", {"enum_values": ["A"]}, "A") == "A"
    with pytest.raises(ServiceValidationError):
        integration._validated_variable_value("number", {}, "bad")
    assert integration._validated_variable_value("number", {}, "1.5") == 1.5
    with pytest.raises(ServiceValidationError):
        integration._validated_variable_value("switch", {}, "maybe")
    assert integration._validated_variable_value("switch", {}, "on") == "true"
    assert integration._validated_variable_value("text", {}, 123) == "123"

    original_get_entry = hass.config_entries.async_get_entry
    monkeypatch.setattr(hass.config_entries, "async_get_entry", lambda entry_id: None)
    assert integration._entry_from_id(hass, entry.entry_id) is entry
    assert integration._entry_from_id(hass, "missing") is None
    monkeypatch.setattr(hass.config_entries, "async_get_entry", original_get_entry)

    async def raise_api(call: Any) -> None:
        raise WebcardLXApiError(500, "raw response body")

    async def raise_generic(call: Any) -> None:
        raise RuntimeError("boom")

    with pytest.raises(ServiceValidationError) as api_error:
        await integration._wrap_service_errors(raise_api)(SimpleNamespace(data={}))
    assert api_error.value.translation_placeholders == {"error": "WebcardLX API error 500"}

    with pytest.raises(ServiceValidationError) as generic_error:
        await integration._wrap_service_errors(raise_generic)(SimpleNamespace(data={}))
    assert generic_error.value.translation_placeholders == {"error": "boom"}
