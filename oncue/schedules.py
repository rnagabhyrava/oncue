"""Friendly schedules backed by cron, plus durable one-time occurrences."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .cron import fields_for, matches


def once_at(schedule: str) -> datetime | None:
    if not schedule.startswith('once:'):
        return None
    value = datetime.fromisoformat(schedule[5:])
    if value.tzinfo is None:
        raise ValueError('One-time schedules need a timezone')
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def validate_schedule(schedule: str, zone: str) -> None:
    ZoneInfo(zone)
    if once_at(schedule) is None:
        fields_for(schedule)


def from_form(data: dict) -> str:
    kind = data.get('frequency', 'daily')
    zone = ZoneInfo(data.get('timezone', 'UTC'))
    if kind == 'custom':
        schedule = str(data.get('cron', '')).strip()
        fields_for(schedule)
        return schedule
    raw_time = str(data.get('time', '09:00'))
    try:
        hour, minute = map(int, raw_time.split(':'))
    except (TypeError, ValueError):
        raise ValueError('Choose a valid time') from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError('Choose a valid time')
    if kind == 'once':
        try:
            local = datetime.fromisoformat(f"{data.get('date', '')}T{hour:02}:{minute:02}")
        except ValueError:
            raise ValueError('Choose a date for this one-time task') from None
        aware = local.replace(tzinfo=zone)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) != local:
            raise ValueError('That time does not exist due to daylight saving. Choose another time.')
        return 'once:' + utc.isoformat()
    if kind == 'daily':
        days = '*'
    elif kind == 'weekdays':
        days = '1-5'
    elif kind == 'weekly':
        day = int(data.get('weekday', 1))
        if day not in range(7):
            raise ValueError('Choose a valid weekday')
        days = str(day)
    else:
        raise ValueError('Choose once, daily, weekdays, weekly, or custom')
    return f'{minute} {hour} * * {days}'


def to_form(schedule: str, zone: str) -> dict:
    once = once_at(schedule)
    if once:
        local = once.astimezone(ZoneInfo(zone))
        return dict(frequency='once', date=local.strftime('%Y-%m-%d'), time=local.strftime('%H:%M'))
    minute, hour, dom, month, dow = fields_for(schedule)
    if minute.isdigit() and hour.isdigit() and dom == month == '*':
        kind = {'*': 'daily', '1-5': 'weekdays'}.get(dow, 'weekly' if dow.isdigit() else 'custom')
        if kind != 'custom':
            return dict(frequency=kind, time=f'{int(hour):02}:{int(minute):02}', weekday=int(dow) % 7 if dow.isdigit() else 1)
    return dict(frequency='custom', cron=schedule)


def due_key(schedule: str, zone: str, now: datetime) -> str | None:
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    once = once_at(schedule)
    if once:
        return once.isoformat() if once <= now else None
    return now.isoformat() if matches(schedule, now.astimezone(ZoneInfo(zone))) else None


def next_run(schedule: str, zone: str, now: datetime | None = None) -> str | None:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    return _next_run(schedule, zone, now)


@lru_cache(maxsize=512)
def _next_run(schedule: str, zone: str, now: datetime) -> str | None:
    once = once_at(schedule)
    if once:
        return once.isoformat()
    # Precompute eligible minutes; walk local dates rather than millions of minutes.
    minute, hour, *_ = fields_for(schedule)
    from .cron import _matches_field
    hours = [h for h in range(24) if _matches_field(hour, h, 0, 23)]
    minutes = [m for m in range(60) if _matches_field(minute, m, 0, 59)]
    tz = ZoneInfo(zone)
    start = now.astimezone(tz).date()
    for offset in range(366 * 5):
        date = start + timedelta(days=offset)
        found = []
        if not matches(schedule, datetime(date.year, date.month, date.day, hours[0], minutes[0], tzinfo=tz)):
            continue
        for h in hours:
            for m in minutes:
                local = datetime(date.year, date.month, date.day, h, m, tzinfo=tz)
                for fold in (0, 1):
                    candidate = local.replace(fold=fold).astimezone(timezone.utc)
                    if candidate > now and candidate.astimezone(tz).replace(tzinfo=None) == local.replace(tzinfo=None):
                        found.append(candidate)
        if found:
            return min(found).isoformat()
    return None
