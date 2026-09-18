"""
WorkWave connectivity check — SUBMITS REAL ORDERS to the configured territory.

This is not a unit test and is deliberately named so pytest will not collect
it. It performs live writes against WorkWave RouteManager using whatever
credentials are in functions/rm_autobridge/.env.

Submits:
  - Test Customer: Standard Service  (Service order)
  - Test Customer: Drain              (Drop-Off order)
  - Test Customer: Fill               (Pick-up order)

All scheduled for TEST_DATE. DELETE THESE from the WorkWave dashboard after
confirming they appear.

Usage:
    python tests/manual/workwave_live_submit.py
"""

import os
import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

# Load env and make src importable (repo root is two levels up)
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / "functions/rm_autobridge/.env")
sys.path.insert(0, str(REPO_ROOT / "functions/rm_autobridge"))

from src.models.order_input import OrderInput
from src.models.enums import ServiceType
from src.io.workwave_client import WorkwaveClient

TEST_DATE = date(2026, 4, 5)


def make_order(service_type: ServiceType) -> OrderInput:
    return OrderInput(
        name=f"Test Customer: {service_type.value}",
        company="Example Spa Services",
        zoho_id="TEST-000",
        customer_phone="6155550000",
        auto_texting_phone="6155550000",
        service_street="1 Titans Way",
        service_city="Nashville",
        service_state="TN",
        service_zip="37213",
        service_type=service_type,
        service_time=60,
        notes="TEST ORDER — PLEASE DELETE",
        maintenance_frequency="TEST",
        preferred_days="",
        eligibility_start=TEST_DATE,
        eligibility_end=TEST_DATE,
    )


def main():
    api_key = os.getenv("WORKWAVE_API_KEY")
    territory_id = os.getenv("WORKWAVE_TERRITORY_ID")

    if not api_key or not territory_id:
        print("ERROR: WORKWAVE_API_KEY or WORKWAVE_TERRITORY_ID not set in .env")
        sys.exit(1)

    orders = [
        make_order(ServiceType.STANDARD),
        make_order(ServiceType.DRAIN),
        make_order(ServiceType.FILL),
    ]

    print(f"Submitting {len(orders)} test orders for {TEST_DATE} ...")
    print()

    client = WorkwaveClient(api_key=api_key, territory_id=territory_id)
    request_ids, failures = client.submit_orders(orders)

    if request_ids:
        print("SUCCESS — WorkWave accepted the submission.")
        print(f"Request ID(s): {request_ids}")
        print()
        print(">>> Go to your WorkWave dashboard and DELETE the 3 'Test Customer' orders <<<")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  {f['Property Name']}: {f['Error Reason']}")


if __name__ == "__main__":
    main()
