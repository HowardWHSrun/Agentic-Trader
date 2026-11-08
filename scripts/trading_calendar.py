#!/usr/bin/env python3
"""NYSE trading-day calendar without third-party dependencies.

Rules follow NYSE Rule 7.2: a Saturday holiday is observed the Friday before,
except New Year's Day (not observed when it falls on Saturday); a Sunday
holiday is observed the next Monday. Unscheduled closures (national mourning,
weather) cannot be predicted and are not included.
"""
import argparse
import datetime as dt
import sys


def _nth_weekday(year, month, weekday, n):
    """n-th (1-based) weekday of a month; n=-1 means the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + dt.timedelta(days=offset + 7 * (n - 1))
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year):
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _observed(day):
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def nyse_holidays(year):
    """Map of full-closure dates to holiday names for one calendar year."""
    days = {}
    new_year = dt.date(year, 1, 1)
    if new_year.weekday() != 5:
        days[_observed(new_year)] = "New Year's Day"
    days[_nth_weekday(year, 1, 0, 3)] = 'Martin Luther King Jr. Day'
    days[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    days[_easter(year) - dt.timedelta(days=2)] = 'Good Friday'
    days[_nth_weekday(year, 5, 0, -1)] = 'Memorial Day'
    if year >= 2022:
        days[_observed(dt.date(year, 6, 19))] = 'Juneteenth'
    days[_observed(dt.date(year, 7, 4))] = 'Independence Day'
    days[_nth_weekday(year, 9, 0, 1)] = 'Labor Day'
    days[_nth_weekday(year, 11, 3, 4)] = 'Thanksgiving Day'
    days[_observed(dt.date(year, 12, 25))] = 'Christmas Day'
    # Next year's New Year's Day observed on Dec 31 never happens under the
    # Saturday exception, so no cross-year entries are needed.
    return days


def holiday_name(day):
    return nyse_holidays(day.year).get(day)


def is_trading_day(day):
    return day.weekday() < 5 and holiday_name(day) is None


def early_close(day):
    """1:00 p.m. ET early-close reason, or None for a regular session."""
    if not is_trading_day(day):
        return None
    july4 = dt.date(day.year, 7, 4)
    if day == july4 - dt.timedelta(days=1) and july4.weekday() in (1, 2, 3, 4):
        return 'Day before Independence Day'
    if day == _nth_weekday(day.year, 11, 3, 4) + dt.timedelta(days=1):
        return 'Day after Thanksgiving'
    if day == dt.date(day.year, 12, 24):
        return 'Christmas Eve'
    return None


def session_bounds(day):
    """(open, close) ET times of the regular session, or None when closed."""
    if not is_trading_day(day):
        return None
    return dt.time(9, 30), dt.time(13, 0) if early_close(day) else dt.time(16, 0)


def in_session(now_et, grace_minutes=5):
    """True while the regular session is open (ET-aware datetime), plus a short grace."""
    bounds = session_bounds(now_et.date())
    if bounds is None:
        return False
    start = dt.datetime.combine(now_et.date(), bounds[0], now_et.tzinfo)
    end = dt.datetime.combine(now_et.date(), bounds[1], now_et.tzinfo) + dt.timedelta(minutes=grace_minutes)
    return start <= now_et <= end


def next_trading_day(day):
    day += dt.timedelta(days=1)
    while not is_trading_day(day):
        day += dt.timedelta(days=1)
    return day


def main(argv=None):
    parser = argparse.ArgumentParser(description='Exit 0 on an NYSE trading day, 1 otherwise.')
    parser.add_argument('--date', help='YYYY-MM-DD (default: today in America/New_York)')
    parser.add_argument('--in-session', action='store_true',
                        help='Exit 0 only while the regular session is open right now')
    args = parser.parse_args(argv)
    if args.in_session:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo('America/New_York'))
        is_open = in_session(now)
        print(f'{now:%Y-%m-%d %H:%M} ET: regular session {"open" if is_open else "closed"}')
        return 0 if is_open else 1
    if args.date:
        day = dt.date.fromisoformat(args.date)
    else:
        from zoneinfo import ZoneInfo
        day = dt.datetime.now(ZoneInfo('America/New_York')).date()
    if is_trading_day(day):
        note = early_close(day)
        print(f'{day} is a trading day' + (f' (early close 13:00 ET: {note})' if note else ''))
        return 0
    print(f'{day} is not a trading day: {holiday_name(day) or "weekend"}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
