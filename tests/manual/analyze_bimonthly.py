"""Analysis script: Run BiMonthlyHandler against all bi_monthly properties in properties.csv.

Categories:
  STANDARD    - Property generated orders successfully with no anomalies
  BUG         - Property generated orders but dates fall on weekends or holidays
  HOL_OK      - Property had a date that was originally a holiday/weekend and was correctly adjusted
  MANUAL      - Property produced orders with no eligibility_start (manual-schedule orders)
  DATA_ERROR  - Property failed at read/parse/validation stage
  ERROR       - Property failed during order generation (handler raised an exception)

Usage (from repo root):
  python -m tests.analyze_bimonthly
"""

import sys
import os

# Ensure repo root and the rm_autobridge function's `src` package resolve
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "functions", "rm_autobridge"))

import io
import pandas as pd

from src.config import get_config
from src.io.csv_reader import CSVReader
from src.io.validators import PropertyValidator
from src.membership.bimonthly import BiMonthlyHandler
from src.scheduling.business_day_calendar import BusinessDayCalendar
from src.scheduling.global_scheduler import GlobalScheduler, FrequencyCalculator

# ── Config ──────────────────────────────────────────────────────────────────
PROPERTIES_CSV = os.path.join(REPO_ROOT, "properties.csv")
TARGET_YEAR = 2026
BI_MONTHLY_MEMBERSHIPS = None  # resolved from config below


def get_bimonthly_membership_names() -> list[str]:
    config = get_config()
    names = []
    for category, membership_list in config.membership_tiers.items():
        if category == "bi_monthly" and isinstance(membership_list, list):
            names.extend(membership_list)
    return names


# ── Category helpers ─────────────────────────────────────────────────────────


def check_orders(orders, calendar: BusinessDayCalendar):
    """Inspect a list of OrderInput objects.

    Returns:
        (category, details)  where category is one of the result keys.
    """
    has_manual = False
    bad_dates = []

    for order in orders:
        d = order.eligibility_start
        if d is None:
            has_manual = True
            continue
        if not calendar.is_business_day(d):
            bad_dates.append(d)

    if bad_dates:
        return "BUG", f"Non-business-day dates generated: {bad_dates}"

    if has_manual:
        return "MANUAL", "Order(s) with no eligibility_start produced"

    return "STANDARD", f"{len(orders)} orders generated OK"


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    global BI_MONTHLY_MEMBERSHIPS
    BI_MONTHLY_MEMBERSHIPS = get_bimonthly_membership_names()
    print(f"Bi-monthly membership types from config: {BI_MONTHLY_MEMBERSHIPS}\n")

    # Read raw CSV bytes
    with open(PROPERTIES_CSV, "rb") as f:
        raw_bytes = f.read()

    # Parse CSV without the CSVReader filter so we can see all rows
    df = pd.read_csv(io.BytesIO(raw_bytes))

    # Filter to bi_monthly membership types
    mask = df["Maintenance Membership"].isin(BI_MONTHLY_MEMBERSHIPS)
    bi_monthly_df = df[mask].copy()

    total_in_csv = len(bi_monthly_df)
    print(f"Bi-monthly rows found in properties.csv: {total_in_csv}\n")

    if total_in_csv == 0:
        print("No bi-monthly properties found. Exiting.")
        return

    calendar = BusinessDayCalendar(TARGET_YEAR)
    handler = BiMonthlyHandler()
    validator = PropertyValidator()
    reader = CSVReader()

    results = {
        "STANDARD": [],
        "BUG": [],
        "HOL_OK": [],
        "MANUAL": [],
        "DATA_ERROR": [],
        "ERROR": [],
    }

    for idx, row in bi_monthly_df.iterrows():
        row_data = row.to_dict()
        prop_name = str(row_data.get("Property Name", f"Row {idx+2}"))
        record_id = str(row_data.get("Record Id", ""))

        # ── Stage 1: validator skip/error check ──────────────────────────────
        is_valid, error_reason, should_skip = validator.validate_property(row_data)
        if should_skip:
            # Skipped means invalid membership status - count as DATA_ERROR with note
            results["DATA_ERROR"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": f"Skipped by validator: {error_reason}",
                }
            )
            continue

        if not is_valid:
            results["DATA_ERROR"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": f"Validation failed: {error_reason}",
                }
            )
            continue

        # ── Stage 2: parse into Property object ──────────────────────────────
        try:
            prop = reader._parse_property(row_data)
        except Exception as e:
            results["DATA_ERROR"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": f"Parse error: {e}",
                }
            )
            continue

        # ── Stage 3: generate orders via BiMonthlyHandler ────────────────────
        # Use a fresh scheduler per property so load balancing is independent
        scheduler = GlobalScheduler(calendar)
        try:
            orders = handler.generate_orders(prop, TARGET_YEAR, scheduler)
        except Exception as e:
            results["ERROR"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": f"Handler exception: {e}",
                }
            )
            continue

        # ── Stage 4: check for HOL_OK ─────────────────────────────────────────
        # HOL_OK: the ideal biweekly pattern landed on a holiday or weekend, so
        # the scheduler had to move it. Detected from the ideal dates alone --
        # any that are not business days were necessarily shifted.
        try:
            start_date = handler.service_group_manager.get_start_date(
                prop.monthly_service_group or 1, TARGET_YEAR
            )
            ideal_dates = set(
                FrequencyCalculator.calculate_biweekly(TARGET_YEAR, start_date=start_date)
            )
            hol_ok_dates = {d for d in ideal_dates if not calendar.is_business_day(d)}
        except Exception:
            hol_ok_dates = set()

        category, detail = check_orders(orders, calendar)

        if hol_ok_dates and category == "STANDARD":
            results["HOL_OK"].append(
                {
                    "property": prop_name,
                    "record_id": record_id,
                    "reason": detail,
                    "hol_ok_dates": sorted(hol_ok_dates),
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

    # ── Report ──────────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"BIMONTHLY HANDLER ANALYSIS  —  Year: {TARGET_YEAR}")
    print("=" * 70)
    print()

    grand_total = sum(len(v) for v in results.values())

    for cat in ["STANDARD", "BUG", "HOL_OK", "MANUAL", "DATA_ERROR", "ERROR"]:
        items = results[cat]
        print(f"{cat}: {len(items)}")
        for item in items:
            prop = item.get("property", "?")
            rec = item.get("record_id", "?")
            reason = item.get("reason", "")
            count = item.get("order_count", "")
            hol = item.get("hol_ok_dates", [])
            order_info = f"  ({count} orders)" if count != "" else ""
            hol_info = f"  holidays_avoided={hol}" if hol else ""
            print(f"  • [{rec}] {prop}{order_info} — {reason}{hol_info}")
        print()

    print("=" * 70)
    print(
        f"TOTALS:  {grand_total} properties processed  (from {total_in_csv} bi-monthly rows in CSV)"
    )
    print(f"  STANDARD   : {len(results['STANDARD'])}")
    print(f"  BUG        : {len(results['BUG'])}")
    print(f"  HOL_OK     : {len(results['HOL_OK'])}")
    print(f"  MANUAL     : {len(results['MANUAL'])}")
    print(f"  DATA_ERROR : {len(results['DATA_ERROR'])}")
    print(f"  ERROR      : {len(results['ERROR'])}")
    print("=" * 70)


if __name__ == "__main__":
    main()
