"""Tripp Lite WebcardLX integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import (
    config_validation as cv,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import service as service_helper
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import WebcardLXApiError, WebcardLXCannotConnect, WebcardLXClient, WebcardLXInvalidAuth
from .const import (
    ATTR_ACTION,
    ATTR_ALARM_IDS,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DELAY,
    ATTR_TOLERANCE,
    ATTR_TURN_OFF_DELAY,
    ATTR_TURN_ON_DELAY,
    ATTR_VALUE,
    CONF_ALLOW_UNSUPPORTED_MODEL,
    CONF_URL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
    SERVICE_LOAD_ACTIONS,
)
from .coordinator import WebcardLXDataUpdateCoordinator, WebcardLXRuntimeData
from .entity import device_identifiers, load_device_identifier
from .helpers import (
    action_supports_device,
    as_bool,
    as_float,
    enum_options,
    is_editable_variable,
    is_main_load,
    load_action_supported,
    load_id,
    stable_unique_suffix,
    variable_id,
    variable_unique_key,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_EXECUTE_LOAD_ACTION = "execute_load_action"
SERVICE_EXECUTE_DEVICE_ACTION = "execute_device_action"
SERVICE_ACKNOWLEDGE_ALARMS = "acknowledge_alarms"
SERVICE_ACKNOWLEDGE_ALL_ALARMS = "acknowledge_all_alarms"
SERVICE_SET_VARIABLE = "set_variable"
SERVICE_UPDATE_DEVICE_PROPERTIES = "update_device_properties"

DEVICE_ACTION_SUPPORT_KEYS = {
    "turn_on": "turn_on_device_supported",
    "turn_off": "turn_off_device_supported",
    "reboot": "restart_device_supported",
}

VARIABLE_ENTITY_DOMAINS = {"number", "select", "switch", "text"}
DEVICE_PROPERTY_FIELDS = {
    "name",
    "location",
    "region",
    "configured_device_id",
    "configured_asset_tag",
    "install_date",
}

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-level services."""
    async_register_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry data to the current schema."""
    if entry.version != 1:
        _LOGGER.error(
            "Unsupported config entry version %s for %s",
            entry.version,
            DOMAIN,
        )
        return False
    if getattr(entry, "minor_version", 1) >= 2:
        return True

    data = dict(entry.data)
    options = dict(entry.options)
    for key in (CONF_SCAN_INTERVAL, CONF_ALLOW_UNSUPPORTED_MODEL):
        if key in data:
            options.setdefault(key, data.pop(key))

    hass.config_entries.async_update_entry(entry, data=data, options=options, minor_version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tripp Lite WebcardLX from a config entry."""
    session = async_get_clientsession(
        hass,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    client = WebcardLXClient(
        session,
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    try:
        await client.async_login()
    except WebcardLXInvalidAuth as err:
        raise ConfigEntryAuthFailed("WebcardLX authentication failed") from err
    except WebcardLXCannotConnect as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = WebcardLXDataUpdateCoordinator(hass, entry, client)
    runtime_data = WebcardLXRuntimeData(client=client, coordinator=coordinator)

    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = runtime_data
        await _async_remove_stale_devices(hass, entry, coordinator)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        if getattr(entry, "runtime_data", None) is runtime_data:
            entry.runtime_data = None
        await client.async_logout()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    cancel_stale_listener = coordinator.async_add_listener(
        lambda: hass.async_create_task(_async_remove_stale_devices(hass, entry, coordinator))
    )
    runtime_data.cancel_stale_listener = cancel_stale_listener

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime_data: WebcardLXRuntimeData = entry.runtime_data
    # Cancel the coordinator listener before unloading platforms so it does not
    # fire stale-device cleanup while entities are being torn down.
    cancel = getattr(runtime_data, "cancel_stale_listener", None)
    if cancel is not None:
        cancel()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await runtime_data.client.async_logout()
        entry.runtime_data = None
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_remove_stale_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WebcardLXDataUpdateCoordinator,
) -> None:
    """Remove stale devices from the device registry."""
    if "loads" in getattr(coordinator, "_optional_failures", set()):
        return
    registry = dr.async_get(hass)
    valid_identifiers: set[tuple[str, str]] = set()
    for device_id, device in coordinator.data.get("devices", {}).items():
        valid_identifiers.update(device_identifiers(entry.unique_id, device_id, device))
    for load in coordinator.data.get("loads", {}).values():
        current_device_id = str(load.get("device_id") or "")
        if current_device_id and not is_main_load(load):
            valid_identifiers.add(load_device_identifier(entry.unique_id, current_device_id, load))

    for device_entry in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device_entry.identifiers.intersection(valid_identifiers):
            registry.async_remove_device(device_entry.id)


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    if hass.services.has_service(DOMAIN, SERVICE_EXECUTE_LOAD_ACTION):
        return

    async def execute_load_action(call: ServiceCall) -> None:
        action = SERVICE_LOAD_ACTIONS[call.data[ATTR_ACTION]]
        refreshed: dict[int, WebcardLXRuntimeData] = {}
        for runtime_data, load in await _load_targets_from_call(hass, call):
            if not load_action_supported(
                runtime_data.coordinator.data.get("actions_supported", {}),
                load,
                runtime_data.coordinator.data.get("_controllable_load_ids"),
            ):
                raise _service_error("load_action_not_supported")
            current_device_id = str(load.get("device_id"))
            current_load_id = load_id(load)
            if is_main_load(load):
                await runtime_data.client.async_execute_main_load(current_device_id, action)
            else:
                await runtime_data.client.async_execute_load(
                    current_load_id,
                    current_device_id,
                    action,
                )
            refreshed[id(runtime_data)] = runtime_data
        await _refresh_runtimes(refreshed.values())

    async def execute_device_action(call: ServiceCall) -> None:
        action = call.data[ATTR_ACTION]
        refreshed: dict[int, WebcardLXRuntimeData] = {}
        for runtime_data, device_id_value in _device_targets_from_call(hass, call):
            support_key = DEVICE_ACTION_SUPPORT_KEYS[action]
            if not action_supports_device(
                runtime_data.coordinator.data.get("actions_supported", {}),
                support_key,
                device_id_value,
            ):
                raise _service_error("device_action_not_supported")
            await runtime_data.client.async_control_device(
                action,
                device_id_value,
                call.data.get(ATTR_TURN_ON_DELAY, call.data.get(ATTR_DELAY)),
                call.data.get(ATTR_TURN_OFF_DELAY, call.data.get(ATTR_DELAY)),
            )
            refreshed[id(runtime_data)] = runtime_data
        await _refresh_runtimes(refreshed.values())

    async def acknowledge_alarms(call: ServiceCall) -> None:
        runtime_data = _runtime_data_from_config_entry_id(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        alarm_ids = [str(item) for item in call.data[ATTR_ALARM_IDS]]
        known_alarm_ids = set(runtime_data.coordinator.data.get("alarms", {}))
        unknown_alarm_ids = set(alarm_ids) - known_alarm_ids
        if unknown_alarm_ids:
            raise _service_error(
                "alarm_not_found",
                {"alarm_ids": ", ".join(sorted(unknown_alarm_ids))},
            )
        await runtime_data.client.async_acknowledge_alarms(alarm_ids)
        await runtime_data.coordinator.async_request_refresh()

    async def acknowledge_all_alarms(call: ServiceCall) -> None:
        runtime_data = _runtime_data_from_config_entry_id(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await runtime_data.client.async_acknowledge_all_alarms()
        await runtime_data.coordinator.async_request_refresh()

    async def set_variable(call: ServiceCall) -> None:
        refreshed: dict[int, WebcardLXRuntimeData] = {}
        for runtime_data, entity_domain, variable in await _variable_targets_from_call(hass, call):
            value = _validated_variable_value(entity_domain, variable, call.data[ATTR_VALUE])
            await runtime_data.client.async_update_variable(
                variable_id(variable),
                value,
                call.data.get(ATTR_TOLERANCE),
            )
            refreshed[id(runtime_data)] = runtime_data
        await _refresh_runtimes(refreshed.values())

    async def update_device_properties(call: ServiceCall) -> None:
        attributes = {
            key: call.data[key]
            for key in DEVICE_PROPERTY_FIELDS
            if call.data.get(key) is not None
        }
        if not attributes:
            raise _service_error("no_device_properties")
        refreshed: dict[int, WebcardLXRuntimeData] = {}
        for runtime_data, device_id_value in _device_targets_from_call(hass, call):
            await runtime_data.client.async_update_device(device_id_value, attributes)
            refreshed[id(runtime_data)] = runtime_data
        await _refresh_runtimes(refreshed.values())

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_LOAD_ACTION,
        _wrap_service_errors(execute_load_action),
        schema=cv.make_entity_service_schema(
            {
                vol.Required(ATTR_ACTION): vol.In(sorted(SERVICE_LOAD_ACTIONS)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_DEVICE_ACTION,
        _wrap_service_errors(execute_device_action),
        schema=cv.make_entity_service_schema(
            {
                vol.Required(ATTR_ACTION): vol.In(sorted(DEVICE_ACTION_SUPPORT_KEYS)),
                vol.Optional(ATTR_DELAY, default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
                vol.Optional(ATTR_TURN_ON_DELAY): vol.All(vol.Coerce(int), vol.Range(min=0)),
                vol.Optional(ATTR_TURN_OFF_DELAY): vol.All(vol.Coerce(int), vol.Range(min=0)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_ALARMS,
        _wrap_service_errors(acknowledge_alarms),
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required(ATTR_ALARM_IDS): vol.All(cv.ensure_list, [cv.string]),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_ALL_ALARMS,
        _wrap_service_errors(acknowledge_all_alarms),
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_VARIABLE,
        _wrap_service_errors(set_variable),
        schema=cv.make_entity_service_schema(
            {
                vol.Required(ATTR_VALUE): cv.match_all,
                vol.Optional(ATTR_TOLERANCE): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_DEVICE_PROPERTIES,
        _wrap_service_errors(update_device_properties),
        schema=cv.make_entity_service_schema(
            {
                vol.Optional("name"): cv.string,
                vol.Optional("location"): cv.string,
                vol.Optional("region"): cv.string,
                vol.Optional("configured_device_id"): cv.string,
                vol.Optional("configured_asset_tag"): cv.string,
                vol.Optional("install_date"): cv.string,
            },
        ),
    )


def _runtime_data_from_config_entry_id(
    hass: HomeAssistant,
    entry_id: str,
) -> WebcardLXRuntimeData:
    """Return runtime data for an explicit config entry ID."""
    entry = _entry_from_id(hass, entry_id)
    if entry is None or getattr(entry, "runtime_data", None) is None:
        raise _service_error("entry_not_found")
    return entry.runtime_data


def _entry_from_id(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    """Return a loaded config entry by ID."""
    if hasattr(hass.config_entries, "async_get_entry"):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and getattr(entry, "domain", DOMAIN) == DOMAIN:
            return entry
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            return entry
    return None


async def _load_targets_from_call(
    hass: HomeAssistant,
    call: ServiceCall,
) -> list[tuple[WebcardLXRuntimeData, dict[str, Any]]]:
    """Resolve targeted load switch entities."""
    entity_registry = er.async_get(hass)
    targets = []
    for entity_id in sorted(await service_helper.async_extract_entity_ids(hass, call)):
        entity_entry = entity_registry.async_get(entity_id)
        entity_domain = str(entity_id).split(".", 1)[0]
        if entity_domain != "switch" or entity_entry is None:
            raise _service_error("invalid_target")
        runtime_data, entry_unique_id = _runtime_data_from_entity_entry(hass, entity_entry)
        load = _load_from_unique_id(runtime_data, entry_unique_id, entity_entry.unique_id)
        if load is None:
            raise _service_error("invalid_target")
        targets.append((runtime_data, load))
    if not targets:
        raise _service_error("invalid_target")
    return targets


async def _variable_targets_from_call(
    hass: HomeAssistant,
    call: ServiceCall,
) -> list[tuple[WebcardLXRuntimeData, str, dict[str, Any]]]:
    """Resolve targeted variable configuration entities."""
    entity_registry = er.async_get(hass)
    targets = []
    for entity_id in sorted(await service_helper.async_extract_entity_ids(hass, call)):
        entity_entry = entity_registry.async_get(entity_id)
        entity_domain = str(entity_id).split(".", 1)[0]
        if entity_domain not in VARIABLE_ENTITY_DOMAINS or entity_entry is None:
            raise _service_error("invalid_target")
        runtime_data, entry_unique_id = _runtime_data_from_entity_entry(hass, entity_entry)
        variable = _variable_from_unique_id(
            runtime_data,
            entry_unique_id,
            entity_entry.unique_id,
            entity_domain,
        )
        if variable is None:
            raise _service_error("invalid_target")
        targets.append((runtime_data, entity_domain, variable))
    if not targets:
        raise _service_error("invalid_target")
    return targets


def _device_targets_from_call(
    hass: HomeAssistant,
    call: ServiceCall,
) -> list[tuple[WebcardLXRuntimeData, str]]:
    """Resolve targeted Home Assistant UPS devices to WebcardLX device IDs."""
    registry = dr.async_get(hass)
    referenced = service_helper.async_extract_referenced_entity_ids(hass, call)
    ha_device_ids = set(referenced.referenced_devices)
    entity_registry = er.async_get(hass)
    for entity_id in referenced.referenced | referenced.indirectly_referenced:
        if (entity_entry := entity_registry.async_get(entity_id)) is not None:
            if entity_entry.device_id:
                ha_device_ids.add(entity_entry.device_id)
    if not ha_device_ids:
        raise _service_error("invalid_target")

    targets = []
    for ha_device_id in sorted(ha_device_ids):
        device_entry = registry.async_get(ha_device_id)
        if device_entry is None:
            raise _service_error("invalid_target")
        found = False
        for entry_id in getattr(device_entry, "config_entries", set()):
            entry = _entry_from_id(hass, entry_id)
            if entry is None or getattr(entry, "runtime_data", None) is None:
                continue
            runtime_data: WebcardLXRuntimeData = entry.runtime_data
            for device_id_value, device in runtime_data.coordinator.data.get("devices", {}).items():
                identifiers = device_identifiers(entry.unique_id, device_id_value, device)
                if identifiers.intersection(device_entry.identifiers):
                    targets.append((runtime_data, device_id_value))
                    found = True
                    break
        if not found:
            raise _service_error("invalid_target")
    return targets


def _runtime_data_from_entity_entry(
    hass: HomeAssistant,
    entity_entry: Any,
) -> tuple[WebcardLXRuntimeData, str]:
    """Return runtime data and entry unique ID for an entity registry entry."""
    entry = _entry_from_id(hass, entity_entry.config_entry_id)
    if entry is None or getattr(entry, "runtime_data", None) is None:
        raise _service_error("entry_not_found")
    return entry.runtime_data, entry.unique_id


def _load_from_unique_id(
    runtime_data: WebcardLXRuntimeData,
    entry_unique_id: str,
    unique_id: str,
) -> dict[str, Any] | None:
    """Return a load matching a load switch unique ID."""
    # Fast O(1) path using the pre-computed reverse lookup map.
    load_uid_map = runtime_data.coordinator.data.get("_load_uid_map")
    if load_uid_map is not None:
        lkey = load_uid_map.get(unique_id)
        if lkey is not None:
            load = runtime_data.coordinator.data.get("loads", {}).get(lkey)
            if load is not None:
                return dict(load)
        return None
    # Fallback O(N) scan for startup or missing map.
    for load in runtime_data.coordinator.data.get("loads", {}).values():
        device_id_value = str(load.get("device_id") or "")
        suffix = "main" if is_main_load(load) else stable_unique_suffix(load_id(load), "load")
        if unique_id == f"{entry_unique_id}_{device_id_value}_load_{suffix}_switch":
            return dict(load)
    return None


def _variable_from_unique_id(
    runtime_data: WebcardLXRuntimeData,
    entry_unique_id: str,
    unique_id: str,
    entity_domain: str,
) -> dict[str, Any] | None:
    """Return a variable matching a config entity unique ID."""
    # Fast O(1) path using the pre-computed reverse lookup map.
    variable_uid_map = runtime_data.coordinator.data.get("_variable_uid_map")
    if variable_uid_map is not None:
        vkey = variable_uid_map.get(unique_id)
        if vkey is not None:
            variable = runtime_data.coordinator.data.get("variables", {}).get(vkey)
            if variable is not None:
                return dict(variable)
        return None
    # Fallback O(N) scan for startup or missing map.
    for variable in runtime_data.coordinator.data.get("variables", {}).values():
        if variable.get("password") or not is_editable_variable(variable):
            continue
        device_id_value = str(variable.get("device_id") or "")
        expected = (
            f"{entry_unique_id}_{device_id_value}_variable_"
            f"{variable_unique_key(variable)}_{entity_domain}"
        )
        if unique_id == expected:
            return dict(variable)
    return None


def _validated_variable_value(entity_domain: str, variable: dict[str, Any], value: Any) -> Any:
    """Return a value validated for the target variable entity domain."""
    if entity_domain == "select":
        if str(value) not in enum_options(variable):
            raise _service_error("invalid_select_option")
        return str(value)
    if entity_domain == "number":
        numeric = as_float(value)
        if numeric is None:
            raise _service_error("invalid_variable_value")
        return numeric
    if entity_domain == "switch":
        boolean = as_bool(value)
        if boolean is None:
            raise _service_error("invalid_variable_value")
        return str(boolean).lower()
    return str(value)


async def _refresh_runtimes(runtimes: Any) -> None:
    """Refresh each affected runtime once."""
    for runtime_data in runtimes:
        await runtime_data.coordinator.async_request_refresh()


def _service_error(
    translation_key: str,
    placeholders: dict[str, str] | None = None,
) -> ServiceValidationError:
    """Return a translated service validation error."""
    return ServiceValidationError(
        translation_key,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=placeholders,
    )


def _wrap_service_errors(handler: Any) -> Any:
    """Wrap service errors in Home Assistant service exceptions."""

    async def wrapped(call: ServiceCall) -> None:
        try:
            await handler(call)
        except ServiceValidationError:
            raise
        except WebcardLXApiError as err:
            _LOGGER.debug("WebcardLX API service call failed", exc_info=True)
            raise ServiceValidationError(
                f"WebcardLX API error {err.status}",
                translation_domain=DOMAIN,
                translation_key="service_call_failed",
                translation_placeholders={"error": f"WebcardLX API error {err.status}"},
            ) from err
        except Exception as err:
            _LOGGER.debug("WebcardLX service call failed", exc_info=True)
            raise ServiceValidationError(
                str(err),
                translation_domain=DOMAIN,
                translation_key="service_call_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    return wrapped
