"""Entity helpers for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import WebcardLXDataUpdateCoordinator
from .helpers import device_id, label, load_id, load_key


class WebcardLXEntity(CoordinatorEntity[WebcardLXDataUpdateCoordinator]):
    """Base entity for WebcardLX entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WebcardLXDataUpdateCoordinator,
        device_id_value: str,
        load_key_value: str | None = None,
        load_attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id_value
        self._device_info_load_key = load_key_value
        self._load_for_device_info = dict(load_attributes or {})
        self._cached_device: Mapping[str, Any] = (
            coordinator.data.get("devices", {}).get(device_id_value, {})
            if coordinator.data
            else {}
        )
        self._attr_device_info = self._build_device_info()

    def _build_device_info(self) -> DeviceInfo:
        """Build and return device registry information."""
        if self._device_info_load_key is not None:
            current_load = (
                self.coordinator.data.get("loads", {}).get(self._device_info_load_key, {})
                if self.coordinator.data
                else {}
            )
            return load_device_info(
                self.coordinator.config_entry.unique_id,
                self._device_id,
                current_load or self._load_for_device_info,
            )
        device = self._cached_device
        serial_number = str(device.get("serial_number") or "").strip()
        return DeviceInfo(
            identifiers=device_identifiers(
                self.coordinator.config_entry.unique_id,
                self._device_id,
                device,
            ),
            manufacturer=str(device.get("manufacturer") or MANUFACTURER),
            model=str(device.get("model") or ""),
            name=str(device.get("name") or f"UPS {self._device_id}"),
            serial_number=serial_number or None,
            sw_version=str(device.get("protocol") or "") or None,
            configuration_url=self.coordinator.client.base_url,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator and refresh cached state."""
        self._cached_device = self.coordinator.data.get("devices", {}).get(self._device_id, {})
        self._attr_device_info = self._build_device_info()
        super()._handle_coordinator_update()

    @property
    def _device(self) -> Mapping[str, Any]:
        """Return device attributes."""
        return self._cached_device

    @property
    def _load(self) -> Mapping[str, Any]:
        """Return load attributes."""
        if self._device_info_load_key is None:
            return {}
        return self.coordinator.data.get("loads", {}).get(self._device_info_load_key, {})


def entity_device_id(attributes: Mapping[str, Any]) -> str:
    """Return a valid entity device id."""
    return device_id(attributes)


def fallback_device_identifier(entry_unique_id: str, device_id_value: str) -> tuple[str, str]:
    """Return the stable fallback device identifier."""
    return (DOMAIN, f"{entry_unique_id}_{device_id_value}")


def device_identifiers(
    entry_unique_id: str,
    device_id_value: str,
    device: Mapping[str, Any],
) -> set[tuple[str, str]]:
    """Return all known identifiers for a UPS device."""
    identifiers = {fallback_device_identifier(entry_unique_id, device_id_value)}
    serial_number = str(device.get("serial_number") or "").strip()
    if serial_number:
        identifiers.add((DOMAIN, serial_number))
    return identifiers


def device_connections(system_details: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Return network connections from card system details."""
    mac_address = str(
        system_details.get("mac")
        or system_details.get("mac_address")
        or ""
    ).strip()
    return {(CONNECTION_NETWORK_MAC, mac_address.lower())} if mac_address else set()


def load_device_identifier(
    entry_unique_id: str,
    device_id_value: str,
    load: Mapping[str, Any],
) -> tuple[str, str]:
    """Return the stable child load device identifier."""
    current_load_id = load_id(load) or load_key(load)
    return (DOMAIN, f"{entry_unique_id}_{device_id_value}_load_{current_load_id}")


def load_device_info(
    entry_unique_id: str,
    device_id_value: str,
    load: Mapping[str, Any],
) -> DeviceInfo:
    """Return device info for a controllable or monitored load."""
    return DeviceInfo(
        identifiers={load_device_identifier(entry_unique_id, device_id_value, load)},
        name=label(load, "Load"),
        manufacturer=MANUFACTURER,
        via_device=fallback_device_identifier(entry_unique_id, device_id_value),
    )
