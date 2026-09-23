# Provident hourly usage for Home Assistant

**This integration uses Provident's MeterConnex USAGE portal at
https://provident.meterconnex.com/. It does not use the separate BILLING portal
at https://providentbilling.com/.** Provident's [FAQ](https://www.pemi.com/faq)
calls them Customer Portal 2 (Usage) and Customer Portal 1 (Billing), respectively.
Most active customers can sign in to the usage portal with **Username = LOC-ID
on the bill** and **Password = 6-digit Customer Number**. Enter these in the
Home Assistant setup form, not the billing portal login details. Availability
of usage access varies by account.

Install by placing `custom_components/provident_energy` under your Home Assistant
configuration directory, restarting Home Assistant, then adding **Provident
Energy Usage** through Settings > Devices & services > Add integration. Setup
checks the usage credentials and discovers meters before creating an entry.

The integration polls every hour for yesterday's and today's hourly readings.
It creates one hourly usage sensor per recognized electricity, cold water, hot
water, heating, or cooling meter. The state is one selected hourly consumption
amount, **not a cumulative meter total**. Electricity uses kWh, heating and
cooling use equivalent kWh (ekWh), and water uses cubic meters. Each sensor
exposes `meter_id`, `meter_name`, `meter_title`, `utility_type`, `delay_hours`
(24 for electricity, 2 for the other four utilities), `hour_timestamp`, and
`hour_index` (zero-based position in the returned graph). These hourly values
have no Home Assistant `state_class` and are not cumulative totals or long-term
energy/water statistics. When the selected hour is missing, malformed,
ambiguous, or on a DST transition with only positional data, the state is
`unknown`; timestamped data can resolve DST ambiguity. A failed poll makes the
sensor unavailable, while a successful refresh with no reading clears old values.

## Limitations

The publicly observed login response wraps a JSON success flag in `d`, and
the unauthenticated rootnodes endpoint responds with HTTP 401. Meter-tree and
quick-graph responses for an authenticated account have not been verified:
no live account authentication or authenticated endpoint testing was performed.
Portal changes or different account response formats may require updating
`api.py`. The 24-hour electricity and 2-hour other-utility selection delays
are fixed assumptions, not provider guarantees. Positional graphs must
contain exactly 48 slots for two ordinary 24-hour days; DST days require
unambiguous timestamped slots. Only the five named utilities are supported.
