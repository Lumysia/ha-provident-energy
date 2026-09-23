"""Offline tests for the usage integration and its client."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy, UnitOfVolume
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.provident_energy import (
    ProvidentCoordinator,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.provident_energy.api import (
    AuthenticationError,
    ConnectionError,
    Meter,
    ProvidentClient,
)
from custom_components.provident_energy.config_flow import ProvidentConfigFlow
from custom_components.provident_energy.const import DOMAIN
from custom_components.provident_energy.data import select_hour, utility_type
from custom_components.provident_energy.sensor import ProvidentHourSensor


def run(coro):
    return asyncio.run(coro)


def test_selection_rejects_ambiguous_and_bad_slots():
    now = datetime(2026, 9, 23, 14, tzinfo=ZoneInfo("America/Toronto"))
    slots = list(range(48))
    slots[36] = {"x": "2026-09-23T12:00:00-04:00", "y": 1}
    assert select_hour(slots, now, 2) is None
    assert select_hour([], now, 2) is None
    assert select_hour([1] * 47, now, 2) is None
    assert select_hour([{"x": "2026-09-23T12:00:00-04:00", "y": 1}] * 2, now, 2) is None
    assert select_hour([{"x": "2026-09-23T12:00:00", "y": 1}], now, 2) is None


def test_five_utility_types_only():
    for label, kind in (
        ("Electricity", "electricity"),
        ("Cold Water", "cold_water"),
        ("Hot Water", "hot_water"),
        ("Cooling", "cooling"),
        ("Heating", "heating"),
        ("Natural Gas", None),
    ):
        assert utility_type(label) == kind


def test_client_login_discovery_graph_and_expired_session():
    client = ProvidentClient(MagicMock(), "fake-loc", "fake-number")
    tree = [
        {
            "id": "group",
            "children": [
                {"id": "e1", "text": "Suite", "a_attr": {"title": "Electricity"}}
            ],
        }
    ]
    client._request = AsyncMock(
        side_effect=[
            {"d": '{"success": true}'},
            tree,
            AuthenticationError(),
            {"d": True},
            [{"meterId": "e1", "data": list(range(48))}],
        ]
    )

    async def scenario():
        assert len(await client.meters()) == 1
        assert await client.graph(
            "e1", datetime(2026, 9, 23, tzinfo=ZoneInfo("America/Toronto"))
        ) == list(range(48))

    run(scenario())
    assert client._request.await_count == 5
    graph_call = client._request.await_args_list[-1]
    assert graph_call.kwargs["params"] == {
        "aggregateGroups": "true",
        "meterlist": "e1",
        "startDate": "2026-09-22",
        "endDate": "2026-09-24",
    }


def test_client_rejects_bad_auth_and_graph():
    client = ProvidentClient(MagicMock(), "fake", "fake")
    client._request = AsyncMock(return_value={"d": {"success": False}})
    with pytest.raises(AuthenticationError):
        run(client.meters())
    client._logged_in = True
    client._request = AsyncMock(
        return_value=[{"meterId": "other", "data": list(range(48))}]
    )
    with pytest.raises(ConnectionError):
        run(client.graph("mine", datetime.now(ZoneInfo("America/Toronto"))))


@pytest.mark.parametrize(
    "result",
    [
        {"d": '{"success": false}'},
        {"d": '{"success": true, "Success": false}'},
        {"d": '{"success": true, "Success": "false"}'},
        {"d": '{"success": 1}'},
        {"d": "not json"},
    ],
)
def test_login_rejects_false_or_ambiguous_results(result):
    client = ProvidentClient(MagicMock(), "synthetic", "synthetic")
    client._request = AsyncMock(return_value=result)
    error = (
        AuthenticationError
        if result
        in (
            {"d": '{"success": false}'},
            {"d": '{"success": true, "Success": false}'},
        )
        else ConnectionError
    )
    with pytest.raises(error):
        run(client.login())
    assert not client._logged_in


def test_graph_accepts_single_legacy_series_without_meter_id():
    client = ProvidentClient(MagicMock(), "synthetic", "synthetic")
    client._logged_in = True
    slots = list(range(48))
    client._request = AsyncMock(
        return_value=[
            {
                "utility": "Electricity (kWh)",
                "name": "Suite",
                "site": "Building",
                "data": slots,
            }
        ]
    )
    now = datetime(2026, 9, 23, tzinfo=ZoneInfo("America/Toronto"))

    assert run(client.graph("e1", now)) == slots
    assert client._request.await_args.kwargs["params"]["meterlist"] == "e1"


@pytest.mark.parametrize(
    "payload",
    [
        [{"data": [1] * 48}],
        [
            {
                "utility": "Electricity (kWh)",
                "name": "Suite",
                "site": "Building",
                "data": [1] * 48,
            }
        ]
        * 2,
        [
            {
                "utility": "Electricity (kWh)",
                "name": "Suite",
                "site": "Building",
                "data": [1] * 48,
            },
            {"meterId": "e1", "data": [2] * 48},
        ],
        [{"utility": "Electricity (kWh)", "name": "Suite", "data": [1] * 48}],
        [
            {
                "utility": "Electricity (kWh)",
                "name": " ",
                "site": "Building",
                "data": [1] * 48,
            }
        ],
        [
            {
                "utility": "Electricity (kWh)",
                "name": "Suite",
                "site": "Building",
                "data": [True] * 48,
            }
        ],
        [
            {
                "utility": "Electricity (kWh)",
                "name": "Suite",
                "site": "Building",
                "meterId": "other",
                "data": [1] * 48,
            }
        ],
        [
            {
                "utility": "Electricity (kWh)",
                "name": "Suite",
                "site": "Building",
                "meterId": "e1",
                "meter_id": "other",
                "data": [1] * 48,
            }
        ],
        [{"meterId": "e1", "data": [1] * 48}, {"x": "2026-09-23T12:00:00Z", "y": 2}],
        [{"meterId": "e1", "data": [1] * 48}, {"meterId": "e1", "data": [2] * 48}],
        [{"meterId": "e1", "meter_id": "other", "data": [1] * 48}],
        [{"meterId": "e1", "data": [{"success": False}]}],
        [{"unexpected": "payload"}],
        [{"x": "2026-09-23T12:00:00Z", "y": 2}, 10],
    ],
)
def test_graph_rejects_ambiguous_payload(payload):
    client = ProvidentClient(MagicMock(), "synthetic", "synthetic")
    client._logged_in = True
    client._request = AsyncMock(return_value=payload)
    with pytest.raises(ConnectionError):
        run(
            client.graph(
                "e1", datetime(2026, 9, 23, tzinfo=ZoneInfo("America/Toronto"))
            )
        )


def test_graph_accepts_timestamped_points_and_empty_result():
    client = ProvidentClient(MagicMock(), "synthetic", "synthetic")
    client._logged_in = True
    points = [{"x": "2026-09-23T12:00:00Z", "y": 2}]
    client._request = AsyncMock(side_effect=[points, []])
    now = datetime(2026, 9, 23, tzinfo=ZoneInfo("America/Toronto"))
    assert run(client.graph("e1", now)) == points
    assert run(client.graph("e1", now)) == []


def test_second_unauthorized_response_resets_login_state():
    client = ProvidentClient(MagicMock(), "synthetic", "synthetic")
    client._logged_in = True
    client._request = AsyncMock(
        side_effect=[
            AuthenticationError(),
            {"d": '{"success": true}'},
            AuthenticationError(),
        ]
    )
    with pytest.raises(AuthenticationError):
        run(client.meters())
    assert not client._logged_in


def test_request_is_bounded_and_targets_usage_only():
    session = MagicMock()
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"d": True})
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    client = ProvidentClient(session, "synthetic-loc", "synthetic-number")
    run(client.login())
    args, kwargs = session.request.call_args
    assert args == (
        "POST",
        "https://provident.meterconnex.com/login/LoginService.aspx/ProcessLogin",
    )
    assert kwargs["timeout"] == aiohttp.ClientTimeout(total=15)
    assert kwargs["json"]["password"] == "synthetic-number"
    assert "synthetic-number" not in args[1]

    response.status = 401
    with pytest.raises(AuthenticationError):
        run(client._request("GET", "/api/internal/metertree/rootnodes"))

    session.request.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(ConnectionError):
        run(client._request("GET", "/api/internal/metertree/rootnodes"))


def test_coordinator_selects_each_meter_and_clears_missing():
    hass = MagicMock()
    entry = MagicMock()
    client = MagicMock()
    client.graph = AsyncMock(
        side_effect=[list(range(48)), list(range(48)), [None] * 48, []]
    )
    meters = [
        Meter("a", "Electricity", "Electricity"),
        Meter("b", "Cold Water", "Cold Water"),
        Meter("c", "Gas", "Gas"),
    ]
    now = datetime(2026, 9, 23, 14, tzinfo=ZoneInfo("America/Toronto"))

    async def scenario():
        coordinator = ProvidentCoordinator(hass, entry, client, meters)
        assert coordinator.update_interval.total_seconds() == 3600
        with patch("custom_components.provident_energy.dt_util.now", return_value=now):
            first = await coordinator._async_update_data()
            second = await coordinator._async_update_data()
        assert set(first) == {"a", "b"}
        assert (
            first["a"].value,
            first["a"].index,
            first["a"].timestamp.isoformat(),
        ) == (14, 14, "2026-09-22T14:00:00-04:00")
        assert (
            first["b"].value,
            first["b"].index,
            first["b"].timestamp.isoformat(),
        ) == (36, 36, "2026-09-23T12:00:00-04:00")
        assert second["a"] is None
        assert second["b"] is None

        coordinator.data = first
        sensor = ProvidentHourSensor(coordinator, entry, meters[0])
        assert sensor.native_value == 14
        assert sensor.extra_state_attributes == {
            "meter_id": "a",
            "meter_name": "Electricity",
            "meter_title": "Electricity",
            "utility_type": "electricity",
            "delay_hours": 24,
            "hour_timestamp": "2026-09-22T14:00:00-04:00",
            "hour_index": 14,
        }
        assert sensor.state_class is None
        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
        coordinator.last_update_success = True
        assert sensor.available
        coordinator.data = second
        assert sensor.native_value is None
        assert sensor.available
        assert sensor.extra_state_attributes["hour_index"] is None
        coordinator.last_update_success = False
        assert not sensor.available

        water = ProvidentHourSensor(coordinator, entry, meters[1])
        assert water.state_class is None
        assert water.device_class == SensorDeviceClass.WATER
        assert water.native_unit_of_measurement == UnitOfVolume.CUBIC_METERS
        assert water.extra_state_attributes["delay_hours"] == 2

    run(scenario())
    assert client.graph.await_count == 4


@pytest.mark.parametrize(
    "kind,delay",
    [
        ("electricity", 24),
        ("cold_water", 2),
        ("hot_water", 2),
        ("heating", 2),
        ("cooling", 2),
    ],
)
def test_each_utility_uses_its_hour_and_reports_meter_context(kind, delay):
    now = datetime(2026, 9, 23, 14, tzinfo=ZoneInfo("America/Toronto"))
    meter = Meter("meter", "Suite 7", kind.replace("_", " "))
    hass = MagicMock()
    entry = MagicMock()
    client = MagicMock()
    client.graph = AsyncMock(return_value=list(range(48)))
    coordinator = ProvidentCoordinator(hass, entry, client, [meter])

    async def scenario():
        with patch("custom_components.provident_energy.dt_util.now", return_value=now):
            coordinator.data = await coordinator._async_update_data()

    run(scenario())
    sensor = ProvidentHourSensor(coordinator, entry, meter)
    assert sensor.native_value == (14 if delay == 24 else 36)
    assert sensor.extra_state_attributes["delay_hours"] == delay
    assert sensor.extra_state_attributes["hour_timestamp"] == (
        "2026-09-22T14:00:00-04:00" if delay == 24 else "2026-09-23T12:00:00-04:00"
    )
    assert sensor.extra_state_attributes["meter_title"] == meter.title
    assert sensor.extra_state_attributes["meter_name"] == meter.name
    assert sensor.state_class is None


def test_flow_checks_discovery_and_releases_session():
    flow = ProvidentConfigFlow()
    flow.hass = MagicMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    flow.async_show_form = MagicMock(side_effect=lambda **kw: kw)
    session = MagicMock()
    client = MagicMock()
    client.meters = AsyncMock(return_value=[Meter("a", "Electricity", "Electricity")])
    data = {CONF_USERNAME: "synthetic-loc", CONF_PASSWORD: "synthetic-number"}
    with (
        patch(
            "custom_components.provident_energy.config_flow.async_create_clientsession",
            return_value=session,
        ) as create_session,
        patch(
            "custom_components.provident_energy.config_flow.ProvidentClient",
            return_value=client,
        ),
    ):
        assert run(flow.async_step_user(data))["type"] == "create_entry"
        client.meters = AsyncMock(return_value=[])
        assert run(flow.async_step_user(data))["errors"] == {"base": "no_meters"}
        client.meters = AsyncMock(return_value=[Meter("g", "Gas", "Gas")])
        assert run(flow.async_step_user(data))["errors"] == {
            "base": "no_supported_meters"
        }
        client.meters = AsyncMock(side_effect=AuthenticationError())
        assert run(flow.async_step_user(data))["errors"] == {"base": "invalid_auth"}
        client.meters = AsyncMock(side_effect=ConnectionError())
        assert run(flow.async_step_user(data))["errors"] == {"base": "cannot_connect"}
    assert session.detach.call_count == 5
    assert all(
        call.kwargs == {"auto_cleanup": False} for call in create_session.call_args_list
    )
    flow.async_set_unique_id.assert_awaited_once_with("synthetic-loc")


def test_setup_unload_and_discovery_failure():
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.data = {CONF_USERNAME: "fake", CONF_PASSWORD: "fake"}
    session = MagicMock()
    client = MagicMock()
    client.meters = AsyncMock(return_value=[Meter("a", "Electricity", "Electricity")])

    async def fake_refresh(coordinator):
        coordinator.data = {"a": None}

    with (
        patch(
            "custom_components.provident_energy.async_create_clientsession",
            return_value=session,
        ) as create_session,
        patch(
            "custom_components.provident_energy.ProvidentClient", return_value=client
        ),
        patch.object(
            ProvidentCoordinator, "async_config_entry_first_refresh", fake_refresh
        ),
    ):
        assert run(async_setup_entry(hass, entry)) is True
        create_session.assert_called_with(hass)
        session.detach.assert_not_called()
        assert "entry" in hass.data[DOMAIN]
        assert run(async_unload_entry(hass, entry)) is True
        session.detach.assert_not_called()
        assert not hass.data[DOMAIN]
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        client.meters = AsyncMock(side_effect=ConnectionError())
        with pytest.raises(ConfigEntryNotReady):
            run(async_setup_entry(hass, entry))
        client.meters = AsyncMock(side_effect=AuthenticationError())
        with pytest.raises(ConfigEntryAuthFailed):
            run(async_setup_entry(hass, entry))
        client.meters = AsyncMock(return_value=[Meter("g", "Gas", "Gas")])
        with pytest.raises(ConfigEntryNotReady):
            run(async_setup_entry(hass, entry))
        client.meters = AsyncMock(
            return_value=[Meter("a", "Electricity", "Electricity")]
        )
        with (
            patch.object(
                ProvidentCoordinator,
                "async_config_entry_first_refresh",
                side_effect=asyncio.CancelledError(),
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            run(async_setup_entry(hass, entry))
    assert session.detach.call_count == 4
