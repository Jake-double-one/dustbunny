"""Cron expressions for SCAN_SCHEDULE: five fields, in the container's time zone (TZ)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
# name, lowest, highest, names for 1.. (months) or 0.. (days)
_FIELDS = (
    ("minute", 0, 59, {}),
    ("hour", 0, 23, {}),
    ("day of month", 1, 31, {}),
    ("month", 1, 12, {name: i + 1 for i, name in enumerate(_MONTHS)}),
    ("day of week", 0, 7, {name: i for i, name in enumerate(_DAYS)}),  # 0 and 7: Sunday
)


class Cron:
    """``minute hour day-of-month month day-of-week`` like crontab(5), incl. lists,
    ranges, steps, month/day names and @daily etc. As in cron, a restricted day of
    month and a restricted day of week match if either one does."""

    def __init__(self, expression: str):
        self.expression = expression.strip()
        text = ALIASES.get(self.expression.lower(), self.expression)
        parts = text.split()
        if len(parts) != 5:
            raise ValueError(
                f"invalid cron expression {expression!r}: needs 5 fields "
                "(minute hour day month weekday), e.g. '0 3 * * *'"
            )
        values = [_field(part, *spec) for part, spec in zip(parts, _FIELDS, strict=True)]
        self.minutes, self.hours, self.days, self.months, weekdays = values
        self.weekdays = {day % 7 for day in weekdays}
        self._any_day = parts[2].startswith("*")
        self._any_weekday = parts[4].startswith("*")
        if self.next_after(datetime(2000, 1, 1)) is None:
            raise ValueError(f"cron expression {expression!r} never matches")

    def next_after(self, moment: datetime) -> datetime | None:
        """First matching minute after ``moment``, in its time zone (wall clock)."""
        t = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        end = t + timedelta(days=5 * 366)  # long enough for 29 February
        while t < end:
            if not self._day_matches(t.date()):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            elif t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
            elif t.minute not in self.minutes:
                t += timedelta(minutes=1)
            else:
                return t
        return None

    def _day_matches(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        by_date = day.day in self.days
        by_weekday = day.isoweekday() % 7 in self.weekdays
        if self._any_day and self._any_weekday:
            return True
        if self._any_day:
            return by_weekday
        if self._any_weekday:
            return by_date
        return by_date or by_weekday


def _field(text: str, name: str, low: int, high: int, names: dict[str, int]) -> set[int]:
    def number(value: str) -> int:
        value = value.strip().lower()
        if value in names:
            return names[value]
        if not value.isdigit():
            raise ValueError(f"invalid {name} {value!r} in cron expression")
        return int(value)

    result: set[int] = set()
    for item in text.split(","):
        span, slash, step_text = item.partition("/")
        step = number(step_text) if slash else 1
        if span == "*":
            start, stop = low, high
        elif "-" in span:
            start, stop = (number(v) for v in span.split("-", 1))
        else:
            start = number(span)
            stop = high if slash else start
        if step < 1 or not low <= start <= stop <= high:
            raise ValueError(f"invalid {name} {item!r} in cron expression ({low}-{high})")
        result.update(range(start, stop + 1, step))
    return result
