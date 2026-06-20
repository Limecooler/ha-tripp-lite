"""Number platform for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WebcardLXRuntimeData
from .entity import WebcardLXEntity, entity_device_id
from .helpers import (
    as_bool,
    as_float,
    enum_options,
    is_editable_variable,
    label,
    raw_value,
    variable_id,
    variable_key,
    variable_unique_key,
)
from .metadata import value_metadata

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WebcardLX number entities."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[NumberEntity] = []
        for variable in coordinator.data.get("variables", {}).values():
            if not _is_number_variable(variable):
                continue
            entity = WebcardLXVariableNumber(coordinator, variable)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)
        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


def _is_number_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable should be represented as a number."""
    if attributes.get("password") or not is_editable_variable(attributes):
        return False
    if as_bool(raw_value(attributes)) is not None:
        return False
    if enum_options(attributes):
        return False
    data_type = str(attributes.get("data_type") or "").upper()
    return data_type in {"VARTYPE_INTEGER", "VARTYPE_FLOAT"} or bool(attributes.get("numeric"))


class WebcardLXVariableNumber(WebcardLXEntity, NumberEntity):
    """Number entity for an editable numeric variable."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_mode = "box"

    def __init__(self, coordinator: Any, variable: Mapping[str, Any]) -> None:
        """Initialize the number entity."""
        self._variable_key = variable_key(variable)
        self._attr_name = label(variable, "Setting")
        metadata = value_metadata(self._attr_name, variable.get("suffix"))
        self._attr_native_unit_of_measurement = metadata.native_unit_of_measurement
        self._attr_device_class = metadata.device_class
        self._attr_suggested_display_precision = metadata.suggested_display_precision
        if (minimum := as_float(variable.get("min_value"))) is not None:
            self._attr_native_min_value = minimum
        if (maximum := as_float(variable.get("max_value"))) is not None:
            self._attr_native_max_value = maximum
        precision = variable.get("precision")
        if isinstance(precision, int) and precision > 0:
            self._attr_native_step = 10 ** -precision
        else:
            self._attr_native_step = 1
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_variable_"
            f"{variable_unique_key(variable)}_number"
        )

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current variable attributes."""
        return self.coordinator.data.get("variables", {}).get(self._variable_key, {})

    @property
    def available(self) -> bool:
        """Return whether the variable still exists in coordinator data."""
        return (
            super().available
            and self._variable_key in self.coordinator.data.get("variables", {})
        )

    @property
    def native_value(self) -> float | None:
        """Return the current numeric value."""
        return as_float(raw_value(self._variable))

    async def async_set_native_value(self, value: float) -> None:
        """Set the numeric value."""
        if not _is_number_variable(self._variable):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="variable_not_editable",
            )
        try:
            await self.coordinator.client.async_update_variable(variable_id(self._variable), value)
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="variable_update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
