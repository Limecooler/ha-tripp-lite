"""Binary sensor platform for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WebcardLXRuntimeData
from .entity import WebcardLXEntity, entity_device_id
from .helpers import (
    as_bool,
    is_editable_variable,
    label,
    raw_value,
    variable_key,
    variable_unique_key,
)

PARALLEL_UPDATES = 0

PROBLEM_LABEL_PARTS = (
    "alarm",
    "fault",
    "fail",
    "low battery",
    "overload",
    "over temperature",
    "overtemperature",
    "replace battery",
)

UPS_STATUS_LABEL_PATTERNS = (
    ("ups", "status"),
    ("device", "state"),
    ("operating", "mode"),
    ("operation", "mode"),
    ("power", "source"),
    ("input", "source"),
    ("line", "status"),
    ("on", "battery"),
    ("online",),
    ("battery", "discharging"),
)

ON_BATTERY_TERMS = (
    "on battery",
    "battery mode",
    "battery power",
    "onbatt",
    "backup",
    "discharging",
)
ONLINE_TERMS = ("online", "on line", "normal", "utility", "line power", "mains")
OFFLINE_TERMS = ("offline", "off line", "unavailable", "lost")
DISCHARGING_TERMS = ("discharging", "discharge")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WebcardLX binary sensors."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[BinarySensorEntity] = []
        first_device_id = next(iter(coordinator.data.get("devices", {})), "")

        for variable in coordinator.data.get("variables", {}).values():
            if not _is_binary_variable(variable):
                continue
            entity = WebcardLXVariableBinarySensor(coordinator, variable)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        if first_device_id and coordinator.data.get("alarm_summary"):
            entity = WebcardLXActiveAlarmBinarySensor(coordinator, first_device_id)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        status_variables = _ups_power_state_variables(
            coordinator.data.get("variables", {}).values()
        )
        for status_variable in status_variables:
            for kind, name, translation_key in (
                ("online", "Online", "online"),
                ("on_battery", "On Battery", "on_battery"),
                (
                    "battery_discharging",
                    "Battery Discharging",
                    "battery_discharging",
                ),
            ):
                entity = WebcardLXUPSPowerStateBinarySensor(
                    coordinator,
                    status_variable,
                    kind,
                    name,
                    translation_key,
                )
                if entity.unique_id not in known_unique_ids:
                    known_unique_ids.add(entity.unique_id)
                    entities.append(entity)

        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


def _is_binary_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable should be represented as a binary sensor."""
    if attributes.get("password") or is_editable_variable(attributes):
        return False
    if _is_ups_power_state_variable(attributes):
        return False
    return as_bool(raw_value(attributes)) is not None


class WebcardLXUPSPowerStateBinarySensor(WebcardLXEntity, BinarySensorEntity):
    """Stable UPS power-state binary sensor."""

    def __init__(
        self,
        coordinator: Any,
        variable: Mapping[str, Any],
        kind: str,
        name: str,
        translation_key: str,
    ) -> None:
        """Initialize the binary sensor."""
        self._kind = kind
        self._attr_name = name
        self._attr_translation_key = translation_key
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_ups_power_state_{kind}"
        )
        self._cached_power_state_var: Mapping[str, Any] = variable

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._cached_power_state_var = _best_power_state_variable_for_device(
            self.coordinator.data.get("variables", {}).values(),
            self._device_id,
        )
        super()._handle_coordinator_update()

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current power-state variable attributes."""
        return self._cached_power_state_var

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and _is_binary_variable(self._variable)

    @property
    def is_on(self) -> bool | None:
        """Return the derived UPS power-state value."""
        variable = self._variable
        text = _normalized_text(raw_value(variable), variable.get("state"))
        label_text = _normalized_text(
            variable.get("display_label"),
            variable.get("label"),
            variable.get("name"),
        )
        parsed_bool = as_bool(raw_value(variable))

        if self._kind == "online":
            if "online" in label_text and parsed_bool is not None:
                return parsed_bool
            if _has_any_term(text, OFFLINE_TERMS) or _is_on_battery_text(text):
                return False
            if _has_any_term(text, ONLINE_TERMS):
                return True
            return None

        if self._kind == "on_battery":
            if "on battery" in label_text and parsed_bool is not None:
                return parsed_bool
            if _has_any_term(text, ONLINE_TERMS):
                return False
            return _is_on_battery_text(text)

        if "discharging" in label_text and parsed_bool is not None:
            return parsed_bool
        return _has_any_term(text, DISCHARGING_TERMS)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return source variable details."""
        return {}


class WebcardLXVariableBinarySensor(WebcardLXEntity, BinarySensorEntity):
    """Binary sensor backed by a boolean WebcardLX variable."""

    def __init__(self, coordinator: Any, variable: Mapping[str, Any]) -> None:
        """Initialize the binary sensor."""
        self._variable_key = variable_key(variable)
        self._attr_name = label(variable, "Variable")
        lower_name = self._attr_name.lower()
        if any(part in lower_name for part in PROBLEM_LABEL_PARTS):
            self._attr_device_class = "problem"
        if variable.get("purpose") != "VARPURPOSE_STATUS":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_variable_"
            f"{variable_unique_key(variable)}_binary"
        )

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current variable attributes."""
        return self.coordinator.data.get("variables", {}).get(self._variable_key, {})

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and _is_binary_variable(self._variable)

    @property
    def is_on(self) -> bool | None:
        """Return the boolean state."""
        return as_bool(raw_value(self._variable))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {}


class WebcardLXActiveAlarmBinarySensor(WebcardLXEntity, BinarySensorEntity):
    """Binary sensor showing whether alarms are active."""

    _attr_name = "Active alarms"
    _attr_translation_key = "active_alarms"
    _attr_device_class = "problem"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Any, device_id_value: str) -> None:
        """Initialize the active alarm binary sensor."""
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_active_alarms"

    @property
    def is_on(self) -> bool:
        """Return whether alarms are active."""
        count = self.coordinator.data.get("alarm_summary", {}).get("total_alarm_count", 0)
        try:
            return int(count) > 0
        except (TypeError, ValueError):
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return alarm count attributes."""
        return dict(self.coordinator.data.get("alarm_summary", {}))

    @property
    def available(self) -> bool:
        """Return whether alarm summary data is available."""
        return (
            super().available
            and "total_alarm_count" in self.coordinator.data.get("alarm_summary", {})
        )


def _is_on_battery_text(text: str) -> bool:
    """Return whether status text describes battery operation."""
    return _has_any_term(text, ON_BATTERY_TERMS)


def _is_ups_power_state_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable carries UPS power/status state."""
    if attributes.get("password") or is_editable_variable(attributes):
        return False
    text = _normalized_text(
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


def _ups_power_state_variables(variables: Any) -> list[Mapping[str, Any]]:
    """Return the best UPS power/status variable per device."""
    candidates: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for variable in variables:
        if not isinstance(variable, Mapping) or not _is_ups_power_state_variable(variable):
            continue
        current_device_id = entity_device_id(variable)
        score = _power_state_variable_score(variable)
        existing = candidates.get(current_device_id)
        if existing is None or score > existing[0]:
            candidates[current_device_id] = (score, variable)
    return [item[1] for item in candidates.values()]


def _best_power_state_variable_for_device(
    variables: Any,
    device_id_value: str,
) -> Mapping[str, Any]:
    """Return the best current UPS power-state variable for a device."""
    best: tuple[int, Mapping[str, Any]] | None = None
    for variable in variables:
        if (
            not isinstance(variable, Mapping)
            or entity_device_id(variable) != device_id_value
            or not _is_ups_power_state_variable(variable)
        ):
            continue
        score = _power_state_variable_score(variable)
        if best is None or score > best[0]:
            best = (score, variable)
    return best[1] if best is not None else {}


def _power_state_variable_score(attributes: Mapping[str, Any]) -> int:
    """Return a score for power-state variable matching."""
    text = _normalized_text(
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


def _normalized_text(*values: Any) -> str:
    """Return normalized text for status matching."""
    text = " ".join(str(value).strip().lower() for value in values if value not in (None, ""))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _has_any_term(text: str, terms: tuple[str, ...]) -> bool:
    """Return whether normalized text includes any whole term or phrase."""
    padded = f" {text} "
    return any(f" {term} " in padded for term in terms)
