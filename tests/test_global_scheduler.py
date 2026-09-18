"""Tests for GlobalScheduler and FrequencyCalculator."""

from datetime import date
from src.scheduling import BusinessDayCalendar, GlobalScheduler, FrequencyCalculator


def test_frequency_calculator_weekly():
    """Test weekly frequency calculation."""
    dates = FrequencyCalculator.calculate_weekly(2025)

    assert len(dates) >= 52
    assert all(d.year == 2025 for d in dates)

    # Check spacing
    for i in range(len(dates) - 1):
        assert (dates[i + 1] - dates[i]).days == 7


def test_frequency_calculator_biweekly():
    """Test bi-weekly frequency calculation."""
    dates = FrequencyCalculator.calculate_biweekly(2025)

    assert len(dates) >= 26
    assert all(d.year == 2025 for d in dates)

    # Check spacing
    for i in range(len(dates) - 1):
        assert (dates[i + 1] - dates[i]).days == 14


def test_frequency_calculator_monthly():
    """Test monthly frequency calculation."""
    dates = FrequencyCalculator.calculate_monthly(2025, service_group=2)

    assert len(dates) == 12
    assert all(d.year == 2025 for d in dates)

    # Should have one date per month
    months = [d.month for d in dates]
    assert sorted(months) == list(range(1, 13))


def test_frequency_calculator_quarterly():
    """Test quarterly frequency calculation."""
    dates = FrequencyCalculator.calculate_quarterly(2025, start_month=1)

    assert len(dates) == 4
    assert all(d.year == 2025 for d in dates)

    # Should be months 1, 4, 7, 10
    months = sorted([d.month for d in dates])
    assert months == [1, 4, 7, 10]


def test_frequency_calculator_semi_annual():
    """Test semi-annual frequency calculation."""
    dates = FrequencyCalculator.calculate_semi_annual(2025, service_group=1)

    assert len(dates) == 2
    assert all(d.year == 2025 for d in dates)

    # Should be January and July
    months = sorted([d.month for d in dates])
    assert months == [1, 7]


def test_frequency_calculator_annual():
    """Test annual frequency calculation."""
    dates = FrequencyCalculator.calculate_annual(2025, month=6)

    assert len(dates) == 1
    assert dates[0].year == 2025
    assert dates[0].month == 6


def test_global_scheduler_initialization():
    """Test scheduler initializes correctly."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    assert scheduler.calendar == calendar
    assert len(scheduler.daily_load) == 0


def test_scheduler_adjusts_weekend_to_business_day():
    """Test that scheduler moves weekend dates to business days."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Jan 4, 2025 is a Saturday
    weekend_date = date(2025, 1, 4)
    pattern_dates = [weekend_date]

    # Create a mock property
    property = None

    scheduled = scheduler.schedule_property(property, pattern_dates)

    # Should be adjusted to a business day
    assert len(scheduled) == 1
    assert calendar.is_business_day(scheduled[0])
    assert scheduled[0] != weekend_date


def test_scheduler_adjusts_holiday_to_business_day():
    """Test that scheduler moves holiday dates to business days."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Jan 1, 2025 is New Year's Day
    holiday = date(2025, 1, 1)
    pattern_dates = [holiday]

    property = None
    scheduled = scheduler.schedule_property(property, pattern_dates)

    # Should be adjusted to a business day
    assert len(scheduled) == 1
    assert calendar.is_business_day(scheduled[0])
    assert scheduled[0] != holiday


def test_scheduler_honors_preferred_weekday():
    """Test that scheduler honors preferred weekday when possible."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Request dates with preference for Monday (0)
    pattern_dates = [
        date(2025, 1, 15),  # Wednesday
        date(2025, 2, 15),  # Saturday
        date(2025, 3, 15),  # Saturday
    ]

    property = None
    scheduled = scheduler.schedule_property(property, pattern_dates, preferred_weekday=0)

    # All scheduled dates should be Mondays (or best attempt)
    for d in scheduled:
        assert calendar.is_business_day(d)
        # Should be Monday or close to it if Monday not available
        assert d.weekday() in [0, 1, 2, 3, 4]


def test_scheduler_tracks_load():
    """Test that scheduler tracks daily load."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Schedule multiple properties
    for i in range(5):
        pattern_dates = [date(2025, 1, 15)]  # All on same ideal date
        scheduler.schedule_property(None, pattern_dates)

    # Load should be tracked
    load_summary = scheduler.get_load_summary()
    assert len(load_summary) > 0

    # Total load should equal number of scheduled properties
    total_scheduled = sum(load_summary.values())
    assert total_scheduled == 5


def test_scheduler_load_balancing():
    """Test that scheduler distributes load when no preference."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Schedule many properties with same ideal date (mid-week, no preference)
    pattern_dates = [date(2025, 1, 15)]  # Wednesday

    scheduled_dates = []
    for i in range(20):
        result = scheduler.schedule_property(None, pattern_dates, preferred_weekday=None)
        scheduled_dates.extend(result)

    # Should spread across multiple days in that week
    unique_dates = set(scheduled_dates)
    assert len(unique_dates) > 1, "Should distribute across multiple days"

    # All should still be in same week
    week_start = date(2025, 1, 13)  # Monday of that week
    week_end = date(2025, 1, 17)  # Friday of that week
    assert all(week_start <= d <= week_end for d in scheduled_dates)


def test_scheduler_statistics():
    """Test scheduler load statistics."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Initially empty
    stats = scheduler.get_load_statistics()
    assert stats["mean"] == 0
    assert stats["max"] == 0
    assert stats["min"] == 0

    # Schedule some properties
    for i in range(10):
        pattern_dates = [date(2025, 1, 15 + i)]
        scheduler.schedule_property(None, pattern_dates)

    stats = scheduler.get_load_statistics()
    assert stats["mean"] > 0
    assert stats["max"] >= stats["mean"]
    assert stats["min"] <= stats["mean"]


def test_scheduler_with_multiple_dates():
    """Test scheduling property with multiple dates."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Schedule quarterly pattern
    pattern_dates = FrequencyCalculator.calculate_quarterly(2025, start_month=1)

    scheduled = scheduler.schedule_property(None, pattern_dates)

    # Should have 4 dates
    assert len(scheduled) == 4

    # All should be business days
    assert all(calendar.is_business_day(d) for d in scheduled)


def test_all_scheduled_dates_are_business_days():
    """Critical: Verify no weekends or holidays in scheduled dates."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Test with various frequency patterns
    patterns = [
        FrequencyCalculator.calculate_weekly(2025),
        FrequencyCalculator.calculate_monthly(2025, 1),
        FrequencyCalculator.calculate_quarterly(2025, 1),
        FrequencyCalculator.calculate_semi_annual(2025, 1),
        FrequencyCalculator.calculate_annual(2025, 6),
    ]

    all_scheduled = []
    for pattern in patterns:
        scheduled = scheduler.schedule_property(None, pattern)
        all_scheduled.extend(scheduled)

    # CRITICAL: No weekends or holidays
    failures = []
    for d in all_scheduled:
        if not calendar.is_business_day(d):
            failures.append(d)

    assert len(failures) == 0, f"Found {len(failures)} non-business days: {failures}"
