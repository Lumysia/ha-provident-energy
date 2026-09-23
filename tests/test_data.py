"""Synthetic protocol and hourly selection tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.provident_energy.api import parse_meters
from custom_components.provident_energy.data import select_hour


def test_parse_nested_meters_and_deduplicate():
    tree = [
        {
            "id": "building",
            "text": "Building",
            "children": [
                {"id": "e1", "text": "Main", "a_attr": {"title": "Electricity"}},
                {"id": "w1", "text": "Water", "a_attr": {"title": "Cold Water"}},
            ],
        },
        {
            "id": "other",
            "children": [
                {"id": "e1", "text": "Duplicate"},
                {"id": "mystery", "text": "Other", "a_attr": {"title": "Other"}},
                {"id": "group", "text": "Untitled group"},
            ],
        },
    ]
    meters = parse_meters(tree)
    assert [(m.id, m.name, m.title) for m in meters] == [
        ("e1", "Main", "Electricity"),
        ("w1", "Water", "Cold Water"),
        ("mystery", "Other", "Other"),
    ]


def test_parse_flat_parent_linked_tree_with_groups_orphans_and_duplicates():
    tree = [
        {"id": "root", "parent": "#", "text": "Building"},
        {
            "id": "e1",
            "parent": "root",
            "text": "Suite 1",
            "a_attr": {"title": "Electricity"},
        },
        {"id": "wing", "parent": "root", "text": "Wing"},
        {
            "id": "w1",
            "parent": "wing",
            "text": "Suite 2",
            "a_attr": {"title": "Cold Water"},
        },
        {
            "id": "e1",
            "parent": "root",
            "text": "Duplicate",
            "a_attr": {"title": "Electricity"},
        },
        {
            "id": "orphan",
            "parent": "missing",
            "text": "Orphan",
            "a_attr": {"title": "Heating"},
        },
        {"id": "empty", "parent": "root", "text": "Group without meter title"},
    ]
    assert [(m.id, m.name, m.title) for m in parse_meters(tree)] == [
        ("e1", "Suite 1", "Electricity"),
        ("w1", "Suite 2", "Cold Water"),
    ]


def test_parse_mixed_nested_and_flat_tree_without_duplicate_meters():
    tree = [
        {
            "id": "building",
            "parent": "#",
            "children": [
                {"id": "e1", "text": "Nested", "a_attr": {"title": "Electricity"}}
            ],
        },
        {
            "id": "w1",
            "parent": "building",
            "text": "Flat",
            "a_attr": {"title": "Hot Water"},
        },
        {
            "id": "e1",
            "parent": "building",
            "text": "Repeated",
            "a_attr": {"title": "Electricity"},
        },
        {"id": "cycle1", "parent": "cycle2", "a_attr": {"title": "Heating"}},
        {"id": "cycle2", "parent": "cycle1", "a_attr": {"title": "Heating"}},
    ]
    assert [(m.id, m.name) for m in parse_meters(tree)] == [
        ("e1", "Nested"),
        ("w1", "Flat"),
    ]


def test_select_lag_and_midnight_from_positional_slots():
    now = datetime(2026, 9, 23, 1, 40, tzinfo=ZoneInfo("America/Toronto"))
    slots = list(range(48))
    electric = select_hour(slots, now, 24)
    water = select_hour(slots, now, 2)
    assert (electric.value, electric.index, electric.timestamp.isoformat()) == (
        1,
        1,
        "2026-09-22T01:00:00-04:00",
    )
    assert (water.value, water.index, water.timestamp.isoformat()) == (
        23,
        23,
        "2026-09-22T23:00:00-04:00",
    )


def test_missing_malformed_future_and_dst_positional_slots_unavailable():
    now = datetime(2026, 9, 23, 14, tzinfo=ZoneInfo("America/Toronto"))
    slots = list(range(48))
    slots[36] = None
    assert select_hour(slots, now, 2) is None
    slots[36] = "not a number"
    assert select_hour(slots, now, 2) is None
    slots[36] = -1
    assert select_hour(slots, now, 2) is None
    slots[36] = 10**1000
    assert select_hour(slots, now, 2) is None
    assert select_hour(list(range(48)), now, True) is None
    assert select_hour(list(range(48)), now, -1) is None
    dst = datetime(2026, 11, 1, 5, tzinfo=ZoneInfo("America/Toronto"))
    assert select_hour(list(range(48)), dst, 2) is None
    spring = datetime(2026, 3, 8, 5, tzinfo=ZoneInfo("America/Toronto"))
    assert select_hour(list(range(48)), spring, 2) is None


def test_timestamped_slots_disambiguate_dst():
    now = datetime(2026, 11, 1, 3, tzinfo=ZoneInfo("America/Toronto"))
    # At 03:00 EST, two elapsed hours ago was 01:00 EST.
    slots = [
        {"x": "2026-11-01T01:00:00-04:00", "y": 3.5},
        {"x": "2026-11-01T01:00:00-05:00", "y": 7},
    ]
    selected = select_hour(slots, now, 2)
    assert (selected.value, selected.index, selected.timestamp.isoformat()) == (
        7,
        1,
        "2026-11-01T01:00:00-05:00",
    )
