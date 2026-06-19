"""Config flow for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import (
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXClient,
    WebcardLXInvalidAuth,
    WebcardLXUnsupportedModel,
    normalize_base_url,
)
from .const import (
    CONF_ALLOW_UNSUPPORTED_MODEL,
    CONF_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .helpers import discovered_models, supported_device_ids


@dataclass
class ValidationResult:
    """Validated WebcardLX data."""

    title: str
    unique_id: str
    models: list[str]


def _schema(
    defaults: dict[str, Any] | None = None,
    *,
    include_options: bool = True,
    password_required: bool = True,
) -> vol.Schema:
    """Return a config flow schema with defaults."""
    defaults = defaults or {}
    schema: dict[Any, Any] = {
        vol.Required(CONF_URL, default=defaults.get(CONF_URL, "")): str,
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
        (
            vol.Required(CONF_PASSWORD)
            if password_required
            else vol.Optional(CONF_PASSWORD, default="")
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        vol.Optional(
            CONF_VERIFY_SSL,
            default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        ): bool,
    }
    if include_options:
        schema.update(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
                vol.Optional(
                    CONF_ALLOW_UNSUPPORTED_MODEL,
                    default=defaults.get(CONF_ALLOW_UNSUPPORTED_MODEL, False),
                ): bool,
            }
        )
    return vol.Schema(schema)


async def async_validate_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    preferred_unique_id: str | None = None,
) -> ValidationResult:
    """Validate user input and return entry metadata."""
    url = normalize_base_url(user_input[CONF_URL])
    session = async_get_clientsession(
        hass,
        verify_ssl=user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    client = WebcardLXClient(
        session,
        url,
        user_input[CONF_USERNAME],
        user_input[CONF_PASSWORD],
    )
    logged_in = False
    try:
        await client.async_login()
        logged_in = True
        devices = await client.async_get_devices()
        variables = await client.async_get_variables()
        try:
            system_details = await client.async_get_system_details()
        except (WebcardLXApiError, WebcardLXCannotConnect):
            system_details = {}
        active_device_ids = supported_device_ids(
            devices,
            variables,
            allow_unsupported_model=user_input.get(CONF_ALLOW_UNSUPPORTED_MODEL, False),
        )
        models = discovered_models(devices)
        if not active_device_ids:
            raise WebcardLXUnsupportedModel(models)

        selected = next(
            (
                device
                for device in devices
                if str(device.get("device_id", device.get("id"))) in active_device_ids
            ),
            devices[0] if devices else {},
        )
        title = str(selected.get("name") or selected.get("model") or "Tripp Lite WebcardLX")
        mac_address = str(system_details.get("mac_address") or system_details.get("mac") or "")
        unique_id_candidates = [
            mac_address.strip().lower(),
            str(selected.get("serial_number") or "").strip(),
            str(selected.get("configured_asset_tag") or "").strip(),
            url,
        ]
        if preferred_unique_id in unique_id_candidates:
            unique_id = str(preferred_unique_id)
        else:
            unique_id = next(candidate for candidate in unique_id_candidates if candidate)
        return ValidationResult(title=title, unique_id=unique_id, models=models)
    finally:
        if logged_in:
            await client.async_logout()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tripp Lite WebcardLX."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_url: str | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        defaults = {CONF_URL: self._discovered_url or ""}

        if user_input is not None:
            try:
                user_input = dict(user_input)
                options = _options_from_input(user_input)
                data = _data_from_input(user_input)
                result = await async_validate_input(self.hass, {**data, **options})
            except ValueError:
                errors["base"] = "invalid_url"
            except WebcardLXUnsupportedModel:
                errors["base"] = "unsupported_model"
            except WebcardLXInvalidAuth:
                errors["base"] = "invalid_auth"
            except WebcardLXApiError:
                errors["base"] = "cannot_connect"
            except WebcardLXCannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - config flow should show a generic error.
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(result.unique_id)
                self._abort_if_unique_id_configured(updates={CONF_URL: data[CONF_URL]})
                return self.async_create_entry(title=result.title, data=data, options=options)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(defaults),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: Any) -> config_entries.ConfigFlowResult:
        """Handle DHCP discovery."""
        ip_address = getattr(discovery_info, "ip", None)
        hostname = getattr(discovery_info, "hostname", None)
        macaddress = getattr(discovery_info, "macaddress", None)
        if macaddress:
            await self.async_set_unique_id(str(macaddress).lower())
        if hostname:
            self.context["title_placeholders"] = {"name": hostname}
        if ip_address:
            self._discovered_url = f"https://{ip_address}"
        if macaddress:
            self._abort_if_unique_id_configured(
                updates={CONF_URL: self._discovered_url} if self._discovered_url else None
            )
        return await self.async_step_user()

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle reconfiguration."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                user_input = dict(user_input)
                data = dict(entry.data)
                data.update(
                    _data_from_input(
                        user_input,
                        existing_password=entry.data[CONF_PASSWORD],
                    )
                )
                result = await async_validate_input(
                    self.hass,
                    {**data, **dict(entry.options)},
                    preferred_unique_id=getattr(entry, "unique_id", None),
                )
            except ValueError:
                errors["base"] = "invalid_url"
            except WebcardLXUnsupportedModel:
                errors["base"] = "unsupported_model"
            except WebcardLXInvalidAuth:
                errors["base"] = "invalid_auth"
            except WebcardLXApiError:
                errors["base"] = "cannot_connect"
            except WebcardLXCannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(result.unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data,
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(dict(entry.data), include_options=False, password_required=False),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauthentication."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = dict(entry.data)
            data.update(user_input)
            try:
                data[CONF_URL] = normalize_base_url(data[CONF_URL])
                result = await async_validate_input(
                    self.hass,
                    {**data, **dict(entry.options)},
                    preferred_unique_id=getattr(entry, "unique_id", None),
                )
            except ValueError:
                errors["base"] = "invalid_url"
            except WebcardLXUnsupportedModel:
                errors["base"] = "unsupported_model"
            except WebcardLXInvalidAuth:
                errors["base"] = "invalid_auth"
            except WebcardLXApiError:
                errors["base"] = "cannot_connect"
            except WebcardLXCannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(result.unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data,
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Handle Tripp Lite WebcardLX options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._entry = entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_options_from_input(user_input))

        defaults = {**self._entry.data, **dict(self._entry.options)}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
                    vol.Optional(
                        CONF_ALLOW_UNSUPPORTED_MODEL,
                        default=defaults.get(CONF_ALLOW_UNSUPPORTED_MODEL, False),
                    ): bool,
                }
            ),
        )


def _data_from_input(
    user_input: Mapping[str, Any],
    *,
    existing_password: str | None = None,
) -> dict[str, Any]:
    """Return config-entry data from flow input."""
    password = str(user_input.get(CONF_PASSWORD) or "")
    if not password and existing_password is not None:
        password = existing_password
    return {
        CONF_URL: normalize_base_url(str(user_input[CONF_URL])),
        CONF_USERNAME: user_input[CONF_USERNAME],
        CONF_PASSWORD: password,
        CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    }


def _options_from_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return config-entry options from flow input."""
    return {
        CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        CONF_ALLOW_UNSUPPORTED_MODEL: bool(user_input.get(CONF_ALLOW_UNSUPPORTED_MODEL, False)),
    }
