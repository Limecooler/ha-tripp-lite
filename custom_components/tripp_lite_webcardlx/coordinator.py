"""Data coordinator for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXClient,
    WebcardLXInvalidAuth,
    WebcardLXUnsupportedModel,
)
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENTS_REFRESH_INTERVAL,
    STATIC_DATA_REFRESH_INTERVAL,
)
from .helpers import (
    device_id,
    discovered_models,
    is_sensitive_attributes,
    load_key,
    supported_device_ids,
    variable_key,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class WebcardLXRuntimeData:
    """Runtime data stored on the config entry."""

    client: WebcardLXClient
    coordinator: WebcardLXDataUpdateCoordinator


WebcardLXData = dict[str, Any]


class WebcardLXDataUpdateCoordinator(DataUpdateCoordinator[WebcardLXData]):
    """Fetch and hold WebcardLX state."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: WebcardLXClient,
    ) -> None:
        """Initialize the coordinator."""
        options = getattr(config_entry, "options", {}) or {}
        scan_interval = int(
            options.get(
                "scan_interval",
                config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.client = client
        self._was_unavailable = False
        self._optional_failures: set[str] = set()
        self._last_optional_data: dict[str, Any] = {}
        self._static_data: dict[str, Any] = {}
        self._events: dict[str, Any] = {}
        self._next_static_refresh = 0.0
        self._next_events_refresh = 0.0

    async def _async_update_data(self) -> WebcardLXData:
        """Fetch data from the WebcardLX."""
        try:
            data = await self._async_fetch_data()
        except WebcardLXInvalidAuth as err:
            raise ConfigEntryAuthFailed("WebcardLX authentication failed") from err
        except WebcardLXCannotConnect as err:
            if not self._was_unavailable:
                _LOGGER.warning("WebcardLX is unavailable: %s", err)
                self._was_unavailable = True
            raise UpdateFailed(str(err)) from err
        except WebcardLXApiError as err:
            raise UpdateFailed(f"WebcardLX API error {err.status}") from err
        except WebcardLXUnsupportedModel as err:
            raise UpdateFailed(str(err)) from err

        if self._was_unavailable:
            _LOGGER.info("WebcardLX connection restored")
            self._was_unavailable = False
        return data

    async def _async_fetch_data(self) -> WebcardLXData:
        """Fetch and normalize all integration data."""
        now = monotonic()
        devices = await self.client.async_get_devices()
        variables = await self.client.async_get_variables()

        if not self._static_data or now >= self._next_static_refresh:
            self._static_data = await self._async_fetch_static_data()
            self._next_static_refresh = now + STATIC_DATA_REFRESH_INTERVAL

        control_variables = self._static_data.get("control_variables", [])
        if control_variables:
            by_id = {variable_key(item): item for item in variables if variable_key(item)}
            for item in control_variables:
                item_id = variable_key(item)
                if item_id:
                    by_id[item_id] = {**by_id.get(item_id, {}), **item}
            variables = list(by_id.values())

        active_device_ids = supported_device_ids(
            devices,
            variables,
            allow_unsupported_model=True,
        )
        if not active_device_ids:
            raise WebcardLXUnsupportedModel(discovered_models(devices))

        filtered_devices = {
            device_id(device): device
            for device in devices
            if device_id(device) in active_device_ids
        }
        filtered_variables = {
            variable_key(variable): variable
            for variable in variables
            if variable_key(variable)
            and device_id(variable) in active_device_ids
            and not is_sensitive_attributes(variable)
        }

        loads, alarm_summary, alarms, ready, system_uptime = await asyncio.gather(
            self._async_optional("loads", self.client.async_get_loads, []),
            self._async_optional("alarm_summary", self.client.async_get_alarm_summary, {}),
            self._async_optional("alarms", self.client.async_get_alarms, []),
            self._async_optional("ready", self.client.async_get_ready, {}),
            self._async_optional("system_uptime", self.client.async_get_system_uptime, {}),
        )
        filtered_loads = {
            load_key(load): load
            for load in loads
            if load_key(load)
            and device_id(load) in active_device_ids
            and load.get("device_type", "DEVICE_TYPE_UPS") == "DEVICE_TYPE_UPS"
        }

        if not self._events or now >= self._next_events_refresh:
            self._events = {
                str(event.get("id")): event
                for event in await self._async_optional("events", self.client.async_get_events, [])
                if event.get("id") not in (None, "")
            }
            self._next_events_refresh = now + EVENTS_REFRESH_INTERVAL

        data: WebcardLXData = {
            "devices": filtered_devices,
            "variables": filtered_variables,
            "loads": filtered_loads,
            "load_groups": self._filtered_load_groups(active_device_ids),
            "actions_supported": self._static_data.get("actions_supported", {}),
            "schedules_supported": self._static_data.get("schedules_supported", {}),
            "alarm_summary": alarm_summary,
            "alarms": {
                str(alarm.get("id")): alarm
                for alarm in alarms
                if alarm.get("id") not in (None, "")
            },
            "events": self._events,
            "ready": ready,
            "system_details": self._static_data.get("system_details", {}),
            "system_uptime": system_uptime,
        }
        return data

    async def _async_fetch_static_data(self) -> dict[str, Any]:
        """Fetch slow-changing optional metadata."""
        (
            control_variables,
            load_groups,
            actions_supported,
            schedules_supported,
            system_details,
        ) = await asyncio.gather(
            self._async_optional("control_variables", self.client.async_get_control_variables, []),
            self._async_optional("load_groups", self.client.async_get_load_groups, []),
            self._async_optional("actions_supported", self.client.async_get_supported_actions, {}),
            self._async_optional(
                "schedules_supported", self.client.async_get_supported_schedules, {}
            ),
            self._async_optional("system_details", self.client.async_get_system_details, {}),
        )
        return {
            "control_variables": control_variables,
            "load_groups": load_groups,
            "actions_supported": actions_supported,
            "schedules_supported": schedules_supported,
            "system_details": system_details,
        }

    async def _async_optional(self, name: str, fetch: Any, default: Any) -> Any:
        """Fetch optional API data without failing the whole coordinator update."""
        try:
            result = await fetch()
        except WebcardLXInvalidAuth:
            raise
        except (WebcardLXApiError, WebcardLXCannotConnect) as err:
            if name not in self._optional_failures:
                _LOGGER.warning("WebcardLX optional endpoint %s failed: %s", name, err)
                self._optional_failures.add(name)
            if name in self._last_optional_data:
                cached = self._last_optional_data[name]
                return cached.copy() if isinstance(cached, dict | list | set) else cached
            return default.copy() if isinstance(default, dict | list | set) else default

        if name in self._optional_failures:
            _LOGGER.info("WebcardLX optional endpoint %s recovered", name)
            self._optional_failures.remove(name)
        self._last_optional_data[name] = (
            result.copy() if isinstance(result, dict | list | set) else result
        )
        return result

    def _filtered_load_groups(self, active_device_ids: set[str]) -> dict[str, Any]:
        """Return load groups for active UPS devices."""
        return {
            load_key(group): group
            for group in self._static_data.get("load_groups", [])
            if load_key(group) and device_id(group) in active_device_ids
        }
