from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

def _parse_time(value: str) -> time | None:
    try: return time.fromisoformat(value)
    except (TypeError, ValueError): return None

def calendar_sessions(rows: list[dict]) -> dict[str, tuple[datetime, datetime]]:
    sessions: dict[str, tuple[datetime, datetime]] = {}
    for row in rows:
        day, opened, closed = row.get("date"), _parse_time(row.get("open")), _parse_time(row.get("close"))
        try: parsed_day = date.fromisoformat(day)
        except (TypeError, ValueError): continue
        if opened is None or closed is None: continue
        sessions[day] = (datetime.combine(parsed_day, opened, EASTERN), datetime.combine(parsed_day, closed, EASTERN))
    return sessions

def market_status(now_utc: datetime, sessions: dict[str, tuple[datetime, datetime]]) -> str:
    if not sessions: return "UNVERIFIED"
    now_et = now_utc.astimezone(EASTERN)
    session = sessions.get(now_et.date().isoformat())
    if session is None: return "CLOSED"
    return "OPEN" if session[0] <= now_et < session[1] else "CLOSED"

def quote_session_key(quote_utc: datetime, sessions: dict[str, tuple[datetime, datetime]]) -> str | None:
    local = quote_utc.astimezone(EASTERN)
    key = local.date().isoformat()
    session = sessions.get(key)
    return key if session and session[0] <= local <= session[1] else None

def latest_completed_session_key(now_utc: datetime, sessions: dict[str, tuple[datetime, datetime]]) -> str | None:
    completed = [(closed.astimezone(timezone.utc), key) for key, (_opened, closed) in sessions.items()
                 if closed.astimezone(timezone.utc) <= now_utc]
    return max(completed, default=(None, None))[1]

def session_close_utc(key: str | None, sessions: dict[str, tuple[datetime, datetime]]) -> datetime | None:
    session = sessions.get(key) if key else None
    return session[1].astimezone(timezone.utc) if session else None

def expiry_cutoff_utc(expiration_date: str, sessions: dict[str, tuple[datetime, datetime]]) -> str | None:
    session = sessions.get(expiration_date)
    if session is None: return None
    return session[1].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

