"""Offline exchange calendar for Webull's regular-session-only paper policy."""
from functools import lru_cache
from datetime import timedelta
import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=8)
def calendar(year):
    return xcals.get_calendar("XNYS", start=f"{year-6}-01-01", end=f"{year+1}-12-31")


def completed_sessions(start, today):
    return calendar(today.year).sessions_in_range(
        pd.Timestamp(start), pd.Timestamp(today - timedelta(days=1)))


def regular_session(now):
    cal = calendar(now.year)
    day = pd.Timestamp(now.date())
    return cal.is_session(day) and cal.session_close(day).tz_convert(now.tzinfo).hour == 16
