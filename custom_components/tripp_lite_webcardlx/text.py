"""Text platform for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.text import TextEntity
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
    as_int,
    enum_options,
    is_editable_variable,
    label,
    raw_value,
    variable_id,
    variable_key,
    variable_unique_key,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WebcardLX text entities."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[TextEntity] = []
        for variable in coordinator.data.get("variables", {}).values():
            if not _is_text_variable(variable):
                continue
            entity = WebcardLXVariableText(coordinator, variable)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)
        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


def _is_text_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable should be represented as text."""
    if attributes.get("password") or not is_editable_variable(attributes):
        return False
    if as_bool(raw_value(attributes)) is not None or enum_options(attributes):
        return False
    data_type = str(attributes.get("data_type") or "").upper()
    return data_type not in {"VARTYPE_INTEGER", "VARTYPE_FLOAT"} and not attributes.get("numeric")


class WebcardLXVariableText(WebcardLXEntity, TextEntity):
    """Text entity for an editable string variable."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: Any, variable: Mapping[str, Any]) -> None:
        """Initialize the text entity."""
        self._variable_key = variable_key(variable)
        self._attr_name = label(variable, "Setting")
        if (max_length := as_int(variable.get("max_length"))) is not None:
            self._attr_native_max = max_length
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_variable_"
            f"{variable_unique_key(variable)}_text"
        )

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current variable attributes."""
        return self.coordinator.data.get("variables", {}).get(self._variable_key, {})

    @property
    def available(self) -> bool:
        """Return whether the variable exists."""
        return super().available and _is_text_variable(self._variable)

    @property
    def native_value(self) -> str | None:
        """Return the current text value."""
        value = raw_value(self._variable)
        return str(value) if value not in (None, "") else None

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        var = self._variable
        if not _is_text_variable(var):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="variable_not_editable",
            )
        try:
            await self.coordinator.client.async_update_variable(variable_id(var), value)
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="variable_update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
