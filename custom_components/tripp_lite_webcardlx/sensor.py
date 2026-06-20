"""Sensor platform for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WebcardLXRuntimeData
from .entity import WebcardLXEntity, entity_device_id
from .helpers import (
    as_bool,
    as_float,
    is_editable_variable,
    is_main_load,
    label,
    load_id,
    load_key,
    stable_slug,
    stable_unique_suffix,
    variable_key,
    variable_unique_key,
)
from .metadata import (
    LOAD_METRICS,
    ValueMetadata,
    native_variable_value,
    normalized_text,
    value_metadata,
)

PARALLEL_UPDATES = 0

ALARM_SUMMARY_SENSORS = {
    "critical_alarm_count": "Critical alarms",
    "warning_alarm_count": "Warning alarms",
    "informational_alarm_count": "Informational alarms",
    "total_alarm_count": "Total alarms",
    "high_severity": "Highest alarm severity",
}

SYSTEM_DETAIL_SENSORS = {
    "system_uptime": "System uptime",
    "system_time": "System time",
    "firmware_version": "Firmware version",
    "mac_address": "MAC address",
    "serial_number": "Card serial number",
    "ready": "Ready",
}


@dataclass(frozen=True)
class UPSVariableSensorDescription:
    """Description for a high-value UPS monitoring variable."""

    key: str
    name: str
    required_terms: tuple[str, ...] = ()
    any_terms: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    native_unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = "measurement"
    suggested_display_precision: int | None = None


UPS_VARIABLE_SENSOR_DESCRIPTIONS: tuple[UPSVariableSensorDescription, ...] = (
    UPSVariableSensorDescription(
        key="runtime_remaining",
        name="Runtime Remaining",
        required_terms=("runtime",),
        any_terms=("remaining", "remain"),
        native_unit_of_measurement="min",
        device_class="duration",
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="battery_capacity",
        name="Battery Capacity",
        any_terms=("capacity", "charge"),
        context_terms=("battery",),
        groups=("VARGROUP_BATTERY",),
        native_unit_of_measurement=PERCENTAGE,
        device_class="battery",
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="battery_voltage",
        name="Battery Voltage",
        required_terms=("voltage",),
        context_terms=("battery",),
        groups=("VARGROUP_BATTERY",),
        native_unit_of_measurement="V",
        device_class="voltage",
        suggested_display_precision=1,
    ),
    UPSVariableSensorDescription(
        key="input_voltage",
        name="Input Voltage",
        required_terms=("voltage",),
        context_terms=("input", "line"),
        groups=("VARGROUP_INPUT",),
        native_unit_of_measurement="V",
        device_class="voltage",
        suggested_display_precision=1,
    ),
    UPSVariableSensorDescription(
        key="input_current",
        name="Input Current",
        required_terms=("current",),
        context_terms=("input", "line"),
        groups=("VARGROUP_INPUT",),
        native_unit_of_measurement="A",
        device_class="current",
        suggested_display_precision=2,
    ),
    UPSVariableSensorDescription(
        key="input_frequency",
        name="Input Frequency",
        required_terms=("frequency",),
        context_terms=("input", "line"),
        groups=("VARGROUP_INPUT",),
        native_unit_of_measurement="Hz",
        device_class="frequency",
        suggested_display_precision=1,
    ),
    UPSVariableSensorDescription(
        key="output_voltage",
        name="Output Voltage",
        required_terms=("voltage",),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement="V",
        device_class="voltage",
        suggested_display_precision=1,
    ),
    UPSVariableSensorDescription(
        key="output_current",
        name="Output Current",
        required_terms=("current",),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement="A",
        device_class="current",
        suggested_display_precision=2,
    ),
    UPSVariableSensorDescription(
        key="output_frequency",
        name="Output Frequency",
        required_terms=("frequency",),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement="Hz",
        device_class="frequency",
        suggested_display_precision=1,
    ),
    UPSVariableSensorDescription(
        key="output_power_factor",
        name="Output Power Factor",
        required_terms=("power", "factor"),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement=PERCENTAGE,
        device_class="power_factor",
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="output_apparent_power",
        name="Output Apparent Power",
        required_terms=("apparent", "power"),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement="VA",
        device_class="apparent_power",
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="output_reactive_power",
        name="Output Reactive Power",
        required_terms=("reactive", "power"),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement="var",
        device_class="reactive_power",
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="output_power",
        name="Output Power",
        required_terms=("power",),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        excluded_terms=("apparent", "reactive", "factor", "peak"),
        native_unit_of_measurement="W",
        device_class="power",
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="output_utilization",
        name="Output Utilization",
        any_terms=("utilization", "usage", "load"),
        context_terms=("output",),
        groups=("VARGROUP_OUTPUT",),
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    UPSVariableSensorDescription(
        key="temperature",
        name="Temperature",
        any_terms=("temperature", "temp"),
        groups=("VARGROUP_ENVIRONMENT",),
        device_class="temperature",
        suggested_display_precision=1,
    ),
)

UPS_STATUS_LABEL_PATTERNS = (
    ("ups", "status"),
    ("device", "state"),
    ("operating", "mode"),
    ("operation", "mode"),
    ("power", "source"),
    ("input", "source"),
    ("line", "status"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WebcardLX sensors."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[SensorEntity] = []
        first_device_id = next(iter(coordinator.data.get("devices", {})), "")

        for variable in coordinator.data.get("variables", {}).values():
            if not _is_variable_sensor(variable):
                continue
            entity = WebcardLXVariableSensor(coordinator, variable)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        status_variables = _ups_status_variables(coordinator.data.get("variables", {}).values())
        for status_variable in status_variables:
            entity = WebcardLXUPSStatusSensor(coordinator, status_variable)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        if first_device_id and coordinator.data.get("alarm_summary"):
            for key, name in ALARM_SUMMARY_SENSORS.items():
                if key not in coordinator.data["alarm_summary"]:
                    continue
                entity = WebcardLXAlarmSummarySensor(coordinator, first_device_id, key, name)
                if entity.unique_id not in known_unique_ids:
                    known_unique_ids.add(entity.unique_id)
                    entities.append(entity)

        for load in coordinator.data.get("loads", {}).values():
            entity = WebcardLXLoadStateSensor(coordinator, load)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

            for metric_key, (supported_key, default_unit) in LOAD_METRICS.items():
                if not load.get(supported_key):
                    continue
                if load.get(metric_key) in (None, ""):
                    continue
                metric_entity = WebcardLXLoadMetricSensor(
                    coordinator,
                    load,
                    metric_key,
                    default_unit,
                )
                if metric_entity.unique_id not in known_unique_ids:
                    known_unique_ids.add(metric_entity.unique_id)
                    entities.append(metric_entity)

        if first_device_id:
            for entity in _system_entities(coordinator, first_device_id):
                if entity.unique_id not in known_unique_ids:
                    known_unique_ids.add(entity.unique_id)
                    entities.append(entity)

        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


def _is_variable_sensor(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable should be represented as a sensor."""
    if attributes.get("password"):
        return False
    if _is_ups_status_variable(attributes):
        return False
    value = attributes.get("raw_value", attributes.get("value"))
    if value in (None, ""):
        return False
    data_type = str(attributes.get("data_type") or "").upper()
    if as_bool(value) is not None and data_type not in {"VARTYPE_INTEGER", "VARTYPE_FLOAT"}:
        return False
    if is_editable_variable(attributes):
        return False
    return True


class WebcardLXVariableSensor(WebcardLXEntity, SensorEntity):
    """Sensor backed by a WebcardLX variable."""

    def __init__(self, coordinator: Any, variable: Mapping[str, Any]) -> None:
        """Initialize the sensor."""
        self._variable_key = variable_key(variable)
        self._monitor_description = _ups_monitor_description(variable)
        self._attr_name = (
            self._monitor_description.name
            if self._monitor_description is not None
            else label(variable, "Variable")
        )
        if self._monitor_description is not None:
            self._attr_translation_key = self._monitor_description.key
        metadata = _value_metadata_for_variable(
            self._attr_name,
            variable,
            self._monitor_description,
        )
        self._attr_native_unit_of_measurement = metadata.native_unit_of_measurement
        self._attr_device_class = metadata.device_class
        self._attr_state_class = metadata.state_class
        self._attr_suggested_display_precision = metadata.suggested_display_precision
        self._attr_entity_registry_enabled_default = not _is_noisy_variable(variable)
        if _is_diagnostic_variable(variable):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_variable_"
            f"{variable_unique_key(variable)}"
        )

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current variable attributes."""
        return self.coordinator.data.get("variables", {}).get(self._variable_key, {})

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and _is_variable_sensor(self._variable)

    @property
    def native_value(self) -> Any:
        """Return the sensor state."""
        return native_variable_value(dict(self._variable))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {}


class WebcardLXUPSStatusSensor(WebcardLXEntity, SensorEntity):
    """Sensor exposing a stable UPS status value."""

    _attr_name = "Status"
    _attr_translation_key = "ups_status"

    def __init__(self, coordinator: Any, variable: Mapping[str, Any]) -> None:
        """Initialize the status sensor."""
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{device_id_value}_ups_status"
        self._cached_status_var: Mapping[str, Any] = variable

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._cached_status_var = _best_status_variable_for_device(
            self.coordinator.data.get("variables", {}).values(),
            self._device_id,
        )
        super()._handle_coordinator_update()

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current status variable attributes."""
        return self._cached_status_var

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and bool(self._variable)

    @property
    def native_value(self) -> Any:
        """Return the UPS status value."""
        return native_variable_value(dict(self._variable))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return status variable details."""
        return {}


class WebcardLXAlarmSummarySensor(WebcardLXEntity, SensorEntity):
    """Alarm summary sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: Any,
        device_id_value: str,
        key: str,
        name: str,
    ) -> None:
        """Initialize the alarm summary sensor."""
        super().__init__(coordinator, device_id_value)
        self._key = key
        self._attr_name = name
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_alarm_summary_{key}"
        if key.endswith("_count"):
            self._attr_state_class = "measurement"

    @property
    def native_value(self) -> Any:
        """Return the alarm summary value."""
        return self.coordinator.data.get("alarm_summary", {}).get(self._key)

    @property
    def available(self) -> bool:
        """Return whether the alarm summary value is available."""
        return (
            super().available
            and self._key in self.coordinator.data.get("alarm_summary", {})
        )


class WebcardLXLoadStateSensor(WebcardLXEntity, SensorEntity):
    """Sensor for load state."""

    def __init__(self, coordinator: Any, load: Mapping[str, Any]) -> None:
        """Initialize the load state sensor."""
        self._load_id = load_id(load)
        self._load_key = load_key(load)
        self._attr_name = "State" if not is_main_load(load) else f"{label(load, 'Load')} state"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        device_id_value = entity_device_id(load)
        super().__init__(
            coordinator,
            device_id_value,
            None if is_main_load(load) else self._load_key,
            load,
        )
        suffix = "main" if is_main_load(load) else stable_unique_suffix(self._load_id, "load")
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_load_{suffix}_state"
        )

    @property
    def _load(self) -> Mapping[str, Any]:
        """Return current load attributes."""
        return self.coordinator.data.get("loads", {}).get(self._load_key, {})

    @property
    def available(self) -> bool:
        """Return whether the load exists."""
        return super().available and self._load.get("state") not in (None, "")

    @property
    def native_value(self) -> Any:
        """Return the load state."""
        return self._load.get("state")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra load attributes."""
        return {}


class WebcardLXLoadMetricSensor(WebcardLXEntity, SensorEntity):
    """Sensor for a load metric."""

    def __init__(
        self,
        coordinator: Any,
        load: Mapping[str, Any],
        metric_key: str,
        default_unit: str | None,
    ) -> None:
        """Initialize the load metric sensor."""
        self._load_id = load_id(load)
        self._load_key = load_key(load)
        self._metric_key = metric_key
        self._supported_key = LOAD_METRICS[metric_key][0]
        metric_name = metric_key.replace("_", " ")
        self._attr_name = (
            metric_name.title()
            if not is_main_load(load)
            else f"{label(load, 'Load')} {metric_name}"
        )
        metadata = value_metadata(metric_name, default_unit)
        self._attr_native_unit_of_measurement = metadata.native_unit_of_measurement
        self._attr_device_class = metadata.device_class
        self._attr_state_class = metadata.state_class
        self._attr_suggested_display_precision = metadata.suggested_display_precision
        if "limit" in metric_key or "crest" in metric_key:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        device_id_value = entity_device_id(load)
        super().__init__(
            coordinator,
            device_id_value,
            None if is_main_load(load) else self._load_key,
            load,
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_load_"
            f"{stable_unique_suffix(self._load_id, 'load')}_{metric_key}"
        )

    @property
    def _load(self) -> Mapping[str, Any]:
        """Return current load attributes."""
        return self.coordinator.data.get("loads", {}).get(self._load_key, {})

    @property
    def available(self) -> bool:
        """Return whether the load exists."""
        return (
            super().available
            and bool(self._load.get(self._supported_key))
            and self._load.get(self._metric_key) not in (None, "")
        )

    @property
    def native_value(self) -> Any:
        """Return the metric value."""
        value = as_float(self._load.get(self._metric_key))
        return value if value is not None else self._load.get(self._metric_key)


class WebcardLXSystemSensor(WebcardLXEntity, SensorEntity):
    """Diagnostic sensor for WebcardLX system details."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: Any,
        device_id_value: str,
        source_key: str,
        value_key: str,
        name: str,
    ) -> None:
        """Initialize the system sensor."""
        super().__init__(coordinator, device_id_value)
        self._source_key = source_key
        self._value_key = value_key
        self._attr_name = name
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_system_"
            f"{stable_slug(source_key + '_' + value_key, 'detail')}"
        )

    @property
    def native_value(self) -> Any:
        """Return the diagnostic value."""
        return self.coordinator.data.get(self._source_key, {}).get(self._value_key)

    @property
    def available(self) -> bool:
        """Return whether the diagnostic value is still available."""
        return super().available and self.native_value not in (None, "")


def _is_diagnostic_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable is diagnostic."""
    return attributes.get("purpose") != "VARPURPOSE_STATUS" or attributes.get("group") in {
        "VARGROUP_SYSTEM",
        "VARGROUP_DEVICE",
    }


def _is_noisy_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable should be disabled by default."""
    return bool(attributes.get("advanced_editable")) or attributes.get("purpose") in {
        "VARPURPOSE_EQUIPMENT",
        "VARPURPOSE_THRESHOLD",
        "VARPURPOSE_BEHAVIOR",
        "VARPURPOSE_PERSONAL",
    }


def _is_ups_status_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable carries the primary UPS power/status state."""
    if attributes.get("password") or is_editable_variable(attributes):
        return False
    text = normalized_text(
        attributes.get("display_label"),
        attributes.get("label"),
        attributes.get("name"),
    )
    if _has_any_term(text, ("alarm", "threshold", "delay")):
        return False
    return any(
        all(_has_any_term(text, (term,)) for term in terms)
        for terms in UPS_STATUS_LABEL_PATTERNS
    )


def _ups_status_variables(variables: Any) -> list[Mapping[str, Any]]:
    """Return the best UPS status variable per device."""
    candidates: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for variable in variables:
        if not isinstance(variable, Mapping) or not _is_ups_status_variable(variable):
            continue
        current_device_id = entity_device_id(variable)
        score = _status_variable_score(variable)
        existing = candidates.get(current_device_id)
        if existing is None or score > existing[0]:
            candidates[current_device_id] = (score, variable)
    return [item[1] for item in candidates.values()]


def _best_status_variable_for_device(
    variables: Any,
    device_id_value: str,
) -> Mapping[str, Any]:
    """Return the best current status variable for a device."""
    best: tuple[int, Mapping[str, Any]] | None = None
    for variable in variables:
        if (
            not isinstance(variable, Mapping)
            or entity_device_id(variable) != device_id_value
            or not _is_ups_status_variable(variable)
        ):
            continue
        score = _status_variable_score(variable)
        if best is None or score > best[0]:
            best = (score, variable)
    return best[1] if best is not None else {}


def _status_variable_score(attributes: Mapping[str, Any]) -> int:
    """Return a score for status variable matching."""
    text = normalized_text(
        attributes.get("display_label"),
        attributes.get("label"),
        attributes.get("name"),
    )
    if text in {"ups status", "status", "device state", "operating mode", "power source"}:
        return 100
    return sum(
        10
        for terms in UPS_STATUS_LABEL_PATTERNS
        if all(_has_any_term(text, (term,)) for term in terms)
    )


def _has_any_term(text: str, terms: tuple[str, ...]) -> bool:
    """Return whether normalized text includes any whole term or phrase."""
    padded = f" {text} "
    return any(f" {term} " in padded for term in terms)


def _ups_monitor_description(
    attributes: Mapping[str, Any],
) -> UPSVariableSensorDescription | None:
    """Return a first-class UPS monitor description for a variable."""
    text = normalized_text(
        attributes.get("display_label"),
        attributes.get("label"),
        attributes.get("name"),
        attributes.get("suffix"),
    )
    group = str(attributes.get("group") or "").upper()
    for description in UPS_VARIABLE_SENSOR_DESCRIPTIONS:
        if any(term in text for term in description.excluded_terms):
            continue
        if description.required_terms and not all(
            term in text for term in description.required_terms
        ):
            continue
        if description.any_terms and not any(term in text for term in description.any_terms):
            continue
        if description.context_terms or description.groups:
            context_match = group in description.groups or any(
                term in text for term in description.context_terms
            )
            if not context_match:
                continue
        return description
    return None


def _value_metadata_for_variable(
    name: str,
    variable: Mapping[str, Any],
    description: UPSVariableSensorDescription | None,
) -> ValueMetadata:
    """Return HA metadata with curated UPS monitor defaults when available."""
    metadata = value_metadata(name, variable.get("suffix"))
    if description is None:
        return metadata
    description_device_class = description.device_class
    if (
        description_device_class == "temperature"
        and not metadata.native_unit_of_measurement
        and not description.native_unit_of_measurement
    ):
        description_device_class = None
    return ValueMetadata(
        metadata.native_unit_of_measurement or description.native_unit_of_measurement,
        metadata.device_class or description_device_class,
        metadata.state_class or description.state_class,
        metadata.suggested_display_precision
        if metadata.suggested_display_precision is not None
        else description.suggested_display_precision,
    )


def _system_entities(coordinator: Any, first_device_id: str) -> list[WebcardLXSystemSensor]:
    """Return system diagnostic entities that have values."""
    entities: list[WebcardLXSystemSensor] = []
    for source_key in ("ready", "system_details", "system_uptime"):
        source = coordinator.data.get(source_key, {})
        if not isinstance(source, Mapping):
            continue
        for value_key, value in source.items():
            if value in (None, ""):
                continue
            name = SYSTEM_DETAIL_SENSORS.get(value_key, value_key.replace("_", " ").title())
            entities.append(
                WebcardLXSystemSensor(coordinator, first_device_id, source_key, value_key, name)
            )
    return entities
