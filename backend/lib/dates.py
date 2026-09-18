"""Server-side date/time helpers. The pod clock is UTC — anchor "today" here, never in the browser.

Timezone convention (spec 36.37): the single application timezone is Asia/Kolkata (IST).
Mongo stores UTC-aware datetimes; conversion to IST happens only at the edges.
"""

import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo(os.environ.get("APP_TZ", "Asia/Kolkata"))
UTC = timezone.utc

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
# 09:15 -> 15:30 = 22500 seconds
SESSION_SECONDS = 6 * 3600 + 15 * 60


def now_utc() -> datetime:
    return datetime.now(UTC)


def ist_midnight_utc() -> datetime:
    """Today's IST midnight expressed in UTC — the daily P&L / session boundary."""
    n = datetime.now(IST)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_iso(tz: str | None = None) -> str:
    """Today's date as YYYY-MM-DD in `tz` (default: APP_TZ env, else IST for this app)."""
    zone = tz or os.environ.get("APP_TZ", "Asia/Kolkata")
    return datetime.now(ZoneInfo(zone)).strftime("%Y-%m-%d")


def ist_date(dt: datetime | None = None) -> str:
    dt = dt or now_utc()
    return dt.astimezone(IST).strftime("%Y-%m-%d")


def ist_weekday(dt: datetime | None = None) -> int:
    """0=Monday .. 6=Sunday, in IST."""
    dt = dt or now_utc()
    return dt.astimezone(IST).weekday()


def session_elapsed_seconds(dt_ist: datetime) -> int:
    """Seconds elapsed since 09:15 IST, clamped to [0, SESSION_SECONDS]."""
    secs = dt_ist.hour * 3600 + dt_ist.minute * 60 + dt_ist.second - (
        MARKET_OPEN.hour * 3600 + MARKET_OPEN.minute * 60
    )
    return max(0, min(SESSION_SECONDS, secs))


def session_minute_of(elapsed_seconds: int) -> int:
    """1-minute candle index inside the session (0..374)."""
    return max(0, min(374, int(elapsed_seconds) // 60))


def is_weekend(dt_ist: datetime) -> bool:
    return dt_ist.weekday() >= 5


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def ist_dt(date_str: str, minute_of_session: int = 0) -> datetime:
    """IST datetime for a YYYY-MM-DD date plus a minute offset from 09:15."""
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=IST)
    return base + timedelta(minutes=minute_of_session)


def n_trading_days_back(count: int, end_date: str | None = None) -> list[str]:
    """The last `count` NSE-like trading days (weekdays only; a seeded holiday list is
    applied by the provider) as YYYY-MM-DD strings, oldest first, ending at `end_date`."""
    dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now(IST)
    days: list[str] = []
    while len(days) < count:
        if dt.weekday() < 5:
            days.append(dt.strftime("%Y-%m-%d"))
        dt -= timedelta(days=1)
    days.reverse()
    return days
