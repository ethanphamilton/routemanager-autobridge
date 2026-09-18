"""Regression test: run all completed handlers against properties.csv.

Completed handlers:
  WEEKLY          → WeeklyQuarterlyHandler
  WEEKLY_MONTHLY  → WeeklyMonthlyHandler
  TWICE_WEEKLY    → TwiceWeeklyMonthlyHandler
  BI_MONTHLY      → BiMonthlyHandler

Categories:
  STANDARD    - All orders generated on business days, no anomalies
  BUG         - One or more orders fall on a non-business day
  HOL_OK      - Scheduled correctly; at least one ideal date was a non-business day
                (holiday/weekend avoidance triggered — expected behaviour)
  MANUAL      - Order produced with no eligibility_start
  DATA_ERROR  - Property failed at read/parse/validation stage
  ERROR       - Handler raised an exception during order generation

Usage (from repo root):
  python -m tests.regression_completed_handlers
"""

import sys
import os
import io

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "functions", "rm_autobridge"))

import pandas as pd
from datetime import date

from src.config import get_config
from src.io.csv_reader import CSVReader
from src.io.validators import PropertyValidator
from src.membership import (
    WeeklyQuarterlyHandler,
    WeeklyMonthlyHandler,
    TwiceWeeklyMonthlyHandler,
    BiMonthlyHandler,
    MonthlyHandler,
    QuarterlyHandler,
    SemiAnnualHandler,
    AnnualHandler,
    CustomBiWeeklyDDHandler,
)
from src.models.enums import Frequency
from src.scheduling.business_day_calendar import BusinessDayCalendar
from src.scheduling.global_scheduler import GlobalScheduler, FrequencyCalculator

PROPERTIES_CSV = os.path.join(REPO_ROOT, "properties.csv")
TARGET_YEAR = 2026

COMPLETED = [
    ("WEEKLY", Frequency.WEEKLY, WeeklyQuarterlyHandler),
    ("WEEKLY_MONTHLY", Frequency.WEEKLY_MONTHLY, WeeklyMonthlyHandler),
    ("TWICE_WEEKLY", Frequency.TWICE_WEEKLY, TwiceWeeklyMonthlyHandler),
    ("BI_MONTHLY", Frequency.BI_MONTHLY, BiMonthlyHandler),
    ("MONTHLY", Frequency.MONTHLY, MonthlyHandler),
    ("QUARTERLY", Frequency.QUARTERLY, QuarterlyHandler),
    ("SEMI_ANNUAL", Frequency.SEMI_ANNUAL, SemiAnnualHandler),
    ("ANNUAL", Frequency.ANNUAL, AnnualHandler),
    ("CUSTOM_BIWEEKLY_DD", Frequency.CUSTOM_BIWEEKLY_DD, CustomBiWeeklyDDHandler),
]


def get_membership_names(config, frequency: Frequency) -> list:
    key = frequency.value
    tiers = config.membership_tiers
    return list(tiers.get(key, []))


def check_orders(orders, calendar: BusinessDayCalendar):
    bad_dates = []
    has_manual = False
    for order in orders:
        start = order.eligibility_start
        end = order.eligibility_end
        if start is None:
            has_manual = True
            continue
        # Month-range orders (start != end) intentionally use the 1st of the
        # month as eligibility_start — skip the business-day check for those.
        is_range = end is not None and end != start
        if not is_range and not calendar.is_business_day(start):
            bad_dates.append(start)
    if bad_dates:
        return "BUG", f"Non-business-day dates: {bad_dates}"
    if has_manual:
        return "MANUAL", "Order(s) with no eligibility_start"
    return "STANDARD", f"{len(orders)} orders OK"


def run_handler(freq: Frequency, handler_cls, membership_names, df, calendar, reader, validator):
    mask = df["Maintenance Membership"].isin(membership_names)
    subset = df[mask].copy()

    results = {
        k: [] for k in ("STANDARD", "BUG", "HOL_OK", "MANUAL", "DATA_ERROR", "ERROR", "SKIPPED")
    }
    handler = handler_cls()

    for idx, row in subset.iterrows():
        row_data = row.to_dict()
        prop_name = str(row_data.get("Property Name", f"Row {idx+2}"))
        record_id = str(row_data.get("Record Id", ""))

        is_valid, error_reason, should_skip = validator.validate_property(row_data)
        if should_skip:
            results["SKIPPED"].append(
                {"property": prop_name, "record_id": record_id, "reason": error_reason}
            )
            continue
        if not is_valid:
            results["DATA_ERROR"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": f"Invalid: {error_reason}",
                }
            )
            continue

        try:
            prop = reader._parse_property(row_data)
        except Exception as e:
            results["DATA_ERROR"].append(
                {"property": prop_name, "record_id": record_id, "reason": f"Parse error: {e}"}
            )
            continue

        scheduler = GlobalScheduler(calendar)
        try:
            orders = handler.generate_orders(prop, TARGET_YEAR, scheduler)
        except Exception as e:
            results["ERROR"].append(
                {"property": prop_name, "record_id": record_id, "reason": str(e)}
            )
            continue

        category, detail = check_orders(orders, calendar)

        # Detect HOL_OK: ideal dates that were non-business days (correctly avoided)
        hol_ok_dates = []
        try:
            ideal = _get_ideal_dates(freq, prop, handler, TARGET_YEAR)
            hol_ok_dates = [d for d in ideal if not calendar.is_business_day(d)]
        except Exception:
            pass

        if hol_ok_dates and category == "STANDARD":
            results["HOL_OK"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": detail,
                    "order_count": len(orders),
                }
            )
        else:
            results[category].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": detail,
                    "order_count": len(orders),
                }
            )

    return results, len(subset)


def _get_ideal_dates(freq: Frequency, prop, handler, year: int) -> list:
    """Return the raw ideal visit dates before scheduling for HOL_OK detection."""
    if freq in (Frequency.WEEKLY, Frequency.WEEKLY_MONTHLY):
        return FrequencyCalculator.calculate_weekly(year, start_date=date(year, 1, 1))
    if freq == Frequency.TWICE_WEEKLY:
        return FrequencyCalculator.calculate_weekly(year, start_date=date(year, 1, 1))
    if freq == Frequency.BI_MONTHLY:
        start = handler.service_group_manager.get_start_date(prop.monthly_service_group or 1, year)
        return FrequencyCalculator.calculate_biweekly(year, start_date=start)
    if freq == Frequency.MONTHLY:
        return FrequencyCalculator.calculate_monthly(year, service_group=prop.monthly_service_group)
    return []


def main():
    config = get_config()
    with open(PROPERTIES_CSV, "rb") as f:
        raw = f.read()
    df = pd.read_csv(io.BytesIO(raw))

    calendar = BusinessDayCalendar(TARGET_YEAR)
    reader = CSVReader()
    validator = PropertyValidator()

    grand = {
        k: 0 for k in ("STANDARD", "BUG", "HOL_OK", "MANUAL", "DATA_ERROR", "ERROR", "SKIPPED")
    }
    grand_total = 0

    print("=" * 72)
    print(f"  REGRESSION TEST — Completed Handlers — Year {TARGET_YEAR}")
    print("=" * 72)

    for label, freq, handler_cls in COMPLETED:
        membership_names = get_membership_names(config, freq)
        results, total_rows = run_handler(
            freq, handler_cls, membership_names, df, calendar, reader, validator
        )

        print(f"\n{'─' * 72}")
        print(f"  {label}  ({total_rows} properties in CSV)")
        print(f"{'─' * 72}")
        for cat in ("STANDARD", "BUG", "HOL_OK", "MANUAL", "DATA_ERROR", "ERROR", "SKIPPED"):
            items = results[cat]
            print(f"  {cat:<12}: {len(items)}")
            if cat in ("BUG", "ERROR", "DATA_ERROR") and items:
                for item in items:
                    print(f"    • [{item['record_id']}] {item['property']} — {item['reason']}")
            grand[cat] += len(items)

        grand_total += total_rows

    print(f"\n{'=' * 72}")
    print(f"  GRAND TOTALS  ({grand_total} properties across all completed handlers)")
    print(f"{'=' * 72}")
    for cat in ("STANDARD", "BUG", "HOL_OK", "MANUAL", "DATA_ERROR", "ERROR", "SKIPPED"):
        print(f"  {cat:<12}: {grand[cat]}")
    print("=" * 72)


if __name__ == "__main__":
    main()
