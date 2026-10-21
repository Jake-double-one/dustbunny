from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from dustbunny.config import Settings
from dustbunny.schedule import Cron
from dustbunny.server import Scheduler

BERLIN = ZoneInfo("Europe/Berlin")


def nxt(expression: str, after: datetime) -> datetime | None:
    return Cron(expression).next_after(after)


def test_daily_and_steps() -> None:
    noon = datetime(2026, 10, 21, 12, 0)
    assert nxt("0 3 * * *", noon) == datetime(2026, 10, 22, 3, 0)
    assert nxt("@daily", noon) == datetime(2026, 10, 22, 0, 0)
    assert nxt("*/15 * * * *", datetime(2026, 10, 21, 12, 7)) == datetime(2026, 10, 21, 12, 15)
    assert nxt("0 */6 * * *", noon) == datetime(2026, 10, 21, 18, 0)  # not 12:00 again
    assert nxt("5,35 8-9 * * *", datetime(2026, 10, 21, 8, 40)) == datetime(2026, 10, 21, 9, 5)


def test_weekdays_months_and_names() -> None:
    wednesday = datetime(2026, 10, 21, 12, 0)
    assert nxt("0 3 * * sun", wednesday) == datetime(2026, 10, 25, 3, 0)
    assert nxt("0 3 * * 7", wednesday) == nxt("0 3 * * 0", wednesday)
    assert nxt("0 3 * * MON-FRI", wednesday) == datetime(2026, 10, 22, 3, 0)
    assert nxt("@weekly", wednesday) == datetime(2026, 10, 25, 0, 0)
    assert nxt("0 0 1 jan *", wednesday) == datetime(2027, 1, 1, 0, 0)
    assert nxt("0 0 29 2 *", wednesday) == datetime(2028, 2, 29, 0, 0)


def test_day_of_month_or_weekday() -> None:
    # like cron: both restricted -> either one matches (the 1st, or a Monday)
    assert nxt("0 0 1 * mon", datetime(2026, 10, 21, 12, 0)) == datetime(2026, 10, 26, 0, 0)


def test_time_zone_and_daylight_saving() -> None:
    # Berlin switches to summer time on 29 March 2026: 3:00 is then 01:00 UTC, before 02:00 UTC
    found = nxt("0 3 * * *", datetime(2026, 3, 28, 12, 0, tzinfo=BERLIN))
    assert found == datetime(2026, 3, 29, 3, 0, tzinfo=BERLIN)
    assert found.astimezone(UTC).hour == 1
    scheduler = Scheduler(SimpleNamespace(), timedelta(hours=6), cron=Cron("0 3 * * *"), tz=BERLIN)
    now = datetime(2026, 10, 21, 23, 30, tzinfo=UTC)  # already 01:30 on the 22nd in Berlin
    assert scheduler.next_after(now) == datetime(2026, 10, 22, 3, 0, tzinfo=BERLIN)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "0 3 * *",
        "0 3 * * * *",
        "60 * * * *",
        "0 24 * * *",
        "* * 0 * *",
        "*/0 * * * *",
        "0 3 * * funday",
        "5-1 * * * *",
        "0 0 31 2 *",
    ],
)
def test_invalid_expressions(bad: str) -> None:
    with pytest.raises(ValueError):
        Cron(bad)


def test_settings() -> None:
    settings = Settings(scan_schedule="0 3 * * *", tz="Europe/Berlin")
    assert settings.cron.expression == "0 3 * * *" and settings.time_zone == BERLIN
    unset = Settings(scan_schedule="", tz="")
    assert unset.cron is None and str(unset.time_zone) == "UTC"
    with pytest.raises(ValueError, match="cron"):
        Settings(scan_schedule="every night")
    with pytest.raises(ValueError, match="time zone"):
        Settings(tz="Mars/Olympus")


def test_cron_scheduler_skips_the_start_scan_when_a_report_exists() -> None:
    scans: list[int] = []
    service = SimpleNamespace(
        ready=True,
        report=SimpleNamespace(complete=True),
        last_error=None,
        scan=lambda: scans.append(1),
    )

    async def run() -> None:
        scheduler = Scheduler(service, timedelta(0), cron=Cron("0 3 * * *"), tz=BERLIN)
        scheduler.start()
        await asyncio.sleep(0.05)
        assert scans == [] and scheduler.next_scan_at is not None
        assert scheduler.next_scan_at.astimezone(BERLIN).hour == 3
        scheduler.trigger()  # "Scan now" still works
        await asyncio.sleep(0.05)
        assert scans == [1]
        await scheduler.stop()

    asyncio.run(run())
    service.report = None  # nothing to show yet: scan right away
    asyncio.run(_start_and_stop(Scheduler(service, timedelta(0), cron=Cron("@daily"))))
    assert scans == [1, 1]


async def _start_and_stop(scheduler: Scheduler) -> None:
    scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()
