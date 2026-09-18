"""Live test: pull properties from Zoho CRM and run through order generator.

Does NOT submit anything to WorkWave — read-only end-to-end validation.

Usage (from repo root):
    python -m tests.live_zoho_test [--month M] [--year Y]
"""

import sys
import os
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "functions", "rm_autobridge"))

from src.io.zoho_client import ZohoClient
from src.processors.order_generator import OrderGenerator


def main():
    load_dotenv(Path(REPO_ROOT) / ".env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=int, default=datetime.now().month)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()

    print("Connecting to Zoho CRM...")
    zoho = ZohoClient(
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL"),
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
        api_domain=os.getenv("ZOHO_API_DOMAIN"),
    )

    print("Fetching properties (bulk read job — may take a few seconds)...")
    csv_bytes = zoho.get_properties()
    print(f"Received {len(csv_bytes):,} bytes of CSV data.")

    print(f"\nGenerating orders for {args.month}/{args.year}...")
    generator = OrderGenerator()
    test_run_id = f"livetest-{args.year}-{args.month:02d}"
    result = generator.generate(csv_bytes, month=args.month, year=args.year, run_id=test_run_id)

    total_orders = (
        len(result.service_orders)
        + len(result.drain_orders)
        + len(result.fill_orders)
        + len(result.manual_orders)
    )

    print("\n" + "=" * 60)
    print(f"  LIVE TEST RESULTS — {args.month}/{args.year}")
    print("=" * 60)
    print(f"  Total properties processed : {result.total_properties}")
    print(f"  Successful                 : {result.successful_properties}")
    print(f"  Failed                     : {result.failed_properties}")
    print(f"  Total orders generated     : {total_orders}")
    print(f"    Standard / Weekly        : {len(result.service_orders)}")
    print(f"    Drain                    : {len(result.drain_orders)}")
    print(f"    Fill                     : {len(result.fill_orders)}")
    print(f"    Manual schedule          : {len(result.manual_orders)}")
    print("=" * 60)

    if result.errors:
        print(f"\nERRORS ({len(result.errors)}):")
        for e in result.errors:
            name = e.get("Property Name", "?")
            reason = e.get("Error Reason", "?")
            print(f"  • {name} — {reason}")

    if result.manual_orders:
        print(f"\nMANUAL SCHEDULE ({len(result.manual_orders)}):")
        for o in result.manual_orders:
            print(f"  • {o.name}")


if __name__ == "__main__":
    main()
