"""Pure, OCR-independent parsers. Ambiguous or invalid data stays unresolved."""

import re
from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True)
class DateTimeResult:
    photo_date: date | None = None
    photo_time: time | None = None
    confidence: float | None = None
    raw: str | None = None


class DateTimeParser:
    MONTHS = {
        name: number
        for number, names in enumerate(
            (
                "янв январь января", "фев февр февраль февраля", "мар март марта",
                "апр апрель апреля", "май мая", "июн июнь июня", "июл июль июля",
                "авг август августа", "сен сент сентябрь сентября", "окт октябрь октября",
                "ноя нояб ноябрь ноября", "дек декабрь декабря",
            ),
            start=1,
        )
        for name in names.split()
    }
    DATE = re.compile(
        r"(?<!\d)(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})([./-])(\d{1,2})\5(\d{4}|\d{2}))(?!\d)"
    )
    # rus+eng OCR can render Cyrillic camera-stamp months with Latin lookalikes
    # (e.g. "anp." for "апр."). Normalize only the month token, never date digits.
    MONTH_LOOKALIKES = str.maketrans({
        "a": "а", "c": "с", "e": "е", "k": "к", "m": "м", "n": "п",
        "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
    })
    TEXT_DATE = re.compile(
        r"(?<!\w)(\d{1,2})\s+([a-zа-яё]{3,9})\.?\s+(\d{4})(?!\w)",
        re.IGNORECASE,
    )
    TIME = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])")

    def parse(self, text: str) -> DateTimeResult:
        dates, times, raw = set(), set(), []
        for m in self.DATE.finditer(text):
            try:
                if m[1]:
                    value = date(int(m[1]), int(m[2]), int(m[3]))
                else:
                    year = int(m[7]) + (2000 if len(m[7]) == 2 else 0)
                    value = date(year, int(m[6]), int(m[4]))
                dates.add(value)
                raw.append(m[0])
            except ValueError:
                continue
        for m in self.TEXT_DATE.finditer(text):
            month = self.MONTHS.get(m[2].lower().translate(self.MONTH_LOOKALIKES))
            if month is None:
                continue
            try:
                dates.add(date(int(m[3]), month, int(m[1])))
                raw.append(m[0])
            except ValueError:
                continue
        for m in self.TIME.finditer(text):
            try:
                times.add(time(int(m[1]), int(m[2]), int(m[3] or 0)))
                raw.append(m[0])
            except ValueError:
                continue
        return DateTimeResult(
            next(iter(dates)) if len(dates) == 1 else None,
            next(iter(times)) if len(times) == 1 else None,
            0.95 if len(dates) == 1 else None,
            " | ".join(raw) or None,
        )


@dataclass(frozen=True)
class CoordinateResult:
    latitude: float | None = None
    longitude: float | None = None
    coordinate_format: str | None = None
    confidence: float | None = None
    raw: str | None = None


# Require decimals for a bare pair, so dates, times and street numbers aren't coordinates.
DECIMAL = r"[+-]?\d{1,3}\.\d+"
ANGLE = r"[+-]?\d{1,3}(?:\.\d+)?(?:\s*°\s*\d{1,2}(?:\.\d+)?\s*'(?:\s*\d{1,2}(?:\.\d+)?\s*\")?)?"


class CoordinateParser:
    def _angle(self, value: str, direction: str):
        values = [float(x) for x in re.findall(r"[+-]?\d+(?:\.\d+)?", value)]
        degrees = values[0]
        if len(values) > 1 and not 0 <= values[1] < 60:
            raise ValueError("minutes")
        if len(values) > 2 and not 0 <= values[2] < 60:
            raise ValueError("seconds")
        if degrees < 0 and direction in "NE":
            raise ValueError("conflicting sign")
        sign = -1 if direction in "SW" or degrees < 0 else 1
        result = (
            abs(degrees)
            + (values[1] / 60 if len(values) > 1 else 0)
            + (values[2] / 3600 if len(values) > 2 else 0)
        )
        return sign * result, ["DD", "DM", "DMS"][len(values) - 1]

    def parse(self, text: str) -> CoordinateResult:
        # Only punctuation normalization; never silently substitute digits or infer a city.
        normalized = text.upper().translate(
            str.maketrans({",": ".", "′": "'", "’": "'", "″": '"', "º": "°", "−": "-"})
        )
        candidates = []
        for prefix in (True, False):
            lat = rf"(?P<ns>[NS])\s*(?P<lat>{ANGLE})" if prefix else rf"(?P<lat>{ANGLE})\s*(?P<ns>[NS])"
            lon = rf"(?P<ew>[EW])\s*(?P<lon>{ANGLE})" if prefix else rf"(?P<lon>{ANGLE})\s*(?P<ew>[EW])"
            for pattern in (lat + r"[\s;|/]+" + lon, lon + r"[\s;|/]+" + lat):
                for m in re.finditer(r"(?<![\w.])" + pattern + r"(?![\w.])", normalized):
                    try:
                        latitude, fmt1 = self._angle(m["lat"], m["ns"])
                        longitude, fmt2 = self._angle(m["lon"], m["ew"])
                        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                            candidates.append(
                                CoordinateResult(
                                    latitude,
                                    longitude,
                                    fmt1 if fmt1 == fmt2 else "MIXED",
                                    0.98,
                                    text[m.start() : m.end()],
                                )
                            )
                    except ValueError:
                        continue
        if not candidates:
            # Never salvage a partial decimal pair from a malformed labelled/DMS coordinate line.
            for line in normalized.splitlines():
                if re.search(r"[NSEW°'\"]", line):
                    continue
                for m in re.finditer(
                    rf"(?<![\d.])(?P<lat>{DECIMAL})\s*[;| ]\s*(?P<lon>{DECIMAL})(?![\d.])", line
                ):
                    latitude, longitude = float(m["lat"]), float(m["lon"])
                    if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                        candidates.append(CoordinateResult(latitude, longitude, "DD", 0.8, m[0]))
        unique = {(round(c.latitude, 7), round(c.longitude, 7)) for c in candidates}
        return candidates[0] if len(unique) == 1 else CoordinateResult(raw=text if len(unique) > 1 else None)


def parse_address(text: str) -> tuple[str | None, str | None, str | None]:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for i, line in enumerate(lines):
        if re.search(r"\b(улица|ул\.|проспект|пр-т|проезд|переулок|шоссе|набережная|бульвар)\b", line, re.I):
            city = None
            if i + 1 < len(lines) and re.fullmatch(
                r"(?:г\.?\s*)?[А-ЯЁ][а-яё-]+(?: [А-ЯЁ][а-яё-]+)*", lines[i + 1]
            ):
                city = re.sub(r"^г\.?\s*", "", lines[i + 1])
            return line, line, city
    return None, None, None
