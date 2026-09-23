"""Client for the MeterConnex usage portal endpoints."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import BASE_URL


class AuthenticationError(Exception):
    """The provider rejected the credentials or expired the session."""


class ConnectionError(Exception):
    """A request or response could not be used."""


@dataclass(frozen=True)
class Meter:
    """A leaf meter in the provider tree."""

    id: str
    name: str
    title: str


def parse_meters(payload: Any) -> list[Meter]:
    """Extract reachable leaf meters from flat or nested meter trees."""
    if not isinstance(payload, list):
        raise ConnectionError("Invalid meter tree")
    found: dict[str, Meter] = {}
    nodes: dict[str, dict] = {}
    children_by_parent: dict[str, list[str]] = {}
    roots: list[str] = []

    def collect(items: list[Any], parent: str | None = None) -> None:
        for node in items:
            if not isinstance(node, dict):
                continue
            raw_id = node.get("id")
            if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
                continue
            meter_id = str(raw_id).strip()
            if not meter_id or meter_id == "#":
                continue
            if meter_id not in nodes:
                nodes[meter_id] = node
                raw_parent = node.get("parent", parent)
                if raw_parent == "#" or (raw_parent is None and parent is None):
                    roots.append(meter_id)
                elif isinstance(raw_parent, (str, int)) and not isinstance(
                    raw_parent, bool
                ):
                    children_by_parent.setdefault(str(raw_parent), []).append(meter_id)
            children = node.get("children")
            if isinstance(children, list):
                collect(children, meter_id)

    collect(payload)
    visited: set[str] = set()

    def visit(meter_id: str, is_root: bool = False) -> None:
        if meter_id in visited:
            return
        visited.add(meter_id)
        node = nodes[meter_id]
        children = children_by_parent.get(meter_id, [])
        if not is_root and not children:
            attrs = node.get("a_attr")
            title = attrs.get("title") if isinstance(attrs, dict) else None
            if isinstance(title, str) and title.strip():
                name = node.get("text")
                found[meter_id] = Meter(
                    meter_id,
                    name if isinstance(name, str) and name.strip() else meter_id,
                    title if isinstance(title, str) else "",
                )
        for child_id in children:
            if child_id in nodes:
                visit(child_id)

    for root in roots:
        visit(root, is_root=True)
    return list(found.values())


class ProvidentClient:
    """Use an isolated cookie session; retry one expired login."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        self.session = session
        self.username = username
        self.password = password
        self._logged_in = False

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with self.session.request(
                method,
                BASE_URL + path,
                timeout=aiohttp.ClientTimeout(total=15),
                **kwargs,
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError("Provider rejected authentication")
                if response.status >= 400:
                    raise ConnectionError("Provider request failed")
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as err:
            raise ConnectionError("Provider connection or response failed") from err

    async def login(self) -> None:
        result = await self._request(
            "POST",
            "/login/LoginService.aspx/ProcessLogin",
            json={
                "username": self.username,
                "password": self.password,
                "rememberMe": False,
            },
        )
        if isinstance(result, dict) and "d" in result:
            result = result["d"]
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                raise ConnectionError("Unrecognized login response") from None
        statuses = (
            [
                result[key]
                for key in ("success", "Success", "isSuccess")
                if key in result
            ]
            if isinstance(result, dict)
            else [result]
        )
        if any(status is False for status in statuses):
            raise AuthenticationError("Provider rejected authentication")
        if not statuses or not all(status is True for status in statuses):
            raise ConnectionError("Unrecognized login response")
        self._logged_in = True

    async def _authenticated(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._logged_in:
            await self.login()
        try:
            return await self._request(method, path, **kwargs)
        except AuthenticationError:
            self._logged_in = False
            await self.login()
            try:
                return await self._request(method, path, **kwargs)
            except AuthenticationError:
                self._logged_in = False
                raise

    async def meters(self) -> list[Meter]:
        payload = await self._authenticated(
            "GET", "/api/internal/metertree/rootnodes", params={"depth": 2}
        )
        return parse_meters(payload)

    async def graph(self, meter_id: str, now: datetime) -> list[Any]:
        yesterday = now.date() - timedelta(days=1)
        tomorrow = now.date() + timedelta(days=1)
        payload = await self._authenticated(
            "GET",
            "/api/internal/graphs/quickgraphs",
            params={
                "aggregateGroups": "true",
                "meterlist": meter_id,
                "startDate": yesterday.isoformat(),
                "endDate": tomorrow.isoformat(),
            },
        )
        if not isinstance(payload, list):
            raise ConnectionError("Invalid graph response")
        if not payload:
            return payload
        if any(isinstance(item, dict) and "data" in item for item in payload):
            if len(payload) == 1 and isinstance(payload[0], dict):
                series = payload[0]
                if (
                    "meterId" not in series
                    and "meter_id" not in series
                    and all(
                        isinstance(series.get(key), str) and series[key].strip()
                        for key in ("utility", "name", "site")
                    )
                    and _valid_graph_slots(series.get("data"))
                ):
                    return series["data"]
            if not all(
                isinstance(item, dict)
                and ("meterId" in item or "meter_id" in item)
                and item.get("meterId", item.get("meter_id"))
                == item.get("meter_id", item.get("meterId"))
                and _valid_graph_slots(item.get("data"))
                for item in payload
            ):
                raise ConnectionError("Ambiguous graph response")
            matching = [
                item
                for item in payload
                if str(item.get("meterId", item.get("meter_id"))) == meter_id
            ]
            if len(matching) != 1:
                raise ConnectionError("Ambiguous graph response")
            return matching[0]["data"]
        if _valid_graph_slots(payload):
            return payload
        raise ConnectionError("Invalid graph response")


def _valid_graph_slots(slots: Any) -> bool:
    """Recognize positional amounts or timestamped points, including missing slots."""
    return isinstance(slots, list) and (
        all(
            item is None
            or isinstance(item, (int, float))
            and not isinstance(item, bool)
            for item in slots
        )
        or all(isinstance(item, dict) and "x" in item and "y" in item for item in slots)
    )
