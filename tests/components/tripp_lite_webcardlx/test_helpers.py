"""Tests for WebcardLX helper functions."""

from __future__ import annotations

import pytest

from custom_components.tripp_lite_webcardlx import helpers as helpers_module  # noqa: E402
from custom_components.tripp_lite_webcardlx.helpers import (  # noqa: E402
    action_load_ids,
    action_supports_device,
    as_bool,
    as_float,
    as_int,
    device_id,
    discovered_models,
    enum_options,
    is_editable_variable,
    is_sensitive_attributes,
    is_supported_model,
    label,
    load_action_supported,
    load_id,
    raw_value,
    stable_slug,
    stable_unique_suffix,
    supported_device_ids,
    supports,
    variable_id,
    variable_key,
    variable_unique_key,
)
from custom_components.tripp_lite_webcardlx.metadata import (  # noqa: E402
    LOAD_METRICS,
    native_variable_value,
    normalized_text,
    value_metadata,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (None, None),
        ("true", True),
        ("OFF", False),
        ("enabled", True),
        ("0", False),
        ("unknown", None),
    ],
)
def test_as_bool(value: object, expected: bool | None) -> None:
    """Test boolean parsing."""
    assert as_bool(value) is expected


def test_numeric_helpers() -> None:
    """Test numeric parsing helpers."""
    assert as_float("1,234.5") == 1234.5
    assert as_float("bad") is None
    assert as_float(None) is None
    assert as_float(float("inf")) is None
    assert as_float(2) == 2
    assert as_int("2.9") == 2
    assert as_int("bad") is None


def test_as_int_handles_conversion_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test integer parsing handles bad numeric wrappers defensively."""

    class BadInteger:
        def __int__(self) -> int:
            raise ValueError

    monkeypatch.setattr(helpers_module, "as_float", lambda value: BadInteger())

    assert as_int("bad-wrapper") is None


@pytest.mark.parametrize("model", ["SU1000XLA", "Tripp Lite SU1500RTXL2UA", "su1500rtxl2u"])
def test_supported_models(model: str) -> None:
    """Test supported model matching."""
    assert is_supported_model(model)


def test_supported_model_false() -> None:
    """Test unsupported model matching."""
    assert not is_supported_model("")
    assert not is_supported_model("SMART1500")


def test_supported_device_ids_requires_supported_model_by_default() -> None:
    """Test default model gate."""
    devices = [{"device_id": 1, "model": "SMART1500RM2U"}]
    variables = [{"device_id": 1, "device_type": "DEVICE_TYPE_UPS"}]

    assert supported_device_ids(devices, variables, allow_unsupported_model=False) == set()


def test_supported_device_ids_can_allow_ups_variable_fallback() -> None:
    """Test explicit unsupported-model override."""
    devices = [{"device_id": 1, "model": "SMART1500RM2U"}]
    variables = [{"device_id": 1, "device_type": "DEVICE_TYPE_UPS"}]

    assert supported_device_ids(devices, variables, allow_unsupported_model=True) == {"1"}


def test_supported_device_ids_explicit_model() -> None:
    """Test explicit supported model ids."""
    devices = [{"device_id": 1, "model": "SU1000XLA"}, {"id": "2", "model": "Other"}]
    assert supported_device_ids(devices, [], allow_unsupported_model=False) == {"1"}


def test_attribute_helpers() -> None:
    """Test generic attribute helpers."""
    attrs = {
        "id": "7",
        "device_id": 1,
        "label": "Battery Capacity",
        "raw_value": "",
        "value": "100",
        "supports": ["VARSUPPORTS_UPDATE"],
        "editable": False,
    }
    assert stable_slug("Hello World!", "x") == "hello_world"
    assert stable_slug("!!!", "x") == "x"
    assert stable_unique_suffix("Hello World!", "x").startswith("hello_world_")
    assert stable_unique_suffix("abc", "x") == "abc"
    assert raw_value(attrs) == "100"
    assert supports(attrs) == {"VARSUPPORTS_UPDATE"}
    assert supports({"supports": "A"}) == {"A"}
    assert supports({"supports": 1}) == set()
    assert is_editable_variable(attrs)
    assert is_editable_variable({"editable": True})
    assert not is_editable_variable({})
    assert device_id(attrs) == "1"
    assert device_id({}) == ""
    assert variable_id(attrs) == "7"
    assert variable_id({}) == ""
    assert variable_key({"id": "fallback"}) == "fallback"
    assert variable_unique_key({"key": 123}) == "123"
    assert variable_unique_key(attrs) == "7"
    assert variable_unique_key({"label": "Runtime Remaining"}) == "runtime_remaining"
    assert load_id({"id": 9}) == "9"
    assert load_id({}) == ""
    assert label(attrs, "Fallback") == "Battery Capacity"
    assert label({}, "Fallback") == "Fallback"
    assert discovered_models([{"model": "B"}, {"model": "A"}, {"model": ""}]) == ["A", "B"]
    assert is_sensitive_attributes({"label": "API Token", "value": "secret"})
    assert not is_sensitive_attributes({"label": "Battery Capacity", "value": "100"})


def test_enum_options() -> None:
    """Test enum option extraction."""
    assert enum_options({"enum_values": {"1": {"name": "One"}, "2": "Two"}}) == ["One", "Two"]
    assert enum_options({"enum_values": [{"label": "A"}, {"value": "B"}, "C", None]}) == [
        "A",
        "B",
        "C",
    ]
    assert enum_options({}) == []


def test_action_support_helpers() -> None:
    """Test action support helpers."""
    actions = {
        "turn_on_device_supported": {
            "supported_on_set": True,
            "supported_on_clear": False,
            "devices": [{"id": 1}],
        },
        "mute_alarm_supported": {"supported_on_set": True},
        "bad": {"supported_on_set": False, "supported_on_clear": False},
        "load_action_supported": {
            "load_identity_per_device": [{"loads": [{"id": "1"}, {"id": ""}, {}]}]
        },
    }
    assert action_supports_device(actions, "turn_on_device_supported", "1")
    assert not action_supports_device(actions, "turn_on_device_supported", "2")
    assert action_supports_device(actions, "mute_alarm_supported", "1")
    assert not action_supports_device(actions, "missing", "1")
    assert not action_supports_device(actions, "bad", "1")
    assert action_load_ids(actions) == {"1"}
    assert action_load_ids(
        {
            "load_action_supported": {
                "load_identity_per_device": [{"device_id": 1, "loads": [{"id": "2"}]}]
            }
        }
    ) == {"1:2"}
    multi_device_actions = {
        "load_action_supported": {
            "load_identity_per_device": [
                {"device_id": 1, "loads": [{"id": "2"}]},
                {"device_id": 2, "loads": [{"id": "2"}]},
            ]
        }
    }
    assert action_load_ids(multi_device_actions) == {"1:2", "2:2"}
    assert load_action_supported(multi_device_actions, {"device_id": 1, "id": "2"})
    assert not load_action_supported(multi_device_actions, {"device_id": 3, "id": "2"})
    assert action_load_ids({}) == set()
    assert action_load_ids({"load_action_supported": {}}) == set()
    assert action_load_ids(
        {"load_action_supported": {"load_identity_per_device": [None, {"loads": "bad"}]}}
    ) == set()


@pytest.mark.parametrize(
    ("label_text", "suffix", "unit", "device_class"),
    [
        ("Battery Capacity", "%", "%", "battery"),
        ("Utilization", "%", "%", None),
        ("Input Voltage", "Volts", "V", "voltage"),
        ("Output Current", "Amps", "A", "current"),
        ("Output Power", "Watts", "W", "power"),
        ("Output", "kW", "kW", "power"),
        ("Apparent Power", "VA", "VA", "apparent_power"),
        ("Reactive Power", "var", "var", "reactive_power"),
        ("Frequency", "Hz", "Hz", "frequency"),
        ("Energy", "kWh", "kWh", "energy"),
        ("Temperature", "Celsius", "°C", "temperature"),
        ("Temperature", "Fahrenheit", "°F", "temperature"),
        ("Runtime Remaining", "Minutes", "min", "duration"),
        ("Delay", "Seconds", "s", "duration"),
        ("Other", "widgets", "widgets", None),
    ],
)
def test_value_metadata(label_text: str, suffix: str, unit: str, device_class: str | None) -> None:
    """Test metadata inference."""
    metadata = value_metadata(label_text, suffix)
    assert metadata.native_unit_of_measurement == unit
    assert metadata.device_class == device_class


def test_metadata_misc() -> None:
    """Test metadata fallbacks and native values."""
    assert normalized_text(" A ", None) == "a"
    assert value_metadata("Power Factor", "%").device_class == "power_factor"
    assert value_metadata("No Unit", None).native_unit_of_measurement is None
    assert value_metadata("Output 24hr Energy", "kWh").state_class == "measurement"
    assert native_variable_value({"data_type": "VARTYPE_INTEGER", "value": "3.2"}) == 3
    assert native_variable_value({"data_type": "VARTYPE_FLOAT", "value": "3.2"}) == 3.2
    assert native_variable_value({"numeric": True, "value": "4.5"}) == 4.5
    assert native_variable_value({"data_type": "VARTYPE_STRING", "value": "ok"}) == "ok"
    assert "voltage" in LOAD_METRICS
