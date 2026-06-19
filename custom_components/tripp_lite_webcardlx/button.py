"""Button platform for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOAD_ACTION_CYCLE
from .coordinator import WebcardLXRuntimeData
from .entity import WebcardLXEntity, entity_device_id
from .helpers import (
    action_supports_device,
    is_main_load,
    label,
    load_action_supported,
    load_id,
    load_key,
    stable_unique_suffix,
)

PARALLEL_UPDATES = 0

DEVICE_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("turn_on", "Turn on", "turn_on_ups", "turn_on_device_supported"),
    ("turn_off", "Turn off", "turn_off_ups", "turn_off_device_supported"),
    ("reboot", "Reboot", "reboot_ups", "restart_device_supported"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WebcardLX buttons."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    coordinator = runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        entities: list[ButtonEntity] = []
        supported_actions = coordinator.data.get("actions_supported", {})

        for load in coordinator.data.get("loads", {}).values():
            if not load_action_supported(supported_actions, load):
                continue
            entity = WebcardLXLoadCycleButton(coordinator, load)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        for current_device_id in coordinator.data.get("devices", {}):
            for action, name, translation_key, support_key in DEVICE_ACTIONS:
                if not action_supports_device(supported_actions, support_key, current_device_id):
                    continue
                entity = WebcardLXDeviceActionButton(
                    coordinator,
                    current_device_id,
                    action,
                    name,
                    translation_key,
                    support_key,
                )
                if entity.unique_id not in known_unique_ids:
                    known_unique_ids.add(entity.unique_id)
                    entities.append(entity)

        first_device_id = next(iter(coordinator.data.get("devices", {})), "")
        if first_device_id and coordinator.data.get("alarm_summary"):
            entity = WebcardLXAcknowledgeAlarmsButton(coordinator, first_device_id)
            if entity.unique_id not in known_unique_ids:
                known_unique_ids.add(entity.unique_id)
                entities.append(entity)

        if entities:
            async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class WebcardLXActionButton(WebcardLXEntity, ButtonEntity):
    """Base action button."""

    async def _async_press_with_error_handling(
        self,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        """Run a button action and refresh data."""
        try:
            await action()
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="button_action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class WebcardLXLoadCycleButton(WebcardLXActionButton):
    """Button to power-cycle a UPS load."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: Any, load: Mapping[str, Any]) -> None:
        """Initialize the load cycle button."""
        self._load_id = load_id(load)
        self._load_key = load_key(load)
        self._is_main = is_main_load(load)
        load_name = label(load, "Load")
        self._attr_name = "Cycle" if not self._is_main else f"Cycle {load_name}"
        self._attr_translation_key = "cycle_load"
        self._attr_translation_placeholders = {"load_name": load_name}
        device_id_value = entity_device_id(load)
        super().__init__(
            coordinator,
            device_id_value,
            None if self._is_main else self._load_key,
            load,
        )
        suffix = "main" if self._is_main else stable_unique_suffix(self._load_id, "load")
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_load_{suffix}_cycle"
        )

    @property
    def available(self) -> bool:
        """Return whether the cycle action is currently available."""
        return super().available and load_action_supported(
            self.coordinator.data.get("actions_supported", {}),
            self.coordinator.data.get("loads", {}).get(self._load_key, {}),
        )

    async def async_press(self) -> None:
        """Cycle the load."""
        load = self.coordinator.data.get("loads", {}).get(self._load_key, {})
        if not load_action_supported(self.coordinator.data.get("actions_supported", {}), load):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_action_not_supported",
            )
        if self._is_main:
            await self._async_press_with_error_handling(
                lambda: self.coordinator.client.async_execute_main_load(
                    self._device_id,
                    LOAD_ACTION_CYCLE,
                )
            )
        else:
            await self._async_press_with_error_handling(
                lambda: self.coordinator.client.async_execute_load(
                    self._load_id,
                    self._device_id,
                    LOAD_ACTION_CYCLE,
                )
            )


class WebcardLXDeviceActionButton(WebcardLXActionButton):
    """Button for UPS device controls."""

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: Any,
        device_id_value: str,
        action: str,
        name: str,
        translation_key: str,
        support_key: str,
    ) -> None:
        """Initialize the device action button."""
        super().__init__(coordinator, device_id_value)
        self._action = action
        self._support_key = support_key
        self._attr_name = name
        self._attr_translation_key = translation_key
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}_{device_id_value}_device_action_{action}"
        )

    @property
    def available(self) -> bool:
        """Return whether this device action is currently supported."""
        return super().available and action_supports_device(
            self.coordinator.data.get("actions_supported", {}),
            self._support_key,
            self._device_id,
        )

    async def async_press(self) -> None:
        """Execute the device action."""
        if not action_supports_device(
            self.coordinator.data.get("actions_supported", {}),
            self._support_key,
            self._device_id,
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_action_not_supported",
            )
        await self._async_press_with_error_handling(
            lambda: self.coordinator.client.async_control_device(self._action, self._device_id)
        )


class WebcardLXAcknowledgeAlarmsButton(WebcardLXActionButton):
    """Button to acknowledge all alarms."""

    _attr_name = "Acknowledge all alarms"
    _attr_translation_key = "acknowledge_all_alarms"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Any, device_id_value: str) -> None:
        """Initialize the acknowledge all alarms button."""
        super().__init__(coordinator, device_id_value)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_acknowledge_all_alarms"

    async def async_press(self) -> None:
        """Acknowledge all alarms."""
        await self._async_press_with_error_handling(
            self.coordinator.client.async_acknowledge_all_alarms
        )
