"""Tests for entity platforms."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tripp_lite_webcardlx import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
    text,
)
from custom_components.tripp_lite_webcardlx.const import (
    LOAD_ACTION_CYCLE,
    LOAD_ACTION_OFF,
    LOAD_ACTION_ON,
)
from custom_components.tripp_lite_webcardlx.coordinator import WebcardLXRuntimeData
from custom_components.tripp_lite_webcardlx.entity import WebcardLXEntity, device_connections


class FakeClient:
    """Fake WebcardLX client."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.fail = False
        self.base_url = "https://ups.local"

    async def _record(self, name: str, *args: object) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append((name, args))

    async def async_execute_main_load(self, *args: object) -> None:
        await self._record("main_load", *args)

    async def async_execute_load(self, *args: object) -> None:
        await self._record("load", *args)

    async def async_control_device(self, *args: object) -> None:
        await self._record("device", *args)

    async def async_acknowledge_all_alarms(self) -> None:
        await self._record("ack_all")

    async def async_update_variable(self, *args: object) -> None:
        await self._record("variable", *args)


class FakeCoordinator:
    """Fake coordinator."""

    def __init__(self) -> None:
        self.config_entry = SimpleNamespace(unique_id="entry")
        self.client = FakeClient()
        self.listeners: list[object] = []
        self.refreshes = 0
        self.last_update_success = True
        self.data = sample_data()

    def async_add_listener(self, listener: object) -> object:
        self.listeners.append(listener)
        return lambda: None

    async def async_request_refresh(self) -> None:
        self.refreshes += 1


class FakeEntry:
    """Fake config entry."""

    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.runtime_data = WebcardLXRuntimeData(coordinator.client, coordinator)
        self.unloads: list[object] = []

    def async_on_unload(self, callback: object) -> None:
        self.unloads.append(callback)


def sample_data() -> dict[str, object]:
    """Return representative coordinator data."""
    data = {
        "devices": {
            "1": {
                "device_id": 1,
                "name": "UPS",
                "manufacturer": "TRIPP LITE",
                "model": "SU1500RTXL2UA",
                "serial_number": "SERIAL",
                "protocol": "3015",
            },
            "2": {"device_id": 2, "name": "Unsupported peer"},
        },
        "variables": {
            "1": {
                "id": "1",
                "key": 100,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Battery Capacity",
                "value": "100",
                "raw_value": "100",
                "suffix": "%",
                "data_type": "VARTYPE_INTEGER",
                "purpose": "VARPURPOSE_STATUS",
                "group": "VARGROUP_BATTERY",
                "state": "DEVICE_STATE_NORMAL",
            },
            "2": {
                "id": "2",
                "key": 101,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Low Battery Alarm",
                "value": "false",
                "data_type": "VARTYPE_STRING",
                "purpose": "VARPURPOSE_STATUS",
                "group": "VARGROUP_BATTERY",
            },
            "3": {
                "id": "3",
                "key": 102,
                "device_id": 1,
                "label": "Audible Alarm",
                "value": "true",
                "editable": True,
                "data_type": "VARTYPE_STRING",
            },
            "4": {
                "id": "4",
                "key": 103,
                "device_id": 1,
                "label": "Low Battery Threshold",
                "value": "20",
                "editable": True,
                "numeric": True,
                "suffix": "%",
                "min_value": 0,
                "max_value": 100,
                "precision": 0,
                "purpose": "VARPURPOSE_THRESHOLD",
            },
            "5": {
                "id": "5",
                "key": 104,
                "device_id": 1,
                "label": "Mode",
                "value": "AUTO",
                "editable": True,
                "data_type": "VARTYPE_ENUMSTRING",
                "enum_values": ["AUTO", "MANUAL"],
            },
            "6": {
                "id": "6",
                "key": 105,
                "device_id": 1,
                "label": "Asset Tag",
                "value": "rack-a",
                "editable": True,
                "data_type": "VARTYPE_STRING",
                "max_length": 32,
            },
            "7": {
                "id": "7",
                "key": 106,
                "device_id": 1,
                "label": "Protocol",
                "value": "3015",
                "data_type": "VARTYPE_STRING",
                "purpose": "VARPURPOSE_EQUIPMENT",
                "group": "VARGROUP_DEVICE",
                "advanced_editable": True,
            },
            "8": {"id": "8", "device_id": 1, "label": "Empty", "value": ""},
            "9": {"id": "9", "device_id": 1, "label": "Secret", "value": "x", "password": True},
            "10": {
                "id": "10",
                "key": 107,
                "device_id": 1,
                "label": "Nominal Runtime",
                "value": "12.34",
                "editable": True,
                "numeric": True,
                "precision": 2,
            },
            "11": {
                "id": "11",
                "key": 108,
                "device_id": 1,
                "label": "Transfer Enabled",
                "value": "true",
                "purpose": "VARPURPOSE_CONFIGURATION",
            },
            "12": {
                "id": "12",
                "key": 109,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Runtime Remaining (Min)",
                "display_label": "Runtime Remaining",
                "value": "15",
                "data_type": "VARTYPE_INTEGER",
                "group": "VARGROUP_BATTERY",
                "purpose": "VARPURPOSE_STATUS",
            },
            "13": {
                "id": "13",
                "key": 120,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Battery Voltage",
                "value": "48.2",
                "suffix": "Volts",
                "data_type": "VARTYPE_FLOAT",
                "group": "VARGROUP_BATTERY",
                "purpose": "VARPURPOSE_STATUS",
            },
            "14": {
                "id": "14",
                "key": 111,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Voltage",
                "value": "121.0",
                "data_type": "VARTYPE_FLOAT",
                "group": "VARGROUP_INPUT",
                "purpose": "VARPURPOSE_STATUS",
            },
            "15": {
                "id": "15",
                "key": 112,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Load",
                "value": "42",
                "data_type": "VARTYPE_INTEGER",
                "group": "VARGROUP_OUTPUT",
                "purpose": "VARPURPOSE_STATUS",
            },
            "16": {
                "id": "16",
                "key": 113,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Internal Temp",
                "value": "32.5",
                "data_type": "VARTYPE_FLOAT",
                "group": "VARGROUP_ENVIRONMENT",
                "purpose": "VARPURPOSE_STATUS",
            },
            "17": {
                "id": "17",
                "key": 114,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "Output Peak Power",
                "value": "150",
                "suffix": "Watts",
                "data_type": "VARTYPE_INTEGER",
                "group": "VARGROUP_OUTPUT",
                "purpose": "VARPURPOSE_STATUS",
            },
            "18": {
                "id": "18",
                "key": 115,
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "label": "UPS Status",
                "value": "Online",
                "data_type": "VARTYPE_STRING",
                "group": "VARGROUP_DEVICE",
                "purpose": "VARPURPOSE_STATUS",
            },
        },
        "loads": {
            "1": {
                "id": "1",
                "device_id": 1,
                "device_type": "DEVICE_TYPE_UPS",
                "name": "Load 1",
                "load_number": 1,
                "state": "LOAD_STATE_ON",
                "controllable": True,
                "voltage_supported": True,
                "voltage": "120.1",
                "current_supported": True,
                "current": "1.5",
                "power_supported": True,
                "power": "100",
                "apparent_power_supported": True,
                "apparent_power": "",
                "power_limit_supported": True,
                "power_limit": "900",
            },
            "main": {
                "id": "main",
                "device_id": 1,
                "name": "Main load",
                "load_number": 0,
                "state": "LOAD_STATE_OFF",
                "controllable": True,
            },
            "2": {
                "id": "2",
                "device_id": 1,
                "name": "Skip load",
                "load_number": 2,
                "state": "",
                "controllable": False,
            },
        },
        "actions_supported": {
            "load_action_supported": {
                "supported_on_set": True,
                "load_identity_per_device": [{"loads": [{"id": "1"}]}],
            },
            "turn_on_device_supported": {"supported_on_set": True, "devices": [{"id": 1}]},
            "turn_off_device_supported": {"supported_on_set": True, "devices": [{"id": 1}]},
            "restart_device_supported": {"supported_on_set": True, "devices": [{"id": 1}]},
        },
        "alarm_summary": {
            "critical_alarm_count": 1,
            "warning_alarm_count": 2,
            "total_alarm_count": 6,
            "high_severity": "ALARM_SEVERITY_LEVEL_CRITICAL",
        },
        "ready": "yes",
        "system_details": {"firmware_version": "1.0", "mac_address": "00:11", "empty": ""},
        "system_uptime": {"system_uptime": "10"},
    }
    data["variables"] = {
        f"{variable['device_id']}:{variable['id']}": variable
        for variable in data["variables"].values()
    }
    data["loads"] = {
        f"{load['device_id']}:{load['id']}": load
        for load in data["loads"].values()
    }
    return data


async def setup_platform(module: object) -> tuple[list[object], FakeCoordinator, FakeEntry]:
    """Set up a platform and collect entities."""
    coordinator = FakeCoordinator()
    entry = FakeEntry(coordinator)
    entities: list[object] = []

    def add(new_entities: list[object]) -> None:
        entities.extend(new_entities)

    await module.async_setup_entry(None, entry, add)
    return entities, coordinator, entry


async def test_sensor_platform_entities() -> None:
    """Test sensor setup and state."""
    entities, coordinator, entry = await setup_platform(sensor)
    assert entry.unloads
    assert coordinator.listeners
    assert any(
        entity.name == "Battery Capacity" and entity.native_value == 100 for entity in entities
    )
    assert any(entity.name == "Critical alarms" and entity.native_value == 1 for entity in entities)
    assert any(
        entity.name == "State" and entity.native_value == "LOAD_STATE_ON" for entity in entities
    )
    assert any(entity.name == "Voltage" and entity.native_value == 120.1 for entity in entities)
    assert any(
        entity.name == "Firmware version" and entity.native_value == "1.0" for entity in entities
    )
    runtime = next(entity for entity in entities if entity.name == "Runtime Remaining")
    assert runtime.native_value == 15
    assert runtime._attr_native_unit_of_measurement == "min"
    assert runtime._attr_device_class == "duration"
    assert runtime.extra_state_attributes == {}
    battery_voltage = next(entity for entity in entities if entity.name == "Battery Voltage")
    assert battery_voltage.native_value == 48.2
    assert battery_voltage._attr_native_unit_of_measurement == "V"
    input_voltage = next(entity for entity in entities if entity.name == "Input Voltage")
    assert input_voltage.native_value == 121.0
    output_utilization = next(entity for entity in entities if entity.name == "Output Utilization")
    assert output_utilization.native_value == 42
    assert output_utilization._attr_native_unit_of_measurement == "%"
    temperature = next(entity for entity in entities if entity.name == "Temperature")
    assert temperature.native_value == 32.5
    assert temperature._attr_device_class is None
    peak_power = next(entity for entity in entities if entity.name == "Output Peak Power")
    assert peak_power.extra_state_attributes == {}
    ups_status = next(entity for entity in entities if entity.name == "Status")
    assert ups_status.native_value == "Online"
    assert ups_status.extra_state_attributes == {}
    for entity in entities:
        assert entity.unique_id
        _ = entity.available
        _ = entity.device_info
        if hasattr(entity, "extra_state_attributes"):
            _ = entity.extra_state_attributes

    coordinator.data["variables"]["1:19"] = {
        "id": "19",
        "key": 110,
        "device_id": 1,
        "label": "Output Frequency",
        "value": "60",
        "suffix": "Hz",
        "data_type": "VARTYPE_FLOAT",
        "group": "VARGROUP_OUTPUT",
    }
    coordinator.listeners[0]()
    assert any(entity.name == "Output Frequency" for entity in entities)
    variable = next(entity for entity in entities if entity.name == "Battery Capacity")
    coordinator.data["variables"].pop("1:1")
    assert variable.available is False


async def test_binary_sensor_platform_entities() -> None:
    """Test binary sensor setup and state."""
    entities, coordinator, _entry = await setup_platform(binary_sensor)
    assert any(entity.name == "Low Battery Alarm" and entity.is_on is False for entity in entities)
    assert any(entity.name == "Active alarms" and entity.is_on is True for entity in entities)
    online = next(entity for entity in entities if entity.name == "Online")
    on_battery = next(entity for entity in entities if entity.name == "On Battery")
    discharging = next(entity for entity in entities if entity.name == "Battery Discharging")
    assert online.is_on is True
    assert on_battery.is_on is False
    assert discharging.is_on is False
    coordinator.data["variables"]["1:18"]["value"] = "On Battery Discharging"
    assert online.is_on is False
    assert on_battery.is_on is True
    assert discharging.is_on is True
    coordinator.data["variables"]["1:18"]["value"] = "Unknown"
    assert online.is_on is None
    assert on_battery.is_on is False
    coordinator.data["variables"].pop("1:18")
    assert online.available is False
    diagnostic = next(entity for entity in entities if entity.name == "Transfer Enabled")
    assert diagnostic.is_on is True
    for entity in entities:
        assert entity.unique_id
        if hasattr(entity, "extra_state_attributes"):
            _ = entity.extra_state_attributes
    coordinator.data["alarm_summary"]["total_alarm_count"] = "bad"
    active = next(entity for entity in entities if entity.name == "Active alarms")
    assert active.is_on is False
    assert active.available is True
    coordinator.data["alarm_summary"].pop("total_alarm_count")
    assert active.available is False
    coordinator.data["variables"].pop("1:2")
    low_battery = next(entity for entity in entities if entity.name == "Low Battery Alarm")
    assert low_battery.available is False


def test_power_state_branch_helpers() -> None:
    """Test direct power-state parsing branches."""
    coordinator = FakeCoordinator()
    online_variable = {
        "id": "20",
        "device_id": 1,
        "label": "Online",
        "value": "false",
    }
    coordinator.data["variables"] = {"1:20": online_variable}
    online = binary_sensor.WebcardLXUPSPowerStateBinarySensor(
        coordinator,
        online_variable,
        "online",
        "Online",
        "online",
    )
    assert online.is_on is False

    on_battery_variable = {
        "id": "21",
        "device_id": 1,
        "label": "On Battery",
        "value": "true",
    }
    coordinator.data["variables"] = {"1:21": on_battery_variable}
    on_battery = binary_sensor.WebcardLXUPSPowerStateBinarySensor(
        coordinator,
        on_battery_variable,
        "on_battery",
        "On Battery",
        "on_battery",
    )
    assert on_battery.is_on is True

    discharging_variable = {
        "id": "22",
        "device_id": 1,
        "label": "Battery Discharging",
        "value": "false",
    }
    coordinator.data["variables"] = {"1:22": discharging_variable}
    discharging = binary_sensor.WebcardLXUPSPowerStateBinarySensor(
        coordinator,
        discharging_variable,
        "battery_discharging",
        "Battery Discharging",
        "battery_discharging",
    )
    assert discharging.is_on is False
    assert binary_sensor._ups_power_state_variables([None, {"label": "Alarm Status"}]) == []
    assert binary_sensor._power_state_variable_score({"label": "Line Status"}) == 10
    assert sensor._ups_status_variables([None, {"label": "Alarm Status"}]) == []
    assert sensor._status_variable_score({"label": "Line Status"}) == 10


async def test_switch_platform_entities_and_actions() -> None:
    """Test switch setup and actions."""
    entities, coordinator, _entry = await setup_platform(switch)
    load_switch = next(entity for entity in entities if entity.name == "Load 1")
    main_switch = next(entity for entity in entities if entity.name == "Main load")
    variable_switch = next(entity for entity in entities if entity.name == "Audible Alarm")
    assert load_switch.is_on is True
    assert main_switch.is_on is False
    assert variable_switch.is_on is True
    _ = load_switch.extra_state_attributes
    await load_switch.async_turn_off()
    await load_switch.async_turn_on()
    await main_switch.async_turn_on()
    await variable_switch.async_turn_off()
    await variable_switch.async_turn_on()
    assert ("load", ("1", "1", LOAD_ACTION_OFF)) in coordinator.client.calls
    assert ("main_load", ("1", LOAD_ACTION_ON)) in coordinator.client.calls
    assert ("variable", ("3", "false")) in coordinator.client.calls
    coordinator.data["loads"]["1:main"]["state"] = "LOAD_STATE_MIXED"
    assert main_switch.is_on is True
    coordinator.data["loads"]["1:main"]["state"] = ""
    assert main_switch.is_on is None
    coordinator.client.fail = True
    with pytest.raises(HomeAssistantError):
        await load_switch.async_turn_off()
    with pytest.raises(HomeAssistantError):
        await variable_switch.async_turn_off()
    coordinator.client.fail = False
    coordinator.data["loads"].pop("1:1")
    assert load_switch.available is False
    coordinator.data["variables"].pop("1:3")
    assert variable_switch.available is False
    with pytest.raises(HomeAssistantError):
        await load_switch.async_turn_off()
    with pytest.raises(HomeAssistantError):
        await variable_switch.async_turn_off()


async def test_number_select_text_entities() -> None:
    """Test editable variable entity platforms."""
    number_entities, number_coordinator, _ = await setup_platform(number)
    number_entity = number_entities[0]
    assert number_entity.name == "Low Battery Threshold"
    assert number_entity.native_value == 20
    assert any(getattr(entity, "_attr_native_step", None) == 0.01 for entity in number_entities)
    await number_entity.async_set_native_value(30)
    assert ("variable", ("4", 30)) in number_coordinator.client.calls
    number_coordinator.client.fail = True
    with pytest.raises(HomeAssistantError):
        await number_entity.async_set_native_value(30)
    number_coordinator.client.fail = False
    number_coordinator.data["variables"].pop("1:4")
    assert number_entity.available is False
    with pytest.raises(HomeAssistantError):
        await number_entity.async_set_native_value(30)

    select_entities, select_coordinator, _ = await setup_platform(select)
    select_entity = select_entities[0]
    assert select_entity.options == ["AUTO", "MANUAL"]
    assert select_entity.current_option == "AUTO"
    await select_entity.async_select_option("MANUAL")
    assert ("variable", ("5", "MANUAL")) in select_coordinator.client.calls
    select_coordinator.client.fail = True
    with pytest.raises(HomeAssistantError):
        await select_entity.async_select_option("AUTO")
    select_coordinator.client.fail = False
    select_coordinator.data["variables"]["1:5"]["value"] = ""
    assert select_entity.current_option is None
    select_coordinator.data["variables"].pop("1:5")
    assert select_entity.available is False
    with pytest.raises(HomeAssistantError):
        await select_entity.async_select_option("AUTO")

    text_entities, text_coordinator, _ = await setup_platform(text)
    text_entity = text_entities[0]
    assert text_entity.native_value == "rack-a"
    await text_entity.async_set_value("rack-b")
    assert ("variable", ("6", "rack-b")) in text_coordinator.client.calls
    text_coordinator.client.fail = True
    with pytest.raises(HomeAssistantError):
        await text_entity.async_set_value("rack-c")
    text_coordinator.client.fail = False
    text_coordinator.data["variables"]["1:6"]["value"] = ""
    assert text_entity.native_value is None
    text_coordinator.data["variables"].pop("1:6")
    assert text_entity.available is False
    with pytest.raises(HomeAssistantError):
        await text_entity.async_set_value("rack-c")


async def test_button_platform_entities_and_actions() -> None:
    """Test button setup and actions."""
    entities, coordinator, _entry = await setup_platform(button)
    names = {entity.name for entity in entities}
    assert {"Cycle", "Turn on", "Turn off", "Reboot", "Acknowledge all alarms"} <= names
    for entity in entities:
        await entity.async_press()
    assert ("load", ("1", "1", LOAD_ACTION_CYCLE)) in coordinator.client.calls
    assert ("device", ("turn_on", "1")) in coordinator.client.calls
    assert ("ack_all", ()) in coordinator.client.calls
    cycle = next(entity for entity in entities if entity.name == "Cycle")
    turn_on = next(entity for entity in entities if entity.name == "Turn on")
    coordinator.data["actions_supported"]["load_action_supported"] = {"supported_on_set": False}
    coordinator.data["loads"]["1:1"]["controllable"] = False
    assert cycle.available is False
    with pytest.raises(HomeAssistantError):
        await cycle.async_press()
    coordinator.data["actions_supported"]["load_action_supported"] = {"supported_on_set": True}
    coordinator.data["loads"]["1:1"]["controllable"] = True
    assert cycle.available is True
    coordinator.data["actions_supported"]["turn_on_device_supported"] = {"supported_on_set": False}
    assert turn_on.available is False
    with pytest.raises(HomeAssistantError):
        await turn_on.async_press()
    coordinator.data["actions_supported"]["turn_on_device_supported"] = {
        "supported_on_set": True,
        "devices": [{"id": 1}],
    }
    assert turn_on.available is True
    coordinator.client.fail = True
    with pytest.raises(HomeAssistantError):
        await cycle.async_press()


def test_base_entity_device_info_fallback() -> None:
    """Test device info fallback identifier."""
    coordinator = FakeCoordinator()
    coordinator.data["devices"]["1"].pop("serial_number")
    entity = WebcardLXEntity(coordinator, "1")
    assert ("tripp_lite_webcardlx", "entry_1") in entity.device_info["identifiers"]
    assert entity._load == {}
    child = WebcardLXEntity(coordinator, "1", "1:1", coordinator.data["loads"]["1:1"])
    assert child._load["id"] == "1"
    coordinator.data["loads"].pop("1:1")
    assert child._load == {}
    assert child.device_info["name"] == "Load 1"
    assert device_connections({"mac": "AA:BB:CC"}) == {("mac", "aa:bb:cc")}
    assert device_connections({"mac_address": "00:11:22"}) == {("mac", "00:11:22")}
    assert device_connections({}) == set()


def test_handle_coordinator_update_refreshes_cache() -> None:
    """Test that _handle_coordinator_update refreshes cached device and device_info."""
    coordinator = FakeCoordinator()
    entity = WebcardLXEntity(coordinator, "1")
    # Verify initial cached device has the right name.
    assert entity._device.get("name") == "UPS"
    # Simulate a coordinator update that changes the device name.
    # Patch async_write_ha_state since hass is not set in unit tests.
    entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    coordinator.data["devices"]["1"]["name"] = "Updated UPS"
    entity._handle_coordinator_update()
    assert entity._device.get("name") == "Updated UPS"
    assert entity.device_info["name"] == "Updated UPS"

    # Test with a load entity.
    load_data = coordinator.data["loads"]["1:1"]
    child = WebcardLXEntity(coordinator, "1", "1:1", load_data)
    child.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    coordinator.data["loads"]["1:1"]["name"] = "Renamed Load"
    child._handle_coordinator_update()
    assert child.device_info["name"] == "Renamed Load"


async def test_ups_status_sensor_handle_coordinator_update() -> None:
    """Test WebcardLXUPSStatusSensor._handle_coordinator_update refreshes the status variable."""
    entities, coordinator, _entry = await setup_platform(sensor)
    status_sensor = next(entity for entity in entities if entity.name == "Status")
    # Patch async_write_ha_state since hass is not set in unit tests.
    status_sensor.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    # Initial state: UPS Status variable "1:18" is used (value "Online").
    assert status_sensor.native_value == "Online"
    # Simulate coordinator update — update the variable value and trigger the callback.
    coordinator.data["variables"]["1:18"]["value"] = "On Battery"
    status_sensor._handle_coordinator_update()
    assert status_sensor.native_value == "On Battery"
    # Remove the status variable and trigger update — sensor should become unavailable.
    coordinator.data["variables"].pop("1:18")
    status_sensor._handle_coordinator_update()
    assert status_sensor.available is False


async def test_ups_power_state_binary_sensor_handle_coordinator_update() -> None:
    """Test WebcardLXUPSPowerStateBinarySensor._handle_coordinator_update."""
    entities, coordinator, _entry = await setup_platform(binary_sensor)
    online = next(entity for entity in entities if entity.name == "Online")
    # Patch async_write_ha_state since hass is not set in unit tests.
    online.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    assert online.is_on is True
    # Update the underlying variable value and trigger coordinator update.
    coordinator.data["variables"]["1:18"]["value"] = "On Battery Discharging"
    online._handle_coordinator_update()
    assert online.is_on is False
    # Remove the power-state variable — sensor should become unavailable.
    coordinator.data["variables"].pop("1:18")
    online._handle_coordinator_update()
    assert online.available is False
