# Supported WebcardLX API Surface

This integration implements the WebcardLX API surfaces that are relevant to the supported UPS models and safe to represent in Home Assistant.

| API surface | Status | Home Assistant exposure |
| --- | --- | --- |
| `/api/oauth/token`, `/api/oauth/refresh`, `/api/oauth/token/logout` | Implemented | Config flow, setup, token refresh, unload |
| `/api/devices` | Implemented | Device registry, supported model validation, editable device-property service |
| `/api/variables` | Implemented | First-class UPS monitor sensors for status, runtime, battery, input, output, load/utilization, and temperature readings; online/on-battery/discharging binary sensors; binary sensors; number/select/switch/text entities for editable variables |
| `/api/loads` | Implemented | Load state sensors, load metric sensors, load switches |
| `/api/loads_execute/*` | Implemented | Load switches, load cycle buttons, `execute_load_action` service |
| `/api/actions/supported` | Implemented | Capability gating for UPS power and load controls |
| `/api/controls_turnon_device/execute` | Implemented | Disabled-by-default button and service |
| `/api/controls_turnoff_device/execute` | Implemented | Disabled-by-default button and service |
| `/api/controls_reboot_device/execute` | Implemented | Disabled-by-default button and service |
| `/api/alarms`, `/api/alarms/summary` | Implemented | Alarm binary sensor, alarm count sensors, diagnostics |
| `/api/alarms/acknowledge`, `/api/alarms/acknowledge/all` | Implemented | Alarm acknowledgement services and button |
| `/api/ready`, `/api/system_details`, `/api/system_uptime` | Implemented | Disabled-by-default diagnostic sensors |
| `/api/events` | Polled for diagnostics | Not exposed as entities |
| `/api/schedulings/supported` | Polled for diagnostics | Not exposed as scheduler CRUD |
| Email/SMS/SNMP contacts and action-rule CRUD | Not exposed | Card administration, not UPS model functionality |
| Local users, password, AAA, AutoProbe, log export | Not exposed | Card administration/maintenance surface |

The integration filters data to supported UPS device IDs before entities are created.

The WebcardLX client is embedded in this custom integration. If this code is prepared
for Home Assistant Core, the client should be split into a separately versioned async
library and listed in `manifest.json` requirements.
