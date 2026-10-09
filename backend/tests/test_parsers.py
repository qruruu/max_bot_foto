from datetime import date, time

import pytest

from app.parsers import CoordinateParser, DateTimeParser, parse_address


@pytest.mark.parametrize("value", ["01.10.2026", "01-10-2026", "01/10/2026", "01.10.26", "2026-10-01"])
def test_date_formats(value):
    result = DateTimeParser().parse(value + " 11:43")
    assert result.photo_date == date(2026, 10, 1)
    assert result.photo_time == time(11, 43)
    assert result.raw


@pytest.mark.parametrize(
    "month,variants",
    [
        (1, "янв. январь января"), (2, "фев. февр. февраль февраля"),
        (3, "мар. март марта"), (4, "апр. апрель апреля"), (5, "май мая"),
        (6, "июн. июнь июня"), (7, "июл. июль июля"), (8, "авг. август августа"),
        (9, "сен. сент. сентябрь сентября"), (10, "окт. октябрь октября"),
        (11, "ноя. нояб. ноябрь ноября"), (12, "дек. декабрь декабря"),
    ],
)
def test_russian_month_names(month, variants):
    for name in variants.split():
        result = DateTimeParser().parse(f"20 {name} 2026 г. 11:43")
        assert result.photo_date == date(2026, month, 20), name
        assert result.photo_time == time(11, 43)
        assert result.raw == f"20 {name} 2026 | 11:43"


@pytest.mark.parametrize("value", ["20 апр 2026", "20 АПР. 2026 г.", "20\u00a0апр.\n2026 г."])
def test_text_date_spacing_and_case(value):
    assert DateTimeParser().parse(value).photo_date == date(2026, 4, 20)


@pytest.mark.parametrize("month", ["anp", "aпр", "апp", "аnp", "aпp", "ANP", "апpeля"])
def test_ocr_latin_lookalikes_in_russian_month(month):
    text = f"20 {month}. 2026 г. 09:24:37"
    result = DateTimeParser().parse(text)
    assert result.photo_date == date(2026, 4, 20)
    assert result.photo_time == time(9, 24, 37)
    assert f"20 {month}. 2026" in result.raw


@pytest.mark.parametrize("text", ["20 anp. 2O26", "2O anp. 2026", "20 abc. 2026", "31 anp. 2026"])
def test_month_normalization_never_guesses_digits_or_unknown_words(text):
    assert DateTimeParser().parse(text).photo_date is None


def test_normalized_month_still_detects_conflicting_dates():
    assert DateTimeParser().parse("20 anp. 2026\n21 апр. 2026").photo_date is None
    assert DateTimeParser().parse("20 anp. 2026\n20 апр. 2026").photo_date == date(2026, 4, 20)


@pytest.mark.parametrize(
    "value",
    [
        "31 апр. 2026", "29 февраля 2026", "0 января 2026", "120 апр. 2026",
        "20 апрельский 2026", "20 апр. 20260", "20 апр. 2026abc", "20 апр. 26",
        "20 апр. 2026 г. 21.04.2026", "20 апреля 2026 21 апреля 2026",
    ],
)
def test_invalid_or_conflicting_text_dates(value):
    result = DateTimeParser().parse(value)
    assert result.photo_date is None
    assert result.confidence is None


def test_matching_numeric_and_text_dates_and_leap_year():
    result = DateTimeParser().parse("29 февраля 2024 г. 29.02.2024")
    assert result.photo_date == date(2024, 2, 29)


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
