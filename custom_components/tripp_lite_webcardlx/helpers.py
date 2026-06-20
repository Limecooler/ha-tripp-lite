"""Shared helpers for the Tripp Lite WebcardLX integration."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from hashlib import sha1
from typing import Any

from homeassistant.util import slugify

from .api import normalize_model
from .const import SUPPORTED_UPS_MODELS, SUPPORTS_UPDATE

_NORMALIZED_SUPPORTED_MODELS: frozenset[str] = frozenset(
    normalize_model(m) for m in SUPPORTED_UPS_MODELS
)

TRUTHY = {"1", "true", "yes", "on", "enabled", "enable", "active"}
FALSY = {"0", "false", "no", "off", "disabled", "disable", "inactive"}
SENSITIVE_TEXT_TERMS = {
    "api key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "password",
    "passphrase",
    "passwd",
    "private key",
    "secret",
    "token",
}


def stable_slug(value: Any, fallback: str) -> str:
    """Return a stable slug for a value."""
    text = str(value or "").strip()
    if not any(char.isalnum() for char in text):
        return fallback
    return slugify(text) or fallback


def stable_unique_suffix(value: Any, fallback: str) -> str:
    """Return a human-readable unique suffix for raw API identifiers."""
    text = str(value or "").strip()
    slug = stable_slug(text, fallback)
    if text.lower() == slug:
        return slug
    digest = sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}"


def as_bool(value: Any) -> bool | None:
    """Parse a WebcardLX boolean-ish value."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    return None


def as_float(value: Any) -> float | None:
    """Parse a number from a WebcardLX value."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    text = str(value).strip().replace(",", "")
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def as_int(value: Any) -> int | None:
    """Parse an integer from a WebcardLX value."""
    numeric = as_float(value)
    if numeric is None:
        return None
    try:
        return int(numeric)
    except (OverflowError, ValueError):
        return None


def raw_value(attributes: Mapping[str, Any]) -> Any:
    """Return the most useful variable value."""
    value = attributes.get("raw_value")
    if value in (None, ""):
        value = attributes.get("value")
    return value


def supports(attributes: Mapping[str, Any]) -> set[str]:
    """Return normalized support flags for a variable."""
    value = attributes.get("supports")
    if isinstance(value, str):
        return {value}
    if isinstance(value, Iterable):
        return {str(item) for item in value}
    return set()


def is_editable_variable(attributes: Mapping[str, Any]) -> bool:
    """Return whether a variable can be updated."""
    return bool(attributes.get("editable")) or SUPPORTS_UPDATE in supports(attributes)


def is_sensitive_attributes(attributes: Mapping[str, Any]) -> bool:
    """Return whether attributes appear to describe a sensitive value."""
    if attributes.get("password"):
        return True
    text = " ".join(
        str(attributes.get(key) or "").lower()
        for key in ("key", "label", "display_label", "name", "description", "type")
    )
    return any(term in text for term in SENSITIVE_TEXT_TERMS)


def device_id(attributes: Mapping[str, Any]) -> str:
    """Return a device id as a string."""
    value = attributes.get("device_id", attributes.get("id"))
    return str(value) if value not in (None, "") else ""


def variable_id(attributes: Mapping[str, Any]) -> str:
    """Return a variable id as a string."""
    value = attributes.get("id")
    return str(value) if value not in (None, "") else ""


def composite_key(attributes: Mapping[str, Any]) -> str:
    """Return a stable per-device object key."""
    value = attributes.get("device_id")
    current_device_id = str(value) if value not in (None, "") else ""
    object_id = variable_id(attributes)
    if current_device_id and object_id:
        return f"{current_device_id}:{object_id}"
    return object_id


def variable_key(attributes: Mapping[str, Any]) -> str:
    """Return a stable variable map key."""
    return composite_key(attributes)


def variable_unique_key(attributes: Mapping[str, Any]) -> str:
    """Return a stable variable key."""
    key = attributes.get("key")
    if key not in (None, ""):
        return str(key)
    var_id = variable_id(attributes)
    if var_id:
        return var_id
    return stable_slug(attributes.get("label") or attributes.get("display_label"), "variable")


def load_id(attributes: Mapping[str, Any]) -> str:
    """Return a load id as a string."""
    value = attributes.get("id")
    return str(value) if value not in (None, "") else ""


def load_key(attributes: Mapping[str, Any]) -> str:
    """Return a stable load map key."""
    current_device_id = device_id(attributes)
    current_load_id = load_id(attributes)
    if current_device_id and current_load_id:
        return f"{current_device_id}:{current_load_id}"
    return current_load_id


def is_main_load(attributes: Mapping[str, Any]) -> bool:
    """Return whether a load represents the UPS main output."""
    current_load_id = load_id(attributes).lower()
    return current_load_id == "main" or as_int(attributes.get("load_number")) == 0


def label(attributes: Mapping[str, Any], fallback: str) -> str:
    """Return a display label from API attributes."""
    value = attributes.get("display_label") or attributes.get("label") or attributes.get("name")
    return str(value).strip() if value not in (None, "") else fallback


def is_supported_model(model: str | None) -> bool:
    """Return whether the model is one of the explicitly supported UPS models."""
    normalized = normalize_model(model)
    return any(s in normalized for s in _NORMALIZED_SUPPORTED_MODELS)


def supported_device_ids(
    devices: Iterable[Mapping[str, Any]],
    variables: Iterable[Mapping[str, Any]],
    *,
    allow_unsupported_model: bool,
) -> set[str]:
    """Return device IDs for supported UPS devices."""
    explicit = {
        device_id(device)
        for device in devices
        if is_supported_model(str(device.get("model", "")))
    }
    explicit.discard("")
    if explicit or not allow_unsupported_model:
        return explicit

    ups_variable_ids = {
        device_id(variable)
        for variable in variables
        if variable.get("device_type") == "DEVICE_TYPE_UPS"
    }
    ups_variable_ids.discard("")
    return ups_variable_ids


def discovered_models(devices: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return discovered model names."""
    models = sorted(
        {m for device in devices if (m := str(device.get("model", "")).strip())}
    )
    return models


def enum_options(attributes: Mapping[str, Any]) -> list[str]:
    """Return select options for a variable enum."""
    enum_values = attributes.get("enum_values")
    if isinstance(enum_values, Mapping):
        values: list[str] = []
        for key, value in enum_values.items():
            if isinstance(value, Mapping):
                option = value.get("name") or value.get("label") or value.get("value") or key
            else:
                option = value or key
            values.append(str(option))
        return values
    if isinstance(enum_values, list):
        values = []
        for item in enum_values:
            if isinstance(item, Mapping):
                option = item.get("name") or item.get("label") or item.get("value")
            else:
                option = item
            if option not in (None, ""):
                values.append(str(option))
        return values
    return []


def action_supports_device(
    actions_supported: Mapping[str, Any],
    support_key: str,
    current_device_id: str,
) -> bool:
    """Return whether a supported-action entry includes the device."""
    support = actions_supported.get(support_key)
    if not isinstance(support, Mapping):
        return False
    if not (support.get("supported_on_set") or support.get("supported_on_clear")):
        return False
    devices = support.get("devices")
    if not isinstance(devices, list):
        return True
    return any(
        str(item.get("id")) == current_device_id
        for item in devices
        if isinstance(item, Mapping)
    )


def action_load_ids(actions_supported: Mapping[str, Any]) -> set[str]:
    """Return per-device load keys listed by action support metadata."""
    support = actions_supported.get("load_action_supported")
    if not isinstance(support, Mapping):
        return set()
    per_device = support.get("load_identity_per_device")
    if not isinstance(per_device, list):
        return set()
    load_ids: set[str] = set()
    allow_bare_ids = len(per_device) == 1
    for item in per_device:
        if not isinstance(item, Mapping):
            continue
        current_device_id = str(
            item.get("device_id")
            or item.get("deviceId")
            or item.get("device")
            or item.get("id")
            or ""
        )
        loads = item.get("loads")
        if not isinstance(loads, list):
            continue
        for load in loads:
            if isinstance(load, Mapping) and load.get("id") not in (None, ""):
                current_load_id = str(load["id"])
                if current_device_id:
                    load_ids.add(f"{current_device_id}:{current_load_id}")
                elif allow_bare_ids:
                    load_ids.add(current_load_id)
    return load_ids


def load_action_supported(actions_supported: Mapping[str, Any], load: Mapping[str, Any]) -> bool:
    """Return whether a load is currently reported as controllable."""
    current_load_key = load_key(load)
    current_load_id = load_id(load)
    supported_load_ids = action_load_ids(actions_supported)
    has_composite_support = any(":" in item for item in supported_load_ids)
    return (
        bool(load.get("controllable"))
        or current_load_key in supported_load_ids
        or (not has_composite_support and current_load_id in supported_load_ids)
    )
