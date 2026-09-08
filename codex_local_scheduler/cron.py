"""Small, dependency-free cron matching for five-field schedules."""

from __future__ import annotations

from datetime import datetime


FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _matches_field(expression: str, value: int, lower: int, upper: int) -> bool:
    matched = False
    for part in expression.split(","):
        step = 1
        base = part
        if "/" in part:
            base, raw_step = part.split("/", 1)
            step = int(raw_step)
            if step <= 0:
                raise ValueError("cron step must be positive")
        if base == "*":
            start, end = lower, upper
        elif "-" in base:
            start, end = (int(item) for item in base.split("-", 1))
        else:
            start = end = int(base)
        if start < lower or end > upper or start > end:
            raise ValueError(f"cron value {part!r} is outside {lower}-{upper}")
        # Cron permits both 0 and 7 for Sunday. Check 7 separately because
        # the datetime representation deliberately uses 0 for Sunday.
        if lower == 0 and upper == 7 and value == 0 and start <= 7 <= end and (7 - start) % step == 0:
            matched = True
        if start <= value <= end and (value - start) % step == 0:
            matched = True
    return matched


def fields_for(schedule: str) -> tuple[str, str, str, str, str]:
    """Parse and validate all five fields of a supported cron expression."""
    fields = schedule.split()
    if len(fields) != 5:
        raise ValueError("schedule must contain five cron fields")
    for field, bounds in zip(fields, FIELDS):
        # Match the lower bound only to exercise the same parser used at runtime.
        _matches_field(field, bounds[0], *bounds)
    return tuple(fields)  # type: ignore[return-value]


def matches(schedule: str, moment: datetime) -> bool:
    """Return whether a five-field cron expression matches `moment`."""
    fields = fields_for(schedule)
    minute, hour, day, month, weekday = (moment.minute, moment.hour, moment.day, moment.month, (moment.weekday() + 1) % 7)
    if not (
        _matches_field(fields[0], minute, *FIELDS[0])
        and _matches_field(fields[1], hour, *FIELDS[1])
        and _matches_field(fields[3], month, *FIELDS[3])
    ):
        return False
    day_matches = _matches_field(fields[2], day, *FIELDS[2])
    weekday_matches = _matches_field(fields[4], weekday, *FIELDS[4])
    # Vixie cron semantics: when both DOM and DOW are restricted, either may match.
    if fields[2] == "*":
        return weekday_matches
    if fields[4] == "*":
        return day_matches
    return day_matches or weekday_matches
