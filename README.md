# Provident Energy for Home Assistant

An unofficial integration that shows hourly usage from Provident's [MeterConnex usage portal](https://provident.meterconnex.com/) in Home Assistant. It supports electricity, cold water, hot water, heating, and cooling meters.

## Install

1. Copy `custom_components/provident_energy` into the `custom_components` folder in your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and select **Provident Energy Usage**.

## Sign in

Use your **usage portal** credentials, not your [billing portal](https://providentbilling.com/) login. For most customers, the username is the **LOC-ID** on the bill and the password is the **6-digit Customer Number**. See [Provident's FAQ](https://www.pemi.com/faq).

Each supported meter gets a sensor that refreshes hourly. The value is **one hour's usage**, not a running total, so it is not a cumulative Energy dashboard source. The sensor also shows which hour the reading belongs to.

**Early version:** Login and readings have not yet been tested with a live Provident account.
