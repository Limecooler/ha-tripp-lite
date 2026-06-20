"""Tests for the WebcardLX config flow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME, CONF_VERIFY_SSL

from custom_components.tripp_lite_webcardlx import config_flow
from custom_components.tripp_lite_webcardlx.api import (
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXInvalidAuth,
    WebcardLXUnsupportedModel,
)
from custom_components.tripp_lite_webcardlx.const import CONF_URL


class FakeValidationClient:
    """Fake API client for validation."""

    login_error: Exception | None = None
    system_details_error: Exception | None = None
    devices: list[dict[str, Any]] = []
    variables: list[dict[str, Any]] = []
    system_details: dict[str, Any] = {}
    instances: list[FakeValidationClient] = []

    def __init__(
        self,
        session: object,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self.session = session
        self.base_url = base_url
        self.username = username
        self.password = password
        self.__class__.instances.append(self)

    async def async_login(self) -> None:
        if self.login_error is not None:
            raise self.login_error

    async def async_get_devices(self) -> list[dict[str, Any]]:
        return self.devices

    async def async_get_variables(self) -> list[dict[str, Any]]:
        return self.variables

    async def async_get_system_details(self) -> dict[str, Any]:
        if self.system_details_error is not None:
            raise self.system_details_error
        return self.system_details

    async def async_logout(self) -> None:
        return None


def valid_input(**updates: Any) -> dict[str, Any]:
    """Return valid flow input."""
    data = {
        CONF_URL: "ups.local/",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "secret",
        CONF_SCAN_INTERVAL: 30,
    }
    data.update(updates)
    return data


def reset_fake_client() -> None:
    """Reset fake validation defaults."""
    FakeValidationClient.login_error = None
    FakeValidationClient.system_details_error = None
    FakeValidationClient.devices = [
        {
            "device_id": 1,
            "model": "SU1500RTXL2UA",
            "name": "Rack UPS",
            "serial_number": "SERIAL",
        }
    ]
    FakeValidationClient.variables = [{"device_id": 1, "device_type": "DEVICE_TYPE_UPS"}]
    FakeValidationClient.system_details = {}
    FakeValidationClient.instances = []


def make_flow() -> config_flow.ConfigFlow:
    """Create a flow with base stub attributes."""
    flow = config_flow.ConfigFlow()
    flow.hass = SimpleNamespace(session="session")
    flow.context = {}
    flow._unique_id = None
    flow._configured_updates = None
    flow.reconfigure_entry = None
    flow.reauth_entry = None
    flow.flow_id = "flow"

    async def async_set_unique_id(unique_id: str) -> None:
        flow._unique_id = unique_id

    def abort_if_unique_id_configured(updates: dict[str, Any] | None = None) -> None:
        flow._configured_updates = updates

    def abort_if_unique_id_mismatch() -> None:
        return None

    def async_create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    def async_show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def get_reconfigure_entry() -> Any:
        return flow.reconfigure_entry

    def get_reauth_entry() -> Any:
        return flow.reauth_entry

    def async_update_reload_and_abort(entry: Any, **kwargs: Any) -> dict[str, Any]:
        return {"type": "abort", "entry": entry, **kwargs}

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    flow._abort_if_unique_id_mismatch = abort_if_unique_id_mismatch  # type: ignore[method-assign]
    flow.async_create_entry = async_create_entry  # type: ignore[method-assign]
    flow.async_show_form = async_show_form  # type: ignore[method-assign]
    flow._get_reconfigure_entry = get_reconfigure_entry  # type: ignore[method-assign]
    flow._get_reauth_entry = get_reauth_entry  # type: ignore[method-assign]
    flow.async_update_reload_and_abort = async_update_reload_and_abort  # type: ignore[method-assign]
    return flow


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch API client used by the flow."""
    reset_fake_client()
    monkeypatch.setattr(config_flow, "WebcardLXClient", FakeValidationClient)
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda *args, **kwargs: "session")


async def test_validate_input_success_and_fallbacks() -> None:
    """Test direct validation."""
    result = await config_flow.async_validate_input(
        SimpleNamespace(session="session"),
        valid_input(),
    )

    assert result.title == "Rack UPS"
    assert result.unique_id == "SERIAL"
    assert result.models == ["SU1500RTXL2UA"]
    assert FakeValidationClient.instances[0].base_url == "https://ups.local"

    FakeValidationClient.devices = [{"device_id": 3, "model": "SMART1500"}]
    FakeValidationClient.variables = [{"device_id": 3, "device_type": "DEVICE_TYPE_UPS"}]
    result = await config_flow.async_validate_input(
        SimpleNamespace(session="session"),
        valid_input(),
    )

    assert result.title == "SMART1500"
    assert result.unique_id == "https://ups.local"

    reset_fake_client()
    FakeValidationClient.system_details = {"mac_address": "AA:BB:CC"}
    result = await config_flow.async_validate_input(
        SimpleNamespace(session="session"),
        valid_input(),
    )
    assert result.unique_id == "aa:bb:cc"

    result = await config_flow.async_validate_input(
        SimpleNamespace(session="session"),
        valid_input(),
        preferred_unique_id="SERIAL",
    )
    assert result.unique_id == "SERIAL"

    reset_fake_client()
    FakeValidationClient.system_details_error = WebcardLXCannotConnect("down")
    result = await config_flow.async_validate_input(
        SimpleNamespace(session="session"),
        valid_input(),
    )
    assert result.unique_id == "SERIAL"


def test_data_from_input_defaults_ssl_verification_to_insecure() -> None:
    """Test omitted SSL verification is stored as disabled."""
    data = config_flow._data_from_input(
        {
            CONF_URL: "ups.local",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
        }
    )

    assert data[CONF_VERIFY_SSL] is False


async def test_validate_input_rejects_when_no_ups_devices() -> None:
    """Test that validation fails when no UPS devices are present."""
    FakeValidationClient.devices = [{"device_id": 2, "model": "SMART1500"}]
    FakeValidationClient.variables = []

    with pytest.raises(WebcardLXUnsupportedModel):
        await config_flow.async_validate_input(SimpleNamespace(session="session"), valid_input())


async def test_user_step_form_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test user flow handling."""
    flow = make_flow()
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await flow.async_step_user(valid_input())
    assert result["type"] == "create_entry"
    assert result["title"] == "Rack UPS"
    assert result["data"][CONF_URL] == "https://ups.local"
    assert flow._unique_id == "SERIAL"
    assert flow._configured_updates == {CONF_URL: "https://ups.local"}

    async def raise_value_error(hass: object, user_input: dict[str, Any]) -> object:
        raise ValueError

    async def raise_unsupported(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXUnsupportedModel(["SMART1500"])

    async def raise_invalid_auth(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXInvalidAuth("bad")

    async def raise_cannot_connect(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXCannotConnect("down")

    async def raise_api_error(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXApiError(500, "raw")

    async def raise_unknown(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise RuntimeError("boom")

    for error_func, error_key in (
        (raise_value_error, "invalid_url"),
        (raise_unsupported, "unsupported_model"),
        (raise_invalid_auth, "invalid_auth"),
        (raise_cannot_connect, "cannot_connect"),
        (raise_api_error, "cannot_connect"),
        (raise_unknown, "unknown"),
    ):
        flow = make_flow()
        monkeypatch.setattr(config_flow, "async_validate_input", error_func)
        result = await flow.async_step_user(valid_input())
        assert result["errors"] == {"base": error_key}


async def test_dhcp_step_prefills_discovery() -> None:
    """Test DHCP discovery step."""
    flow = make_flow()

    result = await flow.async_step_dhcp(
        SimpleNamespace(ip="192.0.2.10", hostname="ups-card", macaddress="AA:BB:CC")
    )

    assert result["type"] == "form"
    assert flow._unique_id == "aa:bb:cc"
    assert flow.context["title_placeholders"] == {"name": "ups-card"}
    assert flow._discovered_url == "https://192.0.2.10"
    # When device is already configured, the URL is updated to the newly-discovered IP
    assert flow._configured_updates == {CONF_URL: "https://192.0.2.10"}


async def test_dhcp_step_tripp_lite_oui_mac() -> None:
    """DHCP discovery with a real Tripp Lite OUI MAC (000667*) works correctly."""
    flow = make_flow()

    result = await flow.async_step_dhcp(
        SimpleNamespace(
            ip="192.168.1.50",
            hostname="webcardlx",
            macaddress="00:06:67:43:17:02",
        )
    )

    assert result["type"] == "form"
    assert flow._unique_id == "00:06:67:43:17:02"
    assert flow._discovered_url == "https://192.168.1.50"
    assert flow._configured_updates == {CONF_URL: "https://192.168.1.50"}


async def test_dhcp_step_no_mac_skips_unique_id() -> None:
    """DHCP discovery without a MAC address does not set unique ID or abort."""
    flow = make_flow()

    result = await flow.async_step_dhcp(
        SimpleNamespace(ip="192.0.2.10", hostname="ups-card", macaddress=None)
    )

    assert result["type"] == "form"
    assert flow._unique_id is None
    assert flow._configured_updates is None


async def test_reconfigure_step_form_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reconfigure flow handling."""
    entry = SimpleNamespace(data=valid_input(), options={}, entry_id="entry")
    flow = make_flow()
    flow.reconfigure_entry = entry

    result = await flow.async_step_reconfigure()
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    result = await flow.async_step_reconfigure(valid_input(CONF_URL="https://ups.local"))
    assert result["type"] == "abort"
    assert result["entry"] is entry
    assert result["data_updates"][CONF_URL] == "https://ups.local"
    assert result["data_updates"][CONF_PASSWORD] == "secret"
    assert result["reason"] == "reconfigure_successful"

    flow = make_flow()
    flow.reconfigure_entry = entry
    result = await flow.async_step_reconfigure(valid_input(**{CONF_PASSWORD: ""}))
    assert result["type"] == "abort"
    assert result["data_updates"][CONF_PASSWORD] == "secret"

    async def raise_value_error(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise ValueError

    async def raise_unsupported(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXUnsupportedModel(["SMART1500"])

    async def raise_invalid_auth(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXInvalidAuth("bad")

    async def raise_cannot_connect(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXCannotConnect("down")

    async def raise_api_error(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXApiError(500, "raw")

    async def raise_unknown(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise RuntimeError("boom")

    for error_func, error_key in (
        (raise_value_error, "invalid_url"),
        (raise_unsupported, "unsupported_model"),
        (raise_invalid_auth, "invalid_auth"),
        (raise_cannot_connect, "cannot_connect"),
        (raise_api_error, "cannot_connect"),
        (raise_unknown, "unknown"),
    ):
        flow = make_flow()
        flow.reconfigure_entry = entry
        monkeypatch.setattr(config_flow, "async_validate_input", error_func)
        result = await flow.async_step_reconfigure(valid_input())
        assert result["errors"] == {"base": error_key}


async def test_reauth_step_form_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reauthentication flow handling."""
    entry = SimpleNamespace(data=valid_input(), options={}, entry_id="entry")
    flow = make_flow()
    flow.reauth_entry = entry

    result = await flow.async_step_reauth(entry.data)
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"

    result = await flow.async_step_reauth_confirm(
        {CONF_USERNAME: "admin2", CONF_PASSWORD: "secret2"}
    )
    assert result["type"] == "abort"
    assert result["entry"] is entry
    assert result["data_updates"][CONF_USERNAME] == "admin2"
    assert result["data_updates"][CONF_PASSWORD] == "secret2"
    assert result["reason"] == "reauth_successful"

    async def raise_value_error(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise ValueError

    async def raise_unsupported(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXUnsupportedModel(["SMART1500"])

    async def raise_invalid_auth(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXInvalidAuth("bad")

    async def raise_cannot_connect(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXCannotConnect("down")

    async def raise_api_error(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise WebcardLXApiError(500, "raw")

    async def raise_unknown(
        hass: object,
        user_input: dict[str, Any],
        preferred_unique_id: str | None = None,
    ) -> object:
        raise RuntimeError("boom")

    for error_func, error_key in (
        (raise_value_error, "invalid_url"),
        (raise_unsupported, "unsupported_model"),
        (raise_invalid_auth, "invalid_auth"),
        (raise_cannot_connect, "cannot_connect"),
        (raise_api_error, "cannot_connect"),
        (raise_unknown, "unknown"),
    ):
        flow = make_flow()
        flow.reauth_entry = entry
        monkeypatch.setattr(config_flow, "async_validate_input", error_func)
        result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "new"})
        assert result["errors"] == {"base": error_key}


async def test_options_flow() -> None:
    """Test options flow."""
    entry = SimpleNamespace(data={}, options={CONF_SCAN_INTERVAL: 45})
    flow = config_flow.ConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, config_flow.OptionsFlow)

    result = await flow.async_step_init()
    assert result["type"] == "form"

    result = await flow.async_step_init({CONF_SCAN_INTERVAL: 60})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_SCAN_INTERVAL] == 60
