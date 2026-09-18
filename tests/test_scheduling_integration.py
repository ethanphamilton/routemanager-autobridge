"""Integration tests for the scheduling system.

Tests the complete flow: BusinessDayCalendar → GlobalScheduler → FrequencyCalculator
"""

from datetime import date
from src.scheduling import BusinessDayCalendar, GlobalScheduler, FrequencyCalculator
from src.models import Property, OrderInput, ServiceType
from src.membership import AnnualHandler


def _annual_property() -> Property:
    """Minimal Property for an annual member with a June Drain & Detail."""
    return Property(
        record_id="TEST-ANNUAL-1",
        property_name="Test Property",
        combined_address="1 Main St, Asheville NC 28801",
        maintenance_membership="Annual Residential Package",
        membership_status="Active Maintenance Member",
        dd_service_group="Annual - Jun",
    )


def test_annual_handler_emits_a_drain_and_fill_spanning_the_target_month():
    """AnnualHandler produces one D&D pair eligible across the whole target month.

    Annual members have no preferred day. The handler sets eligibility to the
    full month and RouteManager selects the day, so the pair is not snapped to
    a single scheduled date the way the weekly handlers are.
    """
    scheduler = GlobalScheduler(BusinessDayCalendar(2025))
    orders = AnnualHandler().generate_orders(_annual_property(), 2025, scheduler)

    assert [o.service_type.value for o in orders] == ["Drain", "Fill"]
    for order in orders:
        assert order.eligibility_start == date(2025, 6, 1)
        assert order.eligibility_end == date(2025, 6, 30)


def test_annual_eligibility_excludes_weekends():
    """Month-span eligibility contains business days only.

    PackageDescriptions.md specifies that annual, semi-annual and quarterly
    eligibility covers the target month "except Saturdays and Sundays". Those
    tiers have no preferred day, so RouteManager selects the day from the
    window and the window must not offer one.
    """
    scheduler = GlobalScheduler(BusinessDayCalendar(2025))
    orders = AnnualHandler().generate_orders(_annual_property(), 2025, scheduler)
    orders[0].run_id = "test-run"

    emitted = orders[0].to_dict()["eligibility"]["onDates"]
    weekend = [d for d in emitted if date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() >= 5]
    assert weekend == []
    assert len(emitted) == 21, "June 2025 has 21 weekdays"


def test_single_date_eligibility_is_unaffected():
    """A scheduled single-date order passes through the weekday filter intact."""
    order = OrderInput(
        name="Test: Weekly",
        company="",
        zoho_id="T",
        customer_phone="",
        auto_texting_phone="",
        service_street="1 Main St",
        service_city="Asheville",
        service_state="NC",
        service_zip="28801",
        service_type=ServiceType.STANDARD,
        service_time=20,
        notes="n",
        maintenance_frequency="Weekly",
        preferred_days="M",
        eligibility_start=date(2025, 6, 2),
        eligibility_end=date(2025, 6, 2),
    )
    order.run_id = "test-run"
    assert order.to_dict()["eligibility"]["onDates"] == ["20250602"]


def test_weekend_only_window_falls_back_rather_than_emptying():
    """A window with no weekday returns its dates rather than an empty list.

    An empty onDates list would leave the order unschedulable in WorkWave.
    """
    order = OrderInput(
        name="Test: Drain",
        company="",
        zoho_id="T",
        customer_phone="",
        auto_texting_phone="",
        service_street="1 Main St",
        service_city="Asheville",
        service_state="NC",
        service_zip="28801",
        service_type=ServiceType.DRAIN,
        service_time=40,
        notes="n",
        maintenance_frequency="Annual",
        preferred_days="",
        eligibility_start=date(2025, 6, 7),
        eligibility_end=date(2025, 6, 8),
    )
    order.run_id = "test-run"
    assert order.to_dict()["eligibility"]["onDates"] == ["20250607", "20250608"]


def test_no_weekends_in_generated_orders():
    """Critical test: Verify NO orders are generated for weekends or holidays."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Test various frequency patterns
    test_cases = [
        (FrequencyCalculator.calculate_weekly(2025), "Weekly"),
        (FrequencyCalculator.calculate_biweekly(2025), "Biweekly"),
        (FrequencyCalculator.calculate_monthly(2025, 1), "Monthly"),
        (FrequencyCalculator.calculate_quarterly(2025, 1), "Quarterly"),
        (FrequencyCalculator.calculate_semi_annual(2025, 1), "Semi-annual"),
        (FrequencyCalculator.calculate_annual(2025, 6), "Annual"),
    ]

    all_scheduled = []
    for pattern, name in test_cases:
        scheduled = scheduler.schedule_property(None, pattern)
        all_scheduled.extend(scheduled)

    # Check every single date
    weekend_dates = []
    holiday_dates = []

    for d in all_scheduled:
        if d.weekday() >= 5:  # Saturday or Sunday
            weekend_dates.append(d)
        if d in calendar.holidays:
            holiday_dates.append(d)

    assert len(weekend_dates) == 0, f"Found {len(weekend_dates)} weekend dates: {weekend_dates}"
    assert len(holiday_dates) == 0, f"Found {len(holiday_dates)} holiday dates: {holiday_dates}"


def test_preferred_day_honored():
    """Test that preferred days are honored when specified."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Generate monthly pattern for customer who prefers Tuesdays
    pattern = FrequencyCalculator.calculate_monthly(2025, service_group=2)

    scheduled = scheduler.schedule_property(None, pattern, preferred_weekday=1)  # Tuesday

    # Count how many are actually Tuesdays (should be most/all)
    tuesdays = sum(1 for d in scheduled if d.weekday() == 1)

    # Should have high percentage of Tuesdays (some might be off due to holidays)
    assert tuesdays >= len(scheduled) * 0.8, f"Only {tuesdays}/{len(scheduled)} were Tuesdays"


def test_load_balancing_works():
    """Test that load balancing distributes customers across days."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Schedule many customers with same ideal date but no preference
    ideal_date = date(2025, 6, 15)  # A Wednesday

    for i in range(50):
        scheduler.schedule_property(
            None, [ideal_date], preferred_weekday=None  # No preference = load balance
        )

    # Check that load was distributed
    load = scheduler.get_load_summary()

    # Should have spread across multiple days
    assert len(load) > 1, "Load should be distributed across multiple days"

    # No single day should have all 50
    max_load = max(load.values())
    assert max_load < 50, f"All customers on same day: {max_load}"


def test_holidays_are_avoided():
    """Test that federal holidays are never used for scheduling."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Try to schedule on New Year's Day
    new_years = date(2025, 1, 1)
    pattern = [new_years]

    scheduled = scheduler.schedule_property(None, pattern)

    # Should NOT be New Year's Day
    assert scheduled[0] != new_years
    assert calendar.is_business_day(scheduled[0])


def test_custom_holidays_respected():
    """Test that custom holidays are also avoided."""
    # Add custom business closure
    custom_closure = date(2025, 3, 15)
    calendar = BusinessDayCalendar(2025, custom_holidays=[custom_closure])
    scheduler = GlobalScheduler(calendar)

    # Try to schedule on that day
    pattern = [custom_closure]
    scheduled = scheduler.schedule_property(None, pattern)

    # Should NOT be the custom holiday
    assert scheduled[0] != custom_closure
    assert calendar.is_business_day(scheduled[0])


def test_full_year_generation():
    """Integration test: Generate full year schedule for multiple customers."""
    calendar = BusinessDayCalendar(2025)
    scheduler = GlobalScheduler(calendar)

    # Simulate different customer types
    customers = [
        ("weekly", FrequencyCalculator.calculate_weekly(2025)),
        ("biweekly", FrequencyCalculator.calculate_biweekly(2025)),
        ("monthly", FrequencyCalculator.calculate_monthly(2025, 1)),
        ("quarterly", FrequencyCalculator.calculate_quarterly(2025, 1)),
        ("annual", FrequencyCalculator.calculate_annual(2025, 6)),
    ]

    all_dates = []
    for customer_type, pattern in customers:
        scheduled = scheduler.schedule_property(None, pattern)
        all_dates.extend(scheduled)

    # Verify ALL dates are business days
    non_business_days = [d for d in all_dates if not calendar.is_business_day(d)]

    assert (
        len(non_business_days) == 0
    ), f"Found {len(non_business_days)} non-business days: {non_business_days}"

    # Verify we have substantial coverage
    # Weekly (52) + Biweekly (26) + Monthly (12) + Quarterly (4) + Annual (1) = 95 dates
    assert len(all_dates) >= 95, "Should have generated substantial schedule"

    print(f"\n✓ Successfully generated {len(all_dates)} business day appointments")
    print(f"✓ Load statistics: {scheduler.get_load_statistics()}")
