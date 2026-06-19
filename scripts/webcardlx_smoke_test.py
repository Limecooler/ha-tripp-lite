#!/usr/bin/env python3
"""Smoke-test a Tripp Lite WebcardLX device against the integration API client."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from getpass import getpass
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, TCPConnector

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.tripp_lite_webcardlx.api import (  # noqa: E402
    WebcardLXApiError,
    WebcardLXCannotConnect,
    WebcardLXClient,
    WebcardLXError,
    WebcardLXInvalidAuth,
)
from custom_components.tripp_lite_webcardlx.binary_sensor import (  # noqa: E402
    _is_binary_variable,
    _is_ups_power_state_variable,
)
from custom_components.tripp_lite_webcardlx.const import (  # noqa: E402
    LOAD_ACTION_CYCLE,
    LOAD_ACTION_OFF,
    LOAD_ACTION_ON,
    SERVICE_LOAD_ACTIONS,
)
from custom_components.tripp_lite_webcardlx.helpers import (  # noqa: E402
    action_supports_device,
    device_id,
    discovered_models,
    is_editable_variable,
    is_main_load,
    is_sensitive_attributes,
    label,
    load_action_supported,
    load_id,
    load_key,
    supported_device_ids,
    variable_id,
    variable_key,
)
from custom_components.tripp_lite_webcardlx.metadata import LOAD_METRICS  # noqa: E402
from custom_components.tripp_lite_webcardlx.number import _is_number_variable  # noqa: E402
from custom_components.tripp_lite_webcardlx.select import _is_select_variable  # noqa: E402
from custom_components.tripp_lite_webcardlx.sensor import (  # noqa: E402
    _is_ups_status_variable,
    _is_variable_sensor,
)
from custom_components.tripp_lite_webcardlx.switch import _is_switch_variable  # noqa: E402
from custom_components.tripp_lite_webcardlx.text import _is_text_variable  # noqa: E402

LOAD_ACTION_VALUES = {
    "on": LOAD_ACTION_ON,
    "off": LOAD_ACTION_OFF,
    "cycle": LOAD_ACTION_CYCLE,
    LOAD_ACTION_ON: LOAD_ACTION_ON,
    LOAD_ACTION_OFF: LOAD_ACTION_OFF,
    LOAD_ACTION_CYCLE: LOAD_ACTION_CYCLE,
}

DEVICE_PROPERTY_FIELDS = {
    "name",
    "location",
    "region",
    "configured_device_id",
    "configured_asset_tag",
    "install_date",
}

DEVICE_ACTION_SUPPORT_KEYS = {
    "turn_on": "turn_on_device_supported",
    "turn_off": "turn_off_device_supported",
    "reboot": "restart_device_supported",
}


@dataclass
class EndpointResult:
    """Result for a single endpoint smoke-test."""

    name: str
    ok: bool
    count: int | None = None
    detail: str = ""


@dataclass
class SmokeReport:
    """Collected smoke-test output."""

    endpoint_results: list[EndpointResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mutations: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _count_payload(value: Any) -> int | None:
    """Return a display count for endpoint payloads."""
    if isinstance(value, Mapping):
        return len(value)
    if isinstance(value, list):
        return len(value)
    return None


def _format_error(err: Exception) -> str:
    """Return a concise, sanitized error string."""
    if isinstance(err, WebcardLXApiError):
        return f"HTTP {err.status}"
    return str(err) or type(err).__name__


def _print_result(result: EndpointResult) -> None:
    """Print an endpoint result line."""
    status = "OK" if result.ok else "WARN"
    count = "" if result.count is None else f" ({result.count})"
    detail = "" if not result.detail else f": {result.detail}"
    print(f"[{status}] {result.name}{count}{detail}")


def _report_payload(report: SmokeReport) -> dict[str, Any]:
    """Return a sanitized JSON-serializable report payload."""
    return {
        "endpoints": [asdict(result) for result in report.endpoint_results],
        "warnings": report.warnings,
        "mutations": report.mutations,
        "summary": report.summary,
    }


def _write_report(path: Path, report: SmokeReport) -> None:
    """Write the smoke-test report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_report_payload(report), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Wrote report to {path}")


async def _fetch_endpoint(
    report: SmokeReport,
    name: str,
    fetch: Callable[[], Awaitable[Any]],
    *,
    required: bool,
    default: Any,
) -> Any:
    """Fetch one endpoint and record the result."""
    try:
        value = await fetch()
    except (WebcardLXApiError, WebcardLXCannotConnect) as err:
        result = EndpointResult(name, False, detail=_format_error(err))
        report.endpoint_results.append(result)
        _print_result(result)
        if required:
            raise
        return default

    result = EndpointResult(name, True, _count_payload(value))
    report.endpoint_results.append(result)
    _print_result(result)
    return value


def _filter_supported_devices(
    devices: list[dict[str, Any]],
    variables: list[dict[str, Any]],
    *,
    allow_unsupported_model: bool,
) -> set[str]:
    """Return supported device IDs with a warning-friendly wrapper."""
    return supported_device_ids(
        devices,
        variables,
        allow_unsupported_model=allow_unsupported_model,
    )


def _variables_for_supported_devices(
    variables: list[dict[str, Any]],
    active_device_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Return non-sensitive variables for active UPS devices."""
    return {
        variable_key(variable): variable
        for variable in variables
        if variable_key(variable)
        and device_id(variable) in active_device_ids
        and not is_sensitive_attributes(variable)
    }


def _loads_for_supported_devices(
    loads: list[dict[str, Any]],
    active_device_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Return UPS loads for active UPS devices."""
    return {
        load_key(load): load
        for load in loads
        if load_key(load)
        and device_id(load) in active_device_ids
        and load.get("device_type", "DEVICE_TYPE_UPS") == "DEVICE_TYPE_UPS"
    }


def _print_sample(items: list[dict[str, Any]], *, heading: str, verbose: bool) -> None:
    """Print sample API records without raw values."""
    if not verbose or not items:
        return
    print(f"\n{heading}:")
    for item in items[:10]:
        item_id = item.get("id")
        current_device_id = item.get("device_id")
        print(f"  - device={current_device_id} id={item_id} label={label(item, 'n/a')}")


def _summarize_entities(
    variables: dict[str, dict[str, Any]],
    loads: dict[str, dict[str, Any]],
    actions_supported: Mapping[str, Any],
) -> dict[str, int]:
    """Summarize entities the integration would generally expose."""
    load_metric_count = 0
    for load in loads.values():
        for metric_key, (supported_key, _unit) in LOAD_METRICS.items():
            if load.get(supported_key) and load.get(metric_key) not in (None, ""):
                load_metric_count += 1

    return {
        "sensor_variables": sum(
            1 for variable in variables.values() if _is_variable_sensor(variable)
        ),
        "ups_status_sensors": sum(
            1 for variable in variables.values() if _is_ups_status_variable(variable)
        ),
        "binary_variables": sum(
            1 for variable in variables.values() if _is_binary_variable(variable)
        ),
        "ups_power_binary_sensors": sum(
            1 for variable in variables.values() if _is_ups_power_state_variable(variable)
        ),
        "number_config_entities": sum(
            1 for variable in variables.values() if _is_number_variable(variable)
        ),
        "select_config_entities": sum(
            1 for variable in variables.values() if _is_select_variable(variable)
        ),
        "switch_config_entities": sum(
            1 for variable in variables.values() if _is_switch_variable(variable)
        ),
        "text_config_entities": sum(
            1 for variable in variables.values() if _is_text_variable(variable)
        ),
        "load_switches": sum(
            1
            for load in loads.values()
            if load_action_supported(actions_supported, load)
        ),
        "load_state_sensors": len(loads),
        "load_metric_sensors": load_metric_count,
    }


def _print_summary(
    report: SmokeReport,
    devices: list[dict[str, Any]],
    variables: dict[str, dict[str, Any]],
    loads: dict[str, dict[str, Any]],
    actions_supported: Mapping[str, Any],
    alarm_summary: Mapping[str, Any],
    alarms: list[dict[str, Any]],
    *,
    active_device_ids: set[str],
    verbose: bool,
) -> None:
    """Print a concise integration-focused summary."""
    entity_summary = _summarize_entities(variables, loads, actions_supported)
    report.summary.update(
        {
            "models": discovered_models(devices),
            "active_device_ids": sorted(active_device_ids),
            "variables_after_filter": len(variables),
            "loads_after_filter": len(loads),
            "entity_summary": entity_summary,
            "alarm_summary": dict(alarm_summary),
            "active_alarm_ids": [
                str(alarm.get("id"))
                for alarm in alarms
                if alarm.get("id") not in (None, "")
            ],
        }
    )

    print("\nSupported UPS devices:")
    print(f"  Models discovered: {', '.join(discovered_models(devices)) or 'none'}")
    print(f"  Active device IDs: {', '.join(sorted(active_device_ids)) or 'none'}")

    print("\nFiltered integration data:")
    print(f"  Variables: {len(variables)}")
    print(f"  Loads/outlets: {len(loads)}")
    if alarm_summary:
        print(f"  Alarm summary: {json.dumps(dict(alarm_summary), sort_keys=True)}")

    print("\nApproximate entity coverage:")
    for key, count in sorted(entity_summary.items()):
        print(f"  {key}: {count}")

    load_switches = [
        load
        for load in loads.values()
        if load_action_supported(actions_supported, load)
    ]
    _print_sample(list(variables.values()), heading="Variable sample", verbose=verbose)
    _print_sample(load_switches, heading="Controllable load sample", verbose=verbose)


def _find_variable(
    variables: list[dict[str, Any]],
    current_variable_id: str,
) -> dict[str, Any] | None:
    """Find a variable by raw WebcardLX variable ID."""
    for variable in variables:
        if variable_id(variable) == current_variable_id:
            return variable
    return None


def _find_load(
    loads: list[dict[str, Any]],
    current_load_id: str,
    current_device_id: str,
) -> dict[str, Any] | None:
    """Find a load by raw WebcardLX load and device IDs."""
    for load in loads:
        if load_id(load) == current_load_id and device_id(load) == current_device_id:
            return load
    return None


def _parse_key_value(value: str) -> tuple[str, str]:
    """Parse KEY=VALUE CLI input."""
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    key, item_value = value.split("=", 1)
    if key not in DEVICE_PROPERTY_FIELDS:
        allowed = ", ".join(sorted(DEVICE_PROPERTY_FIELDS))
        raise argparse.ArgumentTypeError(f"unsupported device property {key!r}; allowed: {allowed}")
    if not item_value:
        raise argparse.ArgumentTypeError("VALUE must not be empty")
    return key, item_value


def _require_mutation_flags(args: argparse.Namespace, *, power: bool = False) -> None:
    """Raise if mutation flags are missing."""
    if not args.allow_mutations:
        raise RuntimeError("mutation requested without --allow-mutations")
    if power and not args.i_understand_power_risk:
        raise RuntimeError("power-control mutation requested without --i-understand-power-risk")


async def _run_mutations(
    client: WebcardLXClient,
    args: argparse.Namespace,
    report: SmokeReport,
    *,
    variables: list[dict[str, Any]],
    loads: list[dict[str, Any]],
    actions_supported: Mapping[str, Any],
    alarms: list[dict[str, Any]],
) -> None:
    """Run optional explicit mutation checks."""
    if args.set_variable:
        _require_mutation_flags(args)
        current_variable_id, value = args.set_variable
        variable = _find_variable(variables, current_variable_id)
        if variable is None:
            raise RuntimeError(f"variable {current_variable_id} was not found")
        if is_sensitive_attributes(variable):
            raise RuntimeError(f"variable {current_variable_id} appears sensitive")
        if not is_editable_variable(variable):
            raise RuntimeError(f"variable {current_variable_id} is not editable")
        await client.async_update_variable(current_variable_id, value, args.tolerance)
        report.mutations.append(f"set variable {current_variable_id}")
        print(f"[OK] Set variable {current_variable_id}")

    if args.ack_alarm:
        _require_mutation_flags(args)
        known_alarm_ids = {
            str(alarm.get("id"))
            for alarm in alarms
            if alarm.get("id") not in (None, "")
        }
        unknown_alarm_ids = set(args.ack_alarm) - known_alarm_ids
        if unknown_alarm_ids:
            raise RuntimeError(f"unknown active alarm IDs: {', '.join(sorted(unknown_alarm_ids))}")
        await client.async_acknowledge_alarms(args.ack_alarm)
        report.mutations.append(f"ack alarms {','.join(args.ack_alarm)}")
        print(f"[OK] Acknowledged alarms: {', '.join(args.ack_alarm)}")

    if args.ack_all_alarms:
        _require_mutation_flags(args)
        await client.async_acknowledge_all_alarms()
        report.mutations.append("ack all alarms")
        print("[OK] Acknowledged all alarms")

    if args.update_device_property:
        _require_mutation_flags(args)
        attributes = dict(args.update_device_property)
        await client.async_update_device(args.update_device_property_device_id, attributes)
        report.mutations.append(f"update device {args.update_device_property_device_id}")
        print(f"[OK] Updated device {args.update_device_property_device_id}: {sorted(attributes)}")

    if args.execute_load:
        _require_mutation_flags(args, power=True)
        current_load_id, current_device_id, action = args.execute_load
        load = _find_load(loads, current_load_id, current_device_id)
        if load is None:
            raise RuntimeError(f"load {current_device_id}:{current_load_id} was not found")
        if not load_action_supported(actions_supported, load):
            raise RuntimeError(f"load {current_device_id}:{current_load_id} is not controllable")
        await client.async_execute_load(
            current_load_id,
            current_device_id,
            LOAD_ACTION_VALUES[action],
        )
        report.mutations.append(f"execute load {current_device_id}:{current_load_id} {action}")
        print(f"[OK] Executed load action {action} on {current_device_id}:{current_load_id}")

    if args.execute_main_load:
        _require_mutation_flags(args, power=True)
        current_device_id, action = args.execute_main_load
        main_load = next(
            (
                load
                for load in loads
                if device_id(load) == current_device_id and is_main_load(load)
            ),
            None,
        )
        if main_load and not load_action_supported(actions_supported, main_load):
            raise RuntimeError(f"main load for device {current_device_id} is not controllable")
        await client.async_execute_main_load(current_device_id, LOAD_ACTION_VALUES[action])
        report.mutations.append(f"execute main load {current_device_id} {action}")
        print(f"[OK] Executed main load action {action} on device {current_device_id}")

    if args.execute_device_action:
        _require_mutation_flags(args, power=True)
        current_device_id, action = args.execute_device_action
        support_key = DEVICE_ACTION_SUPPORT_KEYS[action]
        if not action_supports_device(actions_supported, support_key, current_device_id):
            raise RuntimeError(f"device {current_device_id} does not report support for {action}")
        await client.async_control_device(
            action,
            current_device_id,
            args.turn_on_delay,
            args.turn_off_delay,
        )
        report.mutations.append(f"execute device action {current_device_id} {action}")
        print(f"[OK] Executed device action {action} on device {current_device_id}")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test a WebcardLX card using the integration API client. "
            "Read-only by default."
        )
    )
    parser.add_argument("--url", default=os.getenv("WEBCARDLX_URL"), help="WebcardLX base URL")
    parser.add_argument(
        "--username",
        default=os.getenv("WEBCARDLX_USERNAME"),
        help="WebcardLX username",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("WEBCARDLX_PASSWORD"),
        help="WebcardLX password; omit to prompt",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for self-signed local WebcardLX HTTPS certificates",
    )
    parser.add_argument(
        "--allow-unsupported-model",
        action="store_true",
        help="Use DEVICE_TYPE_UPS fallback when the UPS model is not explicitly supported",
    )
    parser.add_argument(
        "--refresh-token-test",
        action="store_true",
        help="Refresh the OAuth token once after login",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a failure if optional endpoints fail or no supported UPS device is found",
    )
    parser.add_argument("--verbose", action="store_true", help="Print sample variable/load labels")
    parser.add_argument("--report-json", help="Write a sanitized JSON summary report")

    mutation = parser.add_argument_group("explicit mutation tests")
    mutation.add_argument(
        "--allow-mutations",
        action="store_true",
        help="Allow write/acknowledge operations requested by other flags",
    )
    mutation.add_argument(
        "--i-understand-power-risk",
        action="store_true",
        help="Required for load or UPS power-control operations",
    )
    mutation.add_argument(
        "--set-variable",
        nargs=2,
        metavar=("VARIABLE_ID", "VALUE"),
        help="Update an editable non-sensitive variable",
    )
    mutation.add_argument("--tolerance", type=float, help="Tolerance for --set-variable")
    mutation.add_argument("--ack-alarm", action="append", help="Acknowledge a current alarm ID")
    mutation.add_argument(
        "--ack-all-alarms",
        action="store_true",
        help="Acknowledge all active alarms",
    )
    mutation.add_argument(
        "--update-device-property-device-id",
        help="Device ID for --update-device-property entries",
    )
    mutation.add_argument(
        "--update-device-property",
        action="append",
        type=_parse_key_value,
        metavar="KEY=VALUE",
        help="Update editable device metadata; repeat for multiple fields",
    )
    mutation.add_argument(
        "--execute-load",
        nargs=3,
        metavar=("LOAD_ID", "DEVICE_ID", "ACTION"),
        help="Execute load action; ACTION is on, off, or cycle",
    )
    mutation.add_argument(
        "--execute-main-load",
        nargs=2,
        metavar=("DEVICE_ID", "ACTION"),
        help="Execute main load action; ACTION is on, off, or cycle",
    )
    mutation.add_argument(
        "--execute-device-action",
        nargs=2,
        metavar=("DEVICE_ID", "ACTION"),
        help="Execute UPS action; ACTION is turn_on, turn_off, or reboot",
    )
    mutation.add_argument("--turn-on-delay", type=int, default=0)
    mutation.add_argument("--turn-off-delay", type=int, default=0)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    """Validate CLI arguments that argparse cannot express cleanly."""
    missing = [
        name
        for name in ("url", "username")
        if not getattr(args, name)
    ]
    if missing:
        raise RuntimeError(f"missing required arguments: {', '.join(missing)}")
    if args.password is None:
        args.password = getpass("WebcardLX password: ")
    if not args.password:
        raise RuntimeError("password must not be empty")

    if args.update_device_property and not args.update_device_property_device_id:
        raise RuntimeError("--update-device-property requires --update-device-property-device-id")

    for option_name in ("execute_load", "execute_main_load"):
        value = getattr(args, option_name)
        if value and value[-1] not in LOAD_ACTION_VALUES:
            allowed = ", ".join(SERVICE_LOAD_ACTIONS)
            raise RuntimeError(
                f"--{option_name.replace('_', '-')} action must be one of: {allowed}"
            )

    if (
        args.execute_device_action
        and args.execute_device_action[-1] not in DEVICE_ACTION_SUPPORT_KEYS
    ):
        allowed = ", ".join(sorted(DEVICE_ACTION_SUPPORT_KEYS))
        raise RuntimeError(f"--execute-device-action action must be one of: {allowed}")


async def _async_run(args: argparse.Namespace, report: SmokeReport) -> int:
    """Run the smoke test."""
    connector = TCPConnector(ssl=False if args.insecure else None)
    async with ClientSession(connector=connector) as session:
        client = WebcardLXClient(session, args.url, args.username, args.password)
        try:
            await client.async_login()
            print(f"[OK] Login to {client.base_url}")

            if args.refresh_token_test:
                await client.async_refresh_token()
                print("[OK] Token refresh")

            devices = await _fetch_endpoint(
                report,
                "/api/devices",
                client.async_get_devices,
                required=True,
                default=[],
            )
            variables = await _fetch_endpoint(
                report,
                "/api/variables",
                client.async_get_variables,
                required=True,
                default=[],
            )

            devices_info = await _fetch_endpoint(
                report,
                "/api/devices_info",
                client.async_get_devices_info,
                required=False,
                default=[],
            )
            control_variables = await _fetch_endpoint(
                report,
                "/api/variables?filter[has_control_key]=true",
                client.async_get_control_variables,
                required=False,
                default=[],
            )
            loads = await _fetch_endpoint(
                report,
                "/api/loads",
                client.async_get_loads,
                required=False,
                default=[],
            )
            load_groups = await _fetch_endpoint(
                report,
                "/api/loads_group",
                client.async_get_load_groups,
                required=False,
                default=[],
            )
            actions_supported = await _fetch_endpoint(
                report,
                "/api/actions/supported",
                client.async_get_supported_actions,
                required=False,
                default={},
            )
            schedules_supported = await _fetch_endpoint(
                report,
                "/api/schedulings/supported",
                client.async_get_supported_schedules,
                required=False,
                default={},
            )
            alarm_summary = await _fetch_endpoint(
                report,
                "/api/alarms/summary",
                client.async_get_alarm_summary,
                required=False,
                default={},
            )
            alarms = await _fetch_endpoint(
                report,
                "/api/alarms",
                client.async_get_alarms,
                required=False,
                default=[],
            )
            events = await _fetch_endpoint(
                report,
                "/api/events",
                client.async_get_events,
                required=False,
                default=[],
            )
            ready = await _fetch_endpoint(
                report,
                "/api/ready",
                client.async_get_ready,
                required=False,
                default={},
            )
            system_details = await _fetch_endpoint(
                report,
                "/api/system_details",
                client.async_get_system_details,
                required=False,
                default={},
            )
            system_uptime = await _fetch_endpoint(
                report,
                "/api/system_uptime",
                client.async_get_system_uptime,
                required=False,
                default={},
            )

            active_device_ids = _filter_supported_devices(
                devices,
                variables,
                allow_unsupported_model=args.allow_unsupported_model,
            )
            if not active_device_ids:
                warning = (
                    "No supported UPS model found. Use --allow-unsupported-model "
                    "to test DEVICE_TYPE_UPS fallback behavior."
                )
                report.warnings.append(warning)
                print(f"[WARN] {warning}")

            filtered_variables = _variables_for_supported_devices(variables, active_device_ids)
            filtered_loads = _loads_for_supported_devices(loads, active_device_ids)
            _print_summary(
                report,
                devices,
                filtered_variables,
                filtered_loads,
                actions_supported,
                alarm_summary,
                alarms,
                active_device_ids=active_device_ids,
                verbose=args.verbose,
            )
            report.summary.update(
                {
                    "devices_info_count": len(devices_info),
                    "control_variables_count": len(control_variables),
                    "load_groups_count": len(load_groups),
                    "schedules_supported_keys": sorted(schedules_supported),
                    "events_count": len(events),
                    "ready": ready,
                    "system_details_keys": sorted(system_details),
                    "system_uptime": system_uptime,
                }
            )

            await _run_mutations(
                client,
                args,
                report,
                variables=variables,
                loads=loads,
                actions_supported=actions_supported,
                alarms=alarms,
            )

            optional_failures = [result.name for result in report.endpoint_results if not result.ok]
            if args.strict and (optional_failures or not active_device_ids):
                if optional_failures:
                    print(
                        "\nStrict mode failed optional endpoints: "
                        f"{', '.join(optional_failures)}"
                    )
                return 1

            return 0
        finally:
            await client.async_logout()
            print("[OK] Logout")


def main() -> int:
    """Run the CLI."""
    parser = _build_parser()
    args = parser.parse_args()
    report = SmokeReport()
    exit_code = 2
    try:
        _validate_args(args)
        exit_code = asyncio.run(_async_run(args, report))
    except (RuntimeError, WebcardLXInvalidAuth, WebcardLXCannotConnect, WebcardLXApiError) as err:
        print(f"[ERROR] {_format_error(err)}", file=sys.stderr)
    except WebcardLXError as err:
        print(f"[ERROR] {err}", file=sys.stderr)

    if args.report_json:
        _write_report(Path(args.report_json), report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
