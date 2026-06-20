"""Async client for the Tripp Lite WebcardLX PowerAlert API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import API_VERSION, REQUEST_CONNECT_TIMEOUT, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

JSON_API_CONTENT_TYPE = "application/vnd.api+json"


class WebcardLXError(Exception):
    """Base WebcardLX error."""


class WebcardLXCannotConnect(WebcardLXError):
    """Raised when the WebcardLX cannot be reached."""


class WebcardLXInvalidAuth(WebcardLXError):
    """Raised when credentials or tokens are invalid."""


class WebcardLXApiError(WebcardLXError):
    """Raised when the WebcardLX returns an API error."""

    def __init__(self, status: int, message: str | None = None) -> None:
        """Initialize the error."""
        super().__init__(f"WebcardLX API error {status}")
        self.status = status
        self.message = f"WebcardLX API error {status}"
        self.raw_message = message or ""


class WebcardLXUnsupportedModel(WebcardLXError):
    """Raised when no supported UPS model is found."""

    def __init__(self, models: list[str]) -> None:
        """Initialize the error."""
        self.models = models
        super().__init__(f"No supported UPS model found: {', '.join(models) or 'none'}")


def normalize_base_url(value: str) -> str:
    """Normalize a user-supplied WebcardLX endpoint."""
    url = value.strip().rstrip("/")
    if not url:
        raise ValueError("empty URL")
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid URL")
    if parsed.path not in ("", "/"):
        raise ValueError("invalid URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_model(value: str | None) -> str:
    """Normalize a model name for matching."""
    if not value:
        return ""
    return "".join(char for char in value.upper() if char.isalnum())


def _token_value(payload: Mapping[str, Any], key: str) -> str | None:
    """Return a token value, accepting the whitespace seen in the vendor docs."""
    for payload_key, value in payload.items():
        if payload_key.strip() == key and isinstance(value, str):
            return value
    data = payload.get("data")
    if isinstance(data, Mapping):
        attributes = data.get("attributes")
        if isinstance(attributes, Mapping):
            return _token_value(attributes, key)
    return None


def _jsonapi_attributes(item: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource into attributes plus id/type."""
    attributes = item.get("attributes")
    if isinstance(attributes, Mapping):
        data = dict(attributes)
    else:
        data = {}
    if "id" in item:
        data["id"] = str(item["id"])
    if "type" in item:
        data["type"] = item["type"]
    return data


def data_list(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the response data as a list of flattened resource attributes."""
    data = payload.get("data")
    if isinstance(data, list):
        return [
            _jsonapi_attributes(item)
            for item in data
            if isinstance(item, Mapping)
        ]
    if isinstance(data, Mapping):
        return [_jsonapi_attributes(data)]
    return []


def data_object(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the response data as flattened resource attributes."""
    data = payload.get("data")
    if isinstance(data, Mapping):
        return _jsonapi_attributes(data)
    items = data_list(payload)
    return items[0] if items else {}


class WebcardLXClient:
    """Client for the WebcardLX PowerAlert REST API."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self.session = session
        self.base_url = normalize_base_url(base_url)
        self.username = username
        self.password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._refresh_lock = asyncio.Lock()
        self._timeout = ClientTimeout(total=REQUEST_TIMEOUT, connect=REQUEST_CONNECT_TIMEOUT)
        self._base_headers: dict[str, str] = {
            "Accept": JSON_API_CONTENT_TYPE,
            "Content-Type": JSON_API_CONTENT_TYPE,
            "Accept-Version": API_VERSION,
        }

    async def async_login(self) -> None:
        """Authenticate and store access tokens."""
        payload = await self._request(
            "POST",
            "/api/oauth/token",
            auth=False,
            content_type="application/json",
            json={
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
            },
        )
        access_token = _token_value(payload, "access_token")
        refresh_token = _token_value(payload, "refresh_token")
        if not access_token:
            raise WebcardLXInvalidAuth("Authentication response did not include an access token")
        self.access_token = access_token
        self.refresh_token = refresh_token

    async def async_refresh_token(self) -> None:
        """Refresh the access token."""
        await self._async_refresh_token_if_needed(None)

    async def _async_refresh_token_if_needed(self, expired_token: str | None) -> None:
        """Refresh the access token once for concurrent callers."""
        async with self._refresh_lock:
            if expired_token and self.access_token and self.access_token != expired_token:
                return
            await self._async_refresh_token_unlocked()

    async def _async_refresh_token_unlocked(self) -> None:
        """Refresh the access token while holding the refresh lock."""
        if not self.refresh_token:
            raise WebcardLXInvalidAuth("No refresh token is available")
        try:
            payload = await self._request(
                "POST",
                "/api/oauth/refresh",
                auth=False,
                content_type="application/json",
                bearer=self.refresh_token,
            )
        except WebcardLXApiError as err:
            if err.status != 404:
                raise
            _LOGGER.debug(
                "WebcardLX refresh endpoint is unavailable; renewing token with password grant"
            )
            await self.async_login()
            return
        access_token = _token_value(payload, "access_token")
        if not access_token:
            raise WebcardLXInvalidAuth("Refresh response did not include an access token")
        self.access_token = access_token
        if refresh_token := _token_value(payload, "refresh_token"):
            self.refresh_token = refresh_token

    async def async_logout(self) -> None:
        """Invalidate the refresh token if one is available."""
        async with self._refresh_lock:
            if not self.refresh_token:
                return
            rt = self.refresh_token
            self.access_token = None
            self.refresh_token = None
        try:
            await self._request(
                "POST",
                "/api/oauth/token/logout",
                auth=False,
                content_type="application/json",
                bearer=rt,
            )
        except WebcardLXError:
            _LOGGER.debug("Ignoring WebcardLX logout failure", exc_info=True)

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return all device records."""
        return data_list(await self._request("GET", "/api/devices"))

    async def async_get_devices_info(self) -> list[dict[str, Any]]:
        """Return extended device information, if supported."""
        return data_list(await self._request("GET", "/api/devices_info", allow_404=True))

    async def async_get_variables(self) -> list[dict[str, Any]]:
        """Return all variables."""
        return data_list(await self._request("GET", "/api/variables"))

    async def async_get_control_variables(self) -> list[dict[str, Any]]:
        """Return variables that expose control metadata."""
        return data_list(
            await self._request(
                "GET",
                "/api/variables",
                params={"filter[has_control_key]": "true"},
                allow_404=True,
            )
        )

    async def async_get_loads(self) -> list[dict[str, Any]]:
        """Return load/outlet records."""
        return data_list(await self._request("GET", "/api/loads", allow_404=True))

    async def async_get_load_groups(self) -> list[dict[str, Any]]:
        """Return configured load groups."""
        return data_list(await self._request("GET", "/api/loads_group", allow_404=True))

    async def async_get_supported_actions(self) -> dict[str, Any]:
        """Return action support flags for the current device."""
        return data_object(await self._request("GET", "/api/actions/supported", allow_404=True))

    async def async_get_supported_schedules(self) -> dict[str, Any]:
        """Return schedule support flags for the current device."""
        return data_object(await self._request("GET", "/api/schedulings/supported", allow_404=True))

    async def async_get_alarm_summary(self) -> dict[str, Any]:
        """Return the alarm summary."""
        return data_object(await self._request("GET", "/api/alarms/summary", allow_404=True))

    async def async_get_alarms(self) -> list[dict[str, Any]]:
        """Return the newest alarms."""
        return data_list(
            await self._request(
                "GET",
                "/api/alarms",
                params={"page[size]": "30", "page[number]": "1", "sort": "-occurred_time"},
                allow_404=True,
            )
        )

    async def async_get_events(self) -> list[dict[str, Any]]:
        """Return configured device events."""
        return data_list(
            await self._request(
                "GET",
                "/api/events",
                params={"page[size]": "30", "page[number]": "1", "sort": "-occurred_time"},
                allow_404=True,
            )
        )

    async def async_get_ready(self) -> dict[str, Any]:
        """Return system ready state."""
        return data_object(await self._request("GET", "/api/ready", allow_404=True))

    async def async_get_system_details(self) -> dict[str, Any]:
        """Return WebcardLX system details."""
        return data_object(await self._request("GET", "/api/system_details", allow_404=True))

    async def async_get_system_uptime(self) -> dict[str, Any]:
        """Return WebcardLX system uptime."""
        return data_object(await self._request("GET", "/api/system_uptime", allow_404=True))

    async def async_update_variable(
        self,
        variable_id: str | int,
        value: Any,
        tolerance: float | None = None,
    ) -> None:
        """Update a variable value."""
        attributes: dict[str, Any] = {"new_value": str(value)}
        if tolerance is not None:
            attributes["tolerance"] = tolerance
        await self._request(
            "PATCH",
            f"/api/variables/{variable_id}",
            json={"data": {"type": "variables", "attributes": attributes}},
        )

    async def async_execute_load(
        self,
        load_id: str | int,
        device_id: str | int,
        load_action: str,
    ) -> None:
        """Execute an action against an individual load."""
        await self._request(
            "PATCH",
            f"/api/loads_execute/{load_id}",
            json={
                "data": {
                    "type": "loads_execute",
                    "attributes": {
                        "device_id": int(device_id),
                        "load_action": load_action,
                    },
                }
            },
        )

    async def async_execute_main_load(self, device_id: str | int, load_action: str) -> None:
        """Execute an action against the main load for a device."""
        await self._request(
            "PATCH",
            f"/api/loads_execute/main/{device_id}",
            json={
                "data": {
                    "type": "loads_execute_main",
                    "attributes": {"load_action": load_action},
                }
            },
        )

    async def async_control_device(
        self,
        action: str,
        device_id: str | int,
        turn_on_delay: int | None = None,
        turn_off_delay: int | None = None,
    ) -> None:
        """Execute a device power control action."""
        if action == "turn_on":
            endpoint = "/api/controls_turnon_device/execute"
            payload_type = "controls_turnon_device"
            attributes = {"device_id": int(device_id), "turn_on_delay": turn_on_delay or 0}
        elif action == "turn_off":
            endpoint = "/api/controls_turnoff_device/execute"
            payload_type = "controls_turnoff_device"
            attributes = {"device_id": int(device_id), "turn_off_delay": turn_off_delay or 0}
        elif action == "reboot":
            endpoint = "/api/controls_reboot_device/execute"
            payload_type = "controls_reboot_device"
            attributes = {
                "device_id": int(device_id),
                "turn_off_delay": turn_off_delay or 0,
                "turn_on_delay": turn_on_delay or 0,
            }
        else:
            raise ValueError(f"Unsupported device action: {action}")

        await self._request(
            "PATCH",
            endpoint,
            json={"data": {"type": payload_type, "attributes": attributes}},
        )

    async def async_acknowledge_alarms(self, alarm_ids: list[str]) -> None:
        """Acknowledge specific alarms."""
        await self._request(
            "PATCH",
            "/api/alarms/acknowledge",
            json={"data": [{"type": "alarms", "id": alarm_id} for alarm_id in alarm_ids]},
        )

    async def async_acknowledge_all_alarms(self) -> None:
        """Acknowledge all active alarms."""
        await self._request("PATCH", "/api/alarms/acknowledge/all")

    async def async_update_device(
        self,
        device_id: str | int,
        attributes: Mapping[str, Any],
    ) -> None:
        """Update editable device properties."""
        await self._request(
            "PATCH",
            f"/api/devices/{device_id}",
            json={"data": {"type": "devices", "attributes": dict(attributes)}},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        bearer: str | None = None,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        allow_404: bool = False,
        content_type: str = JSON_API_CONTENT_TYPE,
        _retried: bool = False,
    ) -> dict[str, Any]:
        """Make an API request."""
        url = f"{self.base_url}{path}"
        headers = dict(self._base_headers)
        if content_type != JSON_API_CONTENT_TYPE:
            headers["Content-Type"] = content_type
        token = bearer or (self.access_token if auth else None)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with self.session.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=self._timeout,
            ) as response:
                if response.status == 401 and auth and not _retried and self.refresh_token:
                    await self._async_refresh_token_if_needed(token)
                    return await self._request(
                        method,
                        path,
                        auth=auth,
                        json=json,
                        params=params,
                        allow_404=allow_404,
                        content_type=content_type,
                        _retried=True,
                    )
                return await self._handle_response(response, allow_404, auth=auth)
        except WebcardLXError:
            raise
        except TimeoutError as err:
            raise WebcardLXCannotConnect("Timed out connecting to WebcardLX") from err
        except ClientError as err:
            raise WebcardLXCannotConnect(str(err)) from err

    async def _handle_response(
        self,
        response: ClientResponse,
        allow_404: bool,
        *,
        auth: bool,
    ) -> dict[str, Any]:
        """Handle an HTTP response."""
        if allow_404 and response.status == 404:
            return {}
        if response.status == 401 or (response.status == 403 and not auth):
            raise WebcardLXInvalidAuth("Invalid WebcardLX credentials")
        if response.status >= 400:
            text = await response.text()
            _LOGGER.debug(
                "WebcardLX API error response for status %s: %s",
                response.status,
                text[:500],
            )
            raise WebcardLXApiError(response.status, text[:500])
        if response.status == 204:
            return {}
        try:
            payload = await response.json(content_type=None, encoding="utf-8")
        except Exception as err:  # noqa: BLE001 - include malformed device responses.
            text = await response.text()
            _LOGGER.debug(
                "WebcardLX invalid JSON response for status %s: %s",
                response.status,
                text[:500],
            )
            raise WebcardLXApiError(
                response.status,
                f"Invalid JSON response: {text[:500]}",
            ) from err
        if isinstance(payload, Mapping):
            return payload  # type: ignore[return-value]
        raise WebcardLXApiError(response.status, "Response JSON was not an object")
