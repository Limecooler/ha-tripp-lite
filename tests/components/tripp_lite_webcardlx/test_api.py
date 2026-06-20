"""Tests for the WebcardLX API client."""

from __future__ import annotations

from urllib.parse import urlsplit

from custom_components.tripp_lite_webcardlx.api import (  # noqa: E402
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXClient,
    WebcardLXInvalidAuth,
    WebcardLXUnsupportedModel,
    data_list,
    data_object,
    normalize_base_url,
    normalize_model,
)


def test_normalize_base_url_adds_https() -> None:
    """Test bare host normalization."""
    assert normalize_base_url("192.0.2.10") == "https://192.0.2.10"


def test_normalize_base_url_keeps_scheme_and_port() -> None:
    """Test full URL normalization."""
    assert normalize_base_url("http://192.0.2.10:8080/") == "http://192.0.2.10:8080"


def test_normalize_base_url_rejects_bad_url() -> None:
    """Test bad URL rejection."""
    import pytest

    with pytest.raises(ValueError):
        normalize_base_url("")
    with pytest.raises(ValueError):
        normalize_base_url("ftp://example.com")
    with pytest.raises(ValueError):
        normalize_base_url("https://user:pass@example.com")
    with pytest.raises(ValueError):
        normalize_base_url("https://example.com/api")
    with pytest.raises(ValueError):
        normalize_base_url("https://example.com?token=secret")
    with pytest.raises(ValueError):
        normalize_base_url("https://example.com#frag")


def test_normalize_model() -> None:
    """Test model normalization."""
    assert normalize_model(" Tripp Lite SU1500RTXL2Ua ") == "TRIPPLITESU1500RTXL2UA"


def test_data_list_flattens_jsonapi_resources() -> None:
    """Test JSON:API data flattening."""
    payload = {
        "data": [
            {
                "type": "variables",
                "id": "1",
                "attributes": {"label": "Battery Capacity", "value": "100"},
            }
        ]
    }

    assert data_list(payload) == [
        {
            "type": "variables",
            "id": "1",
            "label": "Battery Capacity",
            "value": "100",
        }
    ]


def test_data_helpers_handle_empty_and_single_payloads() -> None:
    """Test data helper edge cases."""
    assert data_list({"data": {"type": "ready", "id": 1, "attributes": {"ready": True}}}) == [
        {"type": "ready", "id": "1", "ready": True}
    ]
    assert data_object({"data": {"type": "ready", "id": 2}}) == {"type": "ready", "id": "2"}
    assert data_list({"data": []}) == []
    assert data_list({"data": "bad"}) == []
    assert data_object({"data": []}) == {}


class FakeResponse:
    """Minimal aiohttp response test double."""

    def __init__(self, status: int = 200, payload: object | None = None, text: str = "") -> None:
        self.status = status
        self.payload = payload if payload is not None else {}
        self._text = text

    async def __aenter__(self) -> FakeResponse:
        """Enter async context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context."""

    async def json(self, content_type: str | None = None, encoding: str | None = None) -> object:
        """Return a token response."""
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def text(self) -> str:
        """Return text response."""
        return self._text


class FakeSession:
    """Minimal aiohttp session test double."""

    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse(
            payload={" access_token ": "access", " refresh_token ": "refresh"}
        )
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def request(self, *args: object, **kwargs: object) -> FakeResponse:
        """Return a fake response."""
        self.calls.append((args, kwargs))
        return self.response


class RoutingSession:
    """Route responses by path."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.unauthorized_once = False

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        """Return a response for a path."""
        path = urlsplit(url).path
        self.calls.append((method, path, kwargs))
        if path == "/api/oauth/token":
            return FakeResponse(
                payload={"data": {"attributes": {"access_token": "a", "refresh_token": "r"}}}
            )
        if path == "/api/oauth/refresh":
            return FakeResponse(payload={"access_token": "new", "refresh_token": "rotated"})
        if path == "/api/oauth/token/logout":
            return FakeResponse(payload={"msg": "ok"})
        if path == "/api/protected" and not self.unauthorized_once:
            self.unauthorized_once = True
            return FakeResponse(status=401, payload={})
        payload = {"data": {"type": "x", "id": "1", "attributes": {"value": path}}}
        if path in {
            "/api/devices",
            "/api/variables",
            "/api/loads",
            "/api/loads_group",
            "/api/alarms",
            "/api/events",
        }:
            payload = {"data": [{"type": "x", "id": "1", "attributes": {"value": path}}]}
        return FakeResponse(payload=payload)


class MissingRefreshSession(RoutingSession):
    """Route responses with an unavailable refresh endpoint."""

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        """Return a response for a path."""
        path = urlsplit(url).path
        if path == "/api/oauth/refresh":
            self.calls.append((method, path, kwargs))
            return FakeResponse(status=404)
        return super().request(method, url, **kwargs)


class ErrorRefreshSession(RoutingSession):
    """Route responses with a failing refresh endpoint."""

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        """Return a response for a path."""
        path = urlsplit(url).path
        if path == "/api/oauth/refresh":
            self.calls.append((method, path, kwargs))
            return FakeResponse(status=500)
        return super().request(method, url, **kwargs)


async def test_login_accepts_whitespace_token_keys() -> None:
    """Test token parsing for the whitespace keys shown in the vendor docs."""
    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(),
        "https://192.0.2.10",
        "user",
        "pass",
    )

    await client.async_login()

    assert client.access_token == "access"
    assert client.refresh_token == "refresh"


async def test_client_methods_and_refresh() -> None:
    """Test client endpoint methods."""
    session = RoutingSession()
    client = WebcardLXClient(  # type: ignore[arg-type]
        session,
        "https://192.0.2.10",
        "user",
        "pass",
    )
    await client.async_login()
    await client._request("GET", "/api/protected")
    await client.async_logout()

    assert client.access_token is None
    assert client.refresh_token is None
    assert ("POST", "/api/oauth/refresh") in [(method, path) for method, path, _ in session.calls]

    client.access_token = "a"
    client.refresh_token = "r"
    assert await client.async_get_devices()
    assert await client.async_get_devices_info()
    assert await client.async_get_variables()
    assert await client.async_get_control_variables()
    assert await client.async_get_loads()
    assert await client.async_get_load_groups()
    assert await client.async_get_supported_actions()
    assert await client.async_get_supported_schedules()
    assert await client.async_get_alarm_summary()
    assert await client.async_get_alarms()
    assert await client.async_get_events()
    assert await client.async_get_ready()
    assert await client.async_get_system_details()
    assert await client.async_get_system_uptime()
    await client.async_update_variable("1", 2, 0.5)
    await client.async_execute_load("1", "1", "LOAD_ACTION_ON")
    await client.async_execute_main_load("1", "LOAD_ACTION_OFF")
    await client.async_control_device("turn_on", "1", turn_on_delay=2)
    await client.async_control_device("turn_off", "1", turn_off_delay=3)
    await client.async_control_device("reboot", "1", turn_on_delay=2, turn_off_delay=1)
    await client.async_acknowledge_alarms(["1", "2"])
    await client.async_acknowledge_all_alarms()
    await client.async_update_device("1", {"name": "UPS"})


async def test_client_error_paths() -> None:
    """Test API error paths."""
    import pytest
    from aiohttp import ClientError

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(status=403)),
        "https://host",
        "u",
        "p",
    )
    with pytest.raises(WebcardLXApiError):
        await client._request("GET", "/api/x")

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(status=403)),
        "https://host",
        "u",
        "p",
    )
    with pytest.raises(WebcardLXInvalidAuth):
        await client._request("POST", "/api/oauth/token", auth=False)

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(status=500, text="bad")),
        "https://host",
        "u",
        "p",
    )
    with pytest.raises(WebcardLXApiError) as raw_error:
        await client._request("GET", "/api/x")
    assert str(raw_error.value) == "WebcardLX API error 500"
    assert raw_error.value.raw_message == "bad"

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(status=404)),
        "https://host",
        "u",
        "p",
    )
    assert await client._request("GET", "/api/x", allow_404=True) == {}

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(status=204)),
        "https://host",
        "u",
        "p",
    )
    assert await client._request("GET", "/api/x") == {}

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(payload=ValueError("json"))),
        "https://host",
        "u",
        "p",
    )
    with pytest.raises(WebcardLXApiError):
        await client._request("GET", "/api/x")

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(payload=[])),
        "https://host",
        "u",
        "p",
    )
    with pytest.raises(WebcardLXApiError):
        await client._request("GET", "/api/x")

    class RaisingSession:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def request(self, *args: object, **kwargs: object) -> FakeResponse:
            raise self.error

    with pytest.raises(WebcardLXCannotConnect):
        await WebcardLXClient(  # type: ignore[arg-type]
            RaisingSession(TimeoutError()),
            "https://host",
            "u",
            "p",
        )._request("GET", "/x")
    with pytest.raises(WebcardLXCannotConnect):
        await WebcardLXClient(  # type: ignore[arg-type]
            RaisingSession(ClientError("x")),
            "https://host",
            "u",
            "p",
        )._request("GET", "/x")

    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(payload={})),
        "https://host",
        "u",
        "p",
    )
    with pytest.raises(WebcardLXInvalidAuth):
        await client.async_login()
    client.refresh_token = None
    with pytest.raises(WebcardLXInvalidAuth):
        await client.async_refresh_token()
    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(payload={})),
        "https://host",
        "u",
        "p",
    )
    client.refresh_token = "refresh"
    with pytest.raises(WebcardLXInvalidAuth):
        await client.async_refresh_token()
    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(FakeResponse(status=500)),
        "https://host",
        "u",
        "p",
    )
    client.refresh_token = "refresh"
    await client.async_logout()
    assert client.refresh_token is None
    client = WebcardLXClient(  # type: ignore[arg-type]
        FakeSession(),
        "https://host",
        "u",
        "p",
    )
    await client.async_logout()
    with pytest.raises(ValueError):
        await client.async_control_device("bad", "1")


async def test_refresh_skips_when_token_already_changed() -> None:
    """Test concurrent refresh guard."""
    session = RoutingSession()
    client = WebcardLXClient(session, "https://host", "u", "p")  # type: ignore[arg-type]
    client.access_token = "new"
    client.refresh_token = "refresh"

    await client._async_refresh_token_if_needed("old")

    assert ("POST", "/api/oauth/refresh") not in [
        (method, path) for method, path, _kwargs in session.calls
    ]

    await client.async_refresh_token()

    assert client.refresh_token == "rotated"


async def test_refresh_falls_back_to_login_when_refresh_endpoint_is_missing() -> None:
    """Test firmware that omits the documented refresh endpoint."""
    session = MissingRefreshSession()
    client = WebcardLXClient(session, "https://host", "u", "p")  # type: ignore[arg-type]

    await client.async_login()
    await client.async_refresh_token()

    calls = [(method, path) for method, path, _kwargs in session.calls]
    assert calls.count(("POST", "/api/oauth/token")) == 2
    assert ("POST", "/api/oauth/refresh") in calls
    assert client.access_token == "a"
    assert client.refresh_token == "r"


async def test_refresh_does_not_fall_back_for_refresh_server_errors() -> None:
    """Test non-404 refresh failures still surface."""
    import pytest

    session = ErrorRefreshSession()
    client = WebcardLXClient(session, "https://host", "u", "p")  # type: ignore[arg-type]

    await client.async_login()
    with pytest.raises(WebcardLXApiError):
        await client.async_refresh_token()


async def test_oauth_endpoints_use_json_content_type() -> None:
    """Test that OAuth endpoints send application/json, not application/vnd.api+json."""
    session = RoutingSession()
    client = WebcardLXClient(session, "https://host", "u", "p")  # type: ignore[arg-type]

    await client.async_login()
    client.refresh_token = "r"
    await client.async_refresh_token()
    await client.async_logout()

    oauth_paths = {"/api/oauth/token", "/api/oauth/refresh", "/api/oauth/token/logout"}
    for _method, path, kwargs in session.calls:
        if path in oauth_paths:
            ct = kwargs.get("headers", {}).get("Content-Type", "")
            assert ct == "application/json", (
                f"{path} sent Content-Type {ct!r}, want application/json"
            )


def test_unsupported_model_error() -> None:
    """Test unsupported model error."""
    err = WebcardLXUnsupportedModel(["X"])
    assert err.models == ["X"]
    assert "X" in str(err)
