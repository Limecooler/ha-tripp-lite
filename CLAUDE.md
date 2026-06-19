# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom integration for Tripp Lite WebcardLX UPS monitoring cards. It talks to the local PowerAlert Device Manager REST API and integrates with HA's config entry, coordinator, diagnostics, reauth, and DHCP discovery patterns. Quality scale: Gold.

## Development Commands

```bash
# Install test dependencies
python -m pip install -e ".[test]"

# Run all tests (100% coverage required)
pytest tests/components/tripp_lite_webcardlx

# Run a single test file or test
pytest tests/components/tripp_lite_webcardlx/test_api.py
pytest tests/components/tripp_lite_webcardlx/test_api.py::test_normalize_base_url_adds_https

# Lint
ruff check custom_components/tripp_lite_webcardlx tests/components/tripp_lite_webcardlx

# Smoke test against a real device
WEBCARDLX_PASSWORD='secret' python scripts/webcardlx_smoke_test.py 192.168.1.50 --insecure --verbose
```

CI also validates JSON/YAML metadata files (manifest.json, strings.json, icons.json, translations/, services.yaml, quality_scale.yaml) and runs `python -m compileall`. Keep these valid when making changes.

## Architecture

### Data Flow

`Config Entry → WebcardLXClient (api.py) → WebcardLXDataUpdateCoordinator (coordinator.py) → Platforms`

The coordinator polls on a configurable interval (default 30s, min 10s). Data is stored as a dict with keys: `devices`, `variables`, `loads`, `load_groups`, `actions_supported`, `schedules_supported`, `alarm_summary`, `alarms`, `events`, `ready`, `system_details`, `system_uptime`. Some of these refresh less frequently (static metadata at 10 min, events at 5 min).

### API Client (`api.py`)

Async REST client wrapping the PowerAlert Device Manager JSON:API. Key behaviors:
- Bearer token auth with automatic refresh on 401
- Optional endpoints (loads, alarms, events, system_details, etc.) fail soft — the coordinator logs a warning and returns cached/safe defaults rather than raising
- `normalize_base_url()` strips paths/query params and adds `https://` if no scheme given
- `data_list()` / `data_object()` flatten JSON:API responses by merging `attributes` with `id`/`type`

### Entity Architecture

All entities extend `WebcardLXEntity` → `CoordinatorEntity`. `_attr_has_entity_name = True` is set on the base class. Device identity uses serial number as the primary unique identifier, falling back to entry+device_id.

Non-main loads create **child devices** in HA (via `via_device`). The main load reuses the parent UPS device.

Entity classification decisions:
- **Sensors** (`sensor.py`): High-priority UPS variables are matched by label patterns in `UPS_VARIABLE_SENSOR_DESCRIPTIONS` and enabled by default. Generic variable sensors are disabled by default if the variable is editable.
- **Binary sensors** (`binary_sensor.py`): Boolean variables; UPS power state (inferred from status variable text); active alarm indicator.
- **Switches** (`switch.py`): Load switches (controllable outputs) and boolean editable variables.
- **Number/Select/Text** (`number.py`, `select.py`, `text.py`): Editable variables by type — all disabled by default in CONFIG entity category.
- **Buttons** (`button.py`): Load cycle, device turn_on/turn_off/reboot, acknowledge-all-alarms.

### Variable Matching

`helpers.py` contains the core classification logic. Variables are matched to devices via `device_id`. Key functions:
- `is_editable_variable()` — has `editable` flag or `SUPPORTS_UPDATE` in supports set
- `is_sensitive_attributes()` — detects passwords/tokens to exclude from diagnostics and text entities
- `supported_device_ids()` — filters devices to supported UPS models; falls back to any device with DEVICE_TYPE_UPS variables when `allow_unsupported_model=True`
- `is_supported_model()` — normalizes model string (strips non-alphanumeric) and checks against `SUPPORTED_UPS_MODELS`

Sensor metadata (unit, device_class, state_class) is inferred from variable label text in `metadata.py:value_metadata()`.

### Services (`__init__.py`)

Six services registered on the domain:
- `execute_load_action` — on/off/cycle a load switch entity
- `execute_device_action` — turn_on/turn_off/reboot a UPS device
- `acknowledge_alarms` / `acknowledge_all_alarms`
- `set_variable` — write a value to a number/select/switch/text config entity
- `update_device_properties` — update device metadata (name, location, etc.)

All services accept HA entity or device targets (not raw API IDs) and translate them through `_load_targets_from_call()`, `_variable_targets_from_call()`, or `_device_targets_from_call()`.

### Config Flow

VERSION=1, MINOR_VERSION=2. Steps: user (manual), dhcp (discovery), reconfigure, reauth. Unique ID priority: MAC → serial → asset_tag → URL. Config entry migration from v1.1 to v1.2 moves `scan_interval` and `allow_unsupported_model` from data to options.

### Supported Models

`SUPPORTED_UPS_MODELS` in `const.py` is the allowlist. Model matching is fuzzy (normalized, substring). Adding a new model only requires updating this set (and the README).
