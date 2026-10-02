from datetime import date, time

import pytest

from app.parsers import CoordinateParser, DateTimeParser, parse_address


@pytest.mark.parametrize("value", ["01.10.2026", "01-10-2026", "01/10/2026", "01.10.26", "2026-10-01"])
def test_date_formats(value):
    result = DateTimeParser().parse(value + " 11:43")
    assert result.photo_date == date(2026, 10, 1)
    assert result.photo_time == time(11, 43)
    assert result.raw


@pytest.mark.parametrize("value", ["31.02.2026", "2026-13-01", "no date", "01.10.2026 02.10.2026"])
def test_bad_or_ambiguous_dates(value):
    assert DateTimeParser().parse(value).photo_date is None


def test_seconds_and_invalid_time():
    assert DateTimeParser().parse("30.09.2026 11:43:25").photo_time == time(11, 43, 25)
    assert DateTimeParser().parse("25:78").photo_time is None


@pytest.mark.parametrize(
    "value",
    [
        "61,1060N 72,5780E",
        "61.1060N 72.5780E",
        "N61,1060 E72,5780",
        "N 61.1060 E 72.5780",
        "61,1060 N 72,5780 E",
        "61.1060 72.5780",
        "61°06'21.6\"N 72°34'40.8\"E",
        "61°06.360'N 72°34.680'E",
        "61°06′21.6″N 72°34′40.8″E",
        "E72.5780 N61.1060",
        "N 61.1060\nE 72.5780",
        "30.09.2026 11:43\n61.1060 72.5780\nНефтеюганск",
    ],
)
def test_coordinate_formats(value):
    result = CoordinateParser().parse(value)
    assert result.latitude == pytest.approx(61.1060)
    assert result.longitude == pytest.approx(72.5780)
    assert result.confidence >= 0.8


@pytest.mark.parametrize(
    "value,lat,lon",
    [
        ("61.106S 72.578W", -61.106, -72.578),
        ("S61.106 E72.578", -61.106, 72.578),
        ("-61.106 -72.578", -61.106, -72.578),
        ("0.0N 0.0E", 0, 0),
    ],
)
def test_hemispheres(value, lat, lon):
    r = CoordinateParser().parse(value)
    assert r.latitude == lat
    assert r.longitude == lon


@pytest.mark.parametrize(
    "value",
    [
        "91.0N 72.0E",
        "61.0N 181.0E",
        "61°60'0\"N 72°34'0\"E",
        "61°06'61\"N 72°34'0\"E",
        "01.10.2026 11:43",
        "26 Парковая улица",
        "-61.106N 72.578E",
        "61.1060N 72.5780E\n62.1060N 72.5780E",
        "91.0 181.0",
        "NaN Infinity",
    ],
)
def test_invalid_coordinates_not_used(value):
    r = CoordinateParser().parse(value)
    assert r.latitude is None and r.longitude is None


def test_address_is_separate():
    assert parse_address("26 Парковая улица\nНефтеюганск") == (
        "26 Парковая улица",
        "26 Парковая улица",
        "Нефтеюганск",
    )
    assert CoordinateParser().parse("12 мкр, Нефтеюганск").latitude is None
