"""Metadata helpers for WebcardLX entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.const import PERCENTAGE

from .helpers import as_float, as_int, raw_value


@dataclass(frozen=True)
class ValueMetadata:
    """HA metadata inferred from a WebcardLX value."""

    native_unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    suggested_display_precision: int | None = None


MEASUREMENT = "measurement"
TOTAL_INCREASING = "total_increasing"


def normalized_text(*values: Any) -> str:
    """Return a normalized searchable string."""
    return " ".join(str(value).strip().lower() for value in values if value not in (None, ""))


def value_metadata(label: str, suffix: str | None) -> ValueMetadata:
    """Infer Home Assistant metadata from a vendor label and unit suffix."""
    text = normalized_text(label, suffix)
    unit = str(suffix or "").strip()
    unit_lower = unit.lower()

    if unit in {"%", "Percent"} or unit_lower in {"percent", "percentage"}:
        if "battery" in text and "capacity" in text:
            return ValueMetadata(PERCENTAGE, "battery", MEASUREMENT, 0)
        if "power factor" in text:
            return ValueMetadata(PERCENTAGE, "power_factor", MEASUREMENT, 0)
        return ValueMetadata(PERCENTAGE, None, MEASUREMENT, 0)

    if unit_lower in {"v", "volt", "volts", "vac", "vdc"} or "voltage" in text:
        return ValueMetadata("V", "voltage", MEASUREMENT, 1)

    if unit_lower in {"a", "amp", "amps", "ampere", "amperes"} or "current" in text:
        return ValueMetadata("A", "current", MEASUREMENT, 2)

    if unit_lower in {"w", "watt", "watts"} or " watt" in f" {text}":
        return ValueMetadata("W", "power", MEASUREMENT, 0)

    if unit_lower in {"kw", "kilowatt", "kilowatts"}:
        return ValueMetadata("kW", "power", MEASUREMENT, 2)

    if unit_lower in {"va", "volt-amps", "volt amps"} or "apparent power" in text:
        return ValueMetadata("VA", "apparent_power", MEASUREMENT, 0)

    if unit_lower in {"var", "vars", "volt-amp reactive"} or "reactive power" in text:
        return ValueMetadata("var", "reactive_power", MEASUREMENT, 0)

    if unit_lower in {"hz", "hertz"} or "frequency" in text:
        return ValueMetadata("Hz", "frequency", MEASUREMENT, 1)

    if unit_lower in {"kwh", "kw h", "kilowatt-hour", "kilowatt hours"} or "energy" in text:
        if "24hr" in text or "24 hour" in text or "24-hour" in text or "rolling" in text:
            return ValueMetadata("kWh", "energy", MEASUREMENT, 2)
        return ValueMetadata("kWh", "energy", TOTAL_INCREASING, 2)

    if unit_lower in {"f", "°f", "deg f", "fahrenheit"}:
        return ValueMetadata("°F", "temperature", MEASUREMENT, 1)

    if unit_lower in {"c", "°c", "deg c", "celsius"}:
        return ValueMetadata("°C", "temperature", MEASUREMENT, 1)

    if unit_lower in {"minutes", "minute", "mins", "min"} or "runtime" in text:
        return ValueMetadata("min", "duration", MEASUREMENT, 0)

    if unit_lower in {"seconds", "second", "secs", "sec"}:
        return ValueMetadata("s", "duration", MEASUREMENT, 0)

    return ValueMetadata(unit or None, None, MEASUREMENT if unit else None, None)


def native_variable_value(attributes: dict[str, Any]) -> Any:
    """Return a typed native value for a variable."""
    value = raw_value(attributes)
    data_type = str(attributes.get("data_type") or "").upper()
    numeric = bool(attributes.get("numeric"))
    if data_type in {"VARTYPE_INTEGER", "VARTYPE_ENUMINTEGER"}:
        parsed_int = as_int(value)
        return parsed_int if parsed_int is not None else value
    if data_type in {"VARTYPE_FLOAT"} or numeric:
        parsed_float = as_float(value)
        return parsed_float if parsed_float is not None else value
    return value


LOAD_METRICS: dict[str, tuple[str, str | None]] = {
    "voltage": ("voltage_supported", "V"),
    "current": ("current_supported", "A"),
    "power": ("power_supported", "W"),
    "apparent_power": ("apparent_power_supported", "VA"),
    "reactive_power": ("reactive_power_supported", "var"),
    "power_factor": ("power_factor_supported", PERCENTAGE),
    "frequency": ("frequency_supported", "Hz"),
    "utilization": ("utilization_supported", PERCENTAGE),
    "output_24hr_energy": ("output_24hr_energy_supported", "kWh"),
    "peak_power": ("peak_power_supported", "W"),
    "crest_factor": ("crest_factor_supported", None),
    "current_limit": ("current_limit_supported", "A"),
    "power_limit": ("power_limit_supported", "W"),
}
