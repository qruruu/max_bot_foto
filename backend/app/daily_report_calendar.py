"""Calendar windows are proposals. Only approved facts complete recurring work."""

from calendar import monthrange
from datetime import date, timedelta


def season_for(day, config):
    start, end = config.summer_start, config.summer_end
    if not start or not end:
        return ""
    md = day.strftime("%m-%d")
    summer = start <= md <= end if start <= end else md >= start or md <= end
    return "summer" if summer else "winter"


def month_day(year, value):
    month, day = map(int, value.split("-"))
    return date(year, month, min(day, monthrange(year, month)[1]))


def work_period(day, work, season, events):
    if work.season != "all" and work.season != season:
        return None
    if (work.requires_event or work.recurrence == "event") and work.id not in events:
        return None
    start = end = day
    mode = work.recurrence
    if mode == "monthly":
        start, end = day.replace(day=1), day.replace(day=monthrange(day.year, day.month)[1])
    elif mode == "four_windows":
        first = min((day.day - 1) // 7 * 7 + 1, 22)
        start, end = day.replace(day=first), day.replace(day=min(first + 6, monthrange(day.year, day.month)[1]) if first < 22 else monthrange(day.year, day.month)[1])
    elif mode == "windows":
        for window in work.windows:
            first, last = month_day(day.year, window.start), month_day(day.year, window.end)
            if first > last:
                if day <= last:
                    first = month_day(day.year - 1, window.start)
                else:
                    last = month_day(day.year + 1, window.end)
            if first <= day <= last:
                return first, last
        return None
    elif mode == "dates":
        if day.strftime("%m-%d") not in work.dates:
            return None
    elif mode == "deadlines":
        start = date(day.year, 1, 1)
        for value in work.dates:
            end = month_day(day.year, value)
            if start <= day <= end:
                return start, end
            start = end + timedelta(days=1)
        return None
    elif mode == "interval":
        start = day - timedelta(days=work.interval_days - 1)
    return start, end
