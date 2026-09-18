"""Tests for BusinessDayCalendar."""

import pytest
from datetime import date
from src.scheduling.business_day_calendar import BusinessDayCalendar


@pytest.fixture
def calendar():
    return BusinessDayCalendar(2025)


def test_calendar_initialization(calendar):
    """Test calendar initializes with correct year."""
    assert calendar.year == 2025
    assert len(calendar.business_days) > 0


def test_federal_holidays_2025(calendar):
    """Test that known 2025 federal holidays are marked."""

    # Fixed holidays
    assert date(2025, 1, 1) in calendar.holidays  # New Year's Day
    assert date(2025, 7, 4) in calendar.holidays  # Independence Day
    assert date(2025, 12, 24) in calendar.holidays  # Christmas Eve
    assert date(2025, 12, 25) in calendar.holidays  # Christmas

    # Calculated holidays
    assert date(2025, 11, 27) in calendar.holidays  # Thanksgiving (4th Thu in Nov)

    # Total should be 5 holidays
    assert len(calendar.holidays) == 5


def test_no_weekends_in_business_days(calendar):
    """Test that no weekends appear in business days."""

    for day in calendar.business_days:
        assert day.weekday() < 5, f"{day} is a weekend day!"


def test_no_holidays_in_business_days(calendar):
    """Test that holidays are excluded from business days."""

    for holiday in calendar.holidays:
        assert (
            holiday not in calendar.business_days
        ), f"Holiday {holiday} is marked as business day!"


def test_custom_holidays(calendar):
    """Test adding custom holidays."""
    custom = [date(2025, 3, 15), date(2025, 6, 1)]
    calendar = BusinessDayCalendar(2025, custom_holidays=custom)

    assert date(2025, 3, 15) in calendar.holidays
    assert date(2025, 6, 1) in calendar.holidays
    assert date(2025, 3, 15) not in calendar.business_days
    assert date(2025, 6, 1) not in calendar.business_days


def test_is_business_day(calendar):
    """Test business day checking."""

    # Normal weekday
    assert calendar.is_business_day(date(2025, 1, 2))  # Thursday

    # Weekend
    assert not calendar.is_business_day(date(2025, 1, 4))  # Saturday
    assert not calendar.is_business_day(date(2025, 1, 5))  # Sunday

    # Holiday
    assert not calendar.is_business_day(date(2025, 1, 1))  # New Year's


def test_next_business_day_simple(calendar):
    """Test finding next business day without preference."""

    # From a Friday, next business day is Monday
    friday = date(2025, 1, 3)
    next_day = calendar.next_business_day(friday)
    assert next_day == date(2025, 1, 3)  # Friday itself is a business day

    # From a Saturday
    saturday = date(2025, 1, 4)
    next_day = calendar.next_business_day(saturday)
    assert next_day == date(2025, 1, 6)  # Monday

    # From a Sunday
    sunday = date(2025, 1, 5)
    next_day = calendar.next_business_day(sunday)
    assert next_day == date(2025, 1, 6)  # Monday


def test_next_business_day_with_preference(calendar):
    """Test finding next business day with weekday preference."""

    # Start on a Monday, prefer Tuesday
    monday = date(2025, 1, 6)
    next_day = calendar.next_business_day(monday, prefer_weekday=1)  # Tuesday
    assert next_day == date(2025, 1, 7)  # Next Tuesday
    assert next_day.weekday() == 1

    # Start on a Friday, prefer Monday
    friday = date(2025, 1, 3)
    next_day = calendar.next_business_day(friday, prefer_weekday=0)  # Monday
    assert next_day == date(2025, 1, 6)  # Next Monday
    assert next_day.weekday() == 0


def test_next_business_day_skips_holidays(calendar):
    """Test that next business day skips holidays."""

    # Dec 24, 2025 is Wednesday, but Dec 25 is Christmas (Thursday)
    wednesday = date(2025, 12, 24)
    next_day = calendar.next_business_day(wednesday, prefer_weekday=3)  # Thursday

    # Should skip Christmas and find next Thursday
    assert next_day != date(2025, 12, 25)
    assert calendar.is_business_day(next_day)


def test_get_business_days_in_month(calendar):
    """Test getting all business days in a month."""

    jan_days = calendar.get_business_days_in_month(1)

    # January 2025 has 31 days, minus 8 weekend days, minus 1 holiday (New Year's) = 22
    assert len(jan_days) == 22

    # All should be in January
    assert all(d.month == 1 for d in jan_days)

    # All should be business days
    assert all(calendar.is_business_day(d) for d in jan_days)


def test_get_business_days_in_week(calendar):
    """Test getting business days in a specific week."""

    # Week of Jan 6-12, 2025 (no holidays)
    monday = date(2025, 1, 6)
    week_days = calendar.get_business_days_in_week(monday)

    # Should have 5 days (Mon-Fri)
    assert len(week_days) == 5
    assert week_days[0].weekday() == 0  # Monday
    assert week_days[4].weekday() == 4  # Friday


def test_get_business_days_in_week_with_holiday(calendar):
    """Test getting business days in a week containing a holiday."""

    # Week containing Thanksgiving (Nov 27, 2025 - Thursday)
    thanksgiving = date(2025, 11, 27)
    week_days = calendar.get_business_days_in_week(thanksgiving)

    # Should have 4 days (Mon, Tue, Wed, Fri, since Thursday is holiday)
    assert len(week_days) == 4
    assert thanksgiving not in week_days


def test_business_day_count_2025(calendar):
    """Test total business days in 2025."""
    # 2025: 365 days - 104 weekend days - 5 holidays = 256
    # (None of the 5 holidays fall on weekends in 2025)
    total = len(calendar.business_days)

    assert total == 256


def test_year_boundary(calendar):
    """Test calendar only includes days from specified year."""
    # No dates from 2024 or 2026
    assert all(d.year == 2025 for d in calendar.business_days)
