# Tripp Lite WebcardLX for Home Assistant

Custom Home Assistant integration for Tripp Lite/Eaton WebcardLX cards installed in:

- Tripp Lite `SU1000XLA`
- Tripp Lite `SU1500RTXL2U`
- Tripp Lite `SU1500RTXL2UA`

The integration uses the local PowerAlert Device Manager REST API documented by Tripp Lite/Eaton and follows Home Assistant’s config entry, diagnostics, reauth, reconfigure, and entity naming patterns.

## Installation

### HACS

This integration can be installed with HACS as a custom repository.

1. Make sure [HACS](https://www.hacs.xyz/) is installed and configured in Home Assistant.
2. In Home Assistant, go to **HACS > Integrations**.
3. Open the three-dot menu and select **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/Limecooler/ha-tripp-lite
   ```

5. Select **Integration** as the category and click **Add**.
6. Search HACS for **Tripp Lite WebcardLX**.
7. Select the integration and click **Download**.
8. Restart Home Assistant.
9. Go to **Settings > Devices & services > Add integration**.
10. Search for **Tripp Lite WebcardLX**.
11. Enter the WebcardLX URL, username, password, and SSL verification preference.

If this repository is private, the GitHub account or token configured in HACS must have access to `Limecooler/ha-tripp-lite`. Public custom repositories do not need additional repository-specific access.

### Manual

1. Copy `custom_components/tripp_lite_webcardlx` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration**.
4. Search for **Tripp Lite WebcardLX**.
5. Enter the WebcardLX URL, username, password, and SSL verification preference.

Use a full local URL such as `https://192.168.1.50` or `http://192.168.1.50`. WebcardLX devices often use self-signed HTTPS certificates; disable SSL verification only when required for that local device.

## Prerequisites And Permissions

Create or select a WebcardLX user that can read UPS variables, loads, alarms, actions, ready state, and system details. To use buttons, switches, or services that control loads, reboot the UPS, turn outputs on or off, acknowledge alarms, or edit variables, the WebcardLX user must also have the matching control permissions.

UPS output controls are intentionally disabled by default where Home Assistant supports that behavior. Turning off, rebooting, or cycling a UPS or load can immediately interrupt connected equipment. Test controls with non-critical loads first.

## Supported Devices

By default the integration only creates entities for UPS device records whose model normalizes to `SU1000XLA`, `SU1500RTXL2U`, or `SU1500RTXL2UA`. Variables and loads from connected peripheral devices are filtered out.

The scan interval and advanced `allow_unsupported_model` lab-test setting are integration options. Leave `allow_unsupported_model` disabled for the supported-device behavior requested for this integration.

## Discovery And Identity

DHCP discovery is intentionally narrow and matches WebcardLX-style Tripp Lite hostnames instead of broad Eaton hostnames. When possible, the integration uses the WebcardLX MAC address, serial number, and system details to keep rediscovery tied to the same card and to update the network URL only for matching registered devices.

UPS devices always get stable fallback identifiers and serial numbers when the card reports them. The WebcardLX card MAC is used for discovery/config-entry identity, but it is not attached to every UPS device because one card can report multiple UPS devices. Non-main controllable loads/outlets are represented as child devices linked to the UPS device; the main output remains on the UPS device.

## Entities

The integration dynamically discovers supported functionality from the card, so entities are only created when the API reports the relevant data or capability.

### Sensors

Primary UPS monitor sensors are created from `/api/variables` when the card reports matching data:

- UPS status
- Runtime remaining
- Battery capacity and battery voltage
- Input voltage, current, and frequency
- Output voltage, current, frequency, power, apparent power, reactive power, power factor, and utilization
- Temperature

Additional readable UPS variables are exposed dynamically as sensors when they are not passwords, not empty, not editable settings, and not better represented as binary sensors.

### Diagnostic Sensors

The integration also creates diagnostic sensors for:

- Load/outlet state and metrics from `/api/loads`
- Alarm counts and highest severity from `/api/alarms/summary`
- WebcardLX ready/system detail/uptime diagnostics

Recent alarms from `/api/alarms`, supported action metadata from `/api/actions/supported`, and supported scheduling metadata from `/api/schedulings/supported` are collected for diagnostics and capability gating.

### Binary Sensors

Binary sensors include:

- Online
- On battery
- Battery discharging
- Active alarms
- Boolean UPS status variables such as low-battery, fault, overload, or replace-battery indicators

### Switches

- Controllable load on/off switches
- Editable boolean variables as configuration switches, disabled by default

### Buttons

Buttons are created only when `/api/actions/supported` reports matching support:

- Load cycle buttons, disabled by default
- UPS turn on/off/reboot buttons, disabled by default
- Acknowledge all alarms button

### Configuration Entities

Editable WebcardLX variables are exposed as `number`, `select`, `switch`, or `text` entities when the API reports the variable as editable. These entities are disabled by default because they represent configuration changes rather than routine monitoring.

### Services

Services are provided for load actions, UPS power actions, alarm acknowledgement, variable updates, and editable device properties. Services use Home Assistant entity, device, or config-entry targets. They do not accept raw WebcardLX variable IDs, load IDs, or implicit "only entry" defaults.

The WebcardLX API also includes broad card-administration surfaces such as local users, passwords, AAA servers, email/SMS/SNMP contacts, notification action-rule CRUD, AutoProbe management, log export, and schedule CRUD. Those are not exposed as entities because they are management-plane features of the card rather than UPS capabilities specific to the supported SU models.

## Data Updates

The integration uses a `DataUpdateCoordinator` and local polling. The default polling interval is 30 seconds; the minimum accepted interval is 10 seconds.

Required polling surfaces are `/api/devices` and `/api/variables`. If either fails, the coordinator update fails and entities become unavailable through Home Assistant’s normal coordinator behavior.

Other surfaces are optional and fail soft: loads, load groups, controls, actions, schedules, alarms, events, ready state, system details, and uptime. Endpoint-specific failures are logged and replaced with safe defaults so core UPS sensors can remain available when a card user lacks a permission or a firmware build omits a surface. A `403` on an optional endpoint is treated as permission or capability failure, not automatic reauthentication.

Variables, loads, alarm summary, ready state, and uptime refresh on every normal poll. Static or slow metadata refreshes less often: actions, schedules, load groups, control metadata, and system details refresh every 10 minutes. Events refresh every 5 minutes and are limited to the newest records. Requests use a 10 second total timeout with a 5 second connect timeout.

## Services

### `tripp_lite_webcardlx.execute_load_action`

Runs an action against a targeted WebcardLX load switch entity. Target one or more `switch` entities created by this integration.

Required fields:

- `target.entity_id`: load switch entities
- `action`: `on`, `off`, or `cycle`

### `tripp_lite_webcardlx.execute_device_action`

Runs immediate UPS device controls documented by the API. Target one or more Home Assistant UPS devices created by this integration.

Required fields:

- `target.device_id`
- `action`: `turn_on`, `turn_off`, or `reboot`

Optional fields:

- `delay`
- `turn_on_delay`
- `turn_off_delay`

### `tripp_lite_webcardlx.acknowledge_alarms`

Acknowledges specific active alarm IDs for an explicit config entry. Alarm IDs are validated against the current coordinator data.

Required fields:

- `config_entry_id`
- `alarm_ids`

### `tripp_lite_webcardlx.acknowledge_all_alarms`

Acknowledges all active alarms for an explicit config entry.

Required fields:

- `config_entry_id`

### `tripp_lite_webcardlx.set_variable`

Updates a targeted WebcardLX configuration entity. Target a `number`, `select`, `switch`, or `text` entity created by this integration. The service validates the current variable capability before writing and rejects password variables.

Required fields:

- `target.entity_id`
- `value`

Optional fields:

- `tolerance`

### `tripp_lite_webcardlx.update_device_properties`

Updates editable UPS device metadata. Target one or more Home Assistant UPS devices. The allowed fields are `name`, `location`, `region`, `configured_device_id`, `configured_asset_tag`, and `install_date`.

## Automation Examples

Notify when the UPS has an active alarm:

```yaml
alias: UPS active alarm
triggers:
  - trigger: state
    entity_id: binary_sensor.ups_active_alarms
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      message: "The UPS has an active alarm."
```

Turn off a controllable load:

```yaml
action: tripp_lite_webcardlx.execute_load_action
target:
  entity_id: switch.rack_ups_load_1
data:
  action: off
```

Update an editable threshold variable:

```yaml
action: tripp_lite_webcardlx.set_variable
target:
  entity_id: number.rack_ups_low_battery_threshold
data:
  value: 25
  tolerance: 0.5
```

Notify when the UPS transfers to battery:

```yaml
alias: UPS on battery
triggers:
  - trigger: state
    entity_id: binary_sensor.ups_on_battery
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      message: "The UPS is running on battery."
```

## Reconfiguration And Reauthentication

Use the integration’s **Reconfigure** flow to change URL, credentials, or SSL verification. Password fields use password selectors and are not prefilled; leaving the password blank during reconfigure keeps the stored password.

Use **Options** to change the scan interval or unsupported-model testing option.

If authentication fails during setup or polling, Home Assistant starts the reauthentication flow.

## Diagnostics

Diagnostics are available from the integration’s device/service page. The diagnostics output includes config entry data and the last coordinator payload with sensitive values redacted, including URLs, usernames, passwords, tokens, authorization headers, serial numbers, MAC addresses, asset tags, location/contact-style fields, and raw alarm/event text.

## Troubleshooting

- `cannot_connect`: Confirm the URL, scheme, port, routing, and that PowerAlert Device Manager is reachable from Home Assistant.
- `invalid_auth`: Confirm the WebcardLX local username and password.
- `unsupported_model`: Confirm the UPS model is one of `SU1000XLA`, `SU1500RTXL2U`, or `SU1500RTXL2UA`.
- Self-signed HTTPS certificate failures: reconfigure the integration and disable SSL verification for that local card.
- Missing load switches: check whether `/api/actions/supported` and `/api/loads` report load control support and `controllable: true`.
- Missing UPS status sensors: check whether `/api/variables` includes a status, operating mode, power source, input source, line status, online, on-battery, or battery-discharging variable.

Direct API checks can help isolate permissions and device capability issues. Replace the host, username, and password with values from your environment. The token extraction below accepts both flat and JSON:API-style token responses:

```sh
TOKEN="$(
  curl -sk -X POST "https://192.168.1.50/api/oauth/token" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"secret","grant_type":"password"}' \
  | jq -r '.access_token // .data.attributes.access_token'
)"

curl -k -H "Authorization: Bearer ${TOKEN}" https://192.168.1.50/api/variables
curl -k -H "Authorization: Bearer ${TOKEN}" https://192.168.1.50/api/actions/supported
curl -k -H "Authorization: Bearer ${TOKEN}" https://192.168.1.50/api/loads
curl -k -H "Authorization: Bearer ${TOKEN}" https://192.168.1.50/api/alarms/summary
```

If the API returns data but entities are missing, confirm the relevant variable or load belongs to a supported UPS device record rather than a connected peripheral. The integration filters variables and loads to the supported UPS device IDs and keeps vanished variables/loads unavailable rather than silently retargeting them.

## Repository Structure

The integration follows the standard Home Assistant component layout with `manifest.json`, `config_flow.py`, `coordinator.py`, platform files, `entity.py`, `diagnostics.py`, `services.yaml`, `strings.json`, `icons.json`, and `quality_scale.yaml`. The WebcardLX client is embedded in `api.py` for this custom integration; if this is prepared for Home Assistant Core, the client should be split into a separately versioned async library and listed in `manifest.json` requirements.

## Removal

1. Delete the integration entry from **Settings > Devices & services**.
2. Restart Home Assistant if you plan to remove the custom component files.
3. Delete `custom_components/tripp_lite_webcardlx`.

## References

- [Tripp Lite/Eaton PADM20 REST API documentation](https://assets.tripplite.com/owners-manual/padm20-api-documentation.html)
- [Home Assistant integration manifest documentation](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Home Assistant config flow documentation](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
