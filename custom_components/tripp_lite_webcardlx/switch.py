"""Switch platform for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOAD_ACTION_OFF, LOAD_ACTION_ON, LOAD_STATE_MIXED, LOAD_STATE_ON
from .coordinator import WebcardLXRuntimeData
from .entity import WebcardLXEntity, entity_device_id
from .helpers import (
    as_bool,
    is_editable_variable,
    is_main_load,
    label,
    load_action_supported,
    load_id,
    load_key,
    raw_value,
    stable_unique_suffix,
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
    """Set up WebcardLX switches."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[SwitchEntity] = []
        for load in coordinator.data.get("loads", {}).values():
            if not load_action_supported(coordinator.data.get("actions_supported", {}), load):
                continue
            entity = WebcardLXLoadSwitch(coordinator, load)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        for variable in coordinator.data.get("variables", {}).values():
            if not _is_switch_variable(variable):
                continue
            entity = WebcardLXVariableSwitch(coordinator, variable)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


def _is_switch_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable should be represented as a switch."""
    if attributes.get("password") or not is_editable_variable(attributes):
        return False
    return as_bool(raw_value(attributes)) is not None


class WebcardLXLoadSwitch(WebcardLXEntity, SwitchEntity):
    """Switch for a controllable UPS load."""

    def __init__(self, coordinator: Any, load: Mapping[str, Any]) -> None:
        """Initialize the load switch."""
        self._load_id = load_id(load)
        self._load_key = load_key(load)
        self._is_main = is_main_load(load)
        self._attr_name = label(load, "Load")
        device_id_value = entity_device_id(load)
        super().__init__(
            coordinator,
            device_id_value,
            None if self._is_main else self._load_key,
            load,
        )
        suffix = "main" if self._is_main else stable_unique_suffix(self._load_id, "load")
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_load_{suffix}_switch"
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
            and bool(self._load)
            and load_action_supported(
                self.coordinator.data.get("actions_supported", {}),
                self._load,
            )
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the load is on."""
        state = self._load.get("state")
        if state == LOAD_STATE_ON:
            return True
        if state == LOAD_STATE_MIXED:
            return True
        if state:
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return load attributes."""
        return {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the load."""
        await self._async_execute(LOAD_ACTION_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the load."""
        await self._async_execute(LOAD_ACTION_OFF)

    async def _async_execute(self, action: str) -> None:
        """Execute a load action."""
        load = self._load
        if not load_action_supported(self.coordinator.data.get("actions_supported", {}), load):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_action_not_supported",
            )
        try:
            if self._is_main:
                await self.coordinator.client.async_execute_main_load(self._device_id, action)
            else:
                await self.coordinator.client.async_execute_load(
                    self._load_id,
                    self._device_id,
                    action,
                )
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class WebcardLXVariableSwitch(WebcardLXEntity, SwitchEntity):
    """Switch for an editable boolean variable."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: Any, variable: Mapping[str, Any]) -> None:
        """Initialize the variable switch."""
        self._variable_key = variable_key(variable)
        self._attr_name = label(variable, "Setting")
        device_id_value = entity_device_id(variable)
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_variable_"
            f"{variable_unique_key(variable)}_switch"
        )

    @property
    def _variable(self) -> Mapping[str, Any]:
        """Return current variable attributes."""
        return self.coordinator.data.get("variables", {}).get(self._variable_key, {})

    @property
    def available(self) -> bool:
        """Return whether the variable exists."""
        return super().available and _is_switch_variable(self._variable)

    @property
    def is_on(self) -> bool | None:
        """Return the switch state."""
        return as_bool(raw_value(self._variable))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the setting."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        """Set the variable value."""
        if not _is_switch_variable(self._variable):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="variable_not_editable",
            )
        try:
            await self.coordinator.client.async_update_variable(
                variable_id(self._variable),
                str(value).lower(),
            )
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="variable_update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
