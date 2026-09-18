"""CSV writer for service orders."""

import pandas as pd
from pathlib import Path
from typing import List
from ..models import OrderInput


class CSVWriter:
    """Writes service orders to CSV files."""

    @staticmethod
    def _default_headers():
        """Headers used for the empty-result case only.

        NOTE: these are the flat, human-readable columns from the original
        manual-CSV era. A non-empty write instead derives its columns from
        OrderInput.to_dict(), which is the nested WorkWave payload shape, so
        an empty backup file and a populated one do not share a header row.
        The backups are a diagnostic artifact rather than a consumed feed, so
        this is recorded rather than fixed; changing it alters output for a
        live pipeline.
        """
        return [
            "Name",
            "Contact Phone",
            "Service Street",
            "Service City",
            "Service State",
            "Service Zip",
            "Pickup Street",
            "Pickup City",
            "Pickup State",
            "Pickup Zip",
            "Service Type",
            "Notes",
            "Maintenance Frequency",
            "Eligibility",
            "Service Time",
            "Zoho ID",
            "Preferred Days",
        ]

    @staticmethod
    def write_orders(orders: List[OrderInput], output_path: Path, include_index: bool = False):
        """Write service orders to CSV file.

        Args:
            orders: List of OrderInput objects
            output_path: Path to output CSV file
            include_index: Whether to include row index
        """
        if not orders:
            # Create empty file with headers
            df = pd.DataFrame(columns=CSVWriter._default_headers())
        else:
            # Convert orders to dictionaries
            order_dicts = [order.to_dict() for order in orders]
            df = pd.DataFrame(order_dicts)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to CSV
        df.to_csv(output_path, index=include_index)

    @staticmethod
    def write_errors(errors: List[dict], output_path: Path):
        """Write error records to CSV file.

        Args:
            errors: List of error dictionaries
            output_path: Path to output CSV file
        """
        if not errors:
            # Create empty error file
            df = pd.DataFrame(columns=["Row Number", "Error Reason"])
        else:
            df = pd.DataFrame(errors)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to CSV
        df.to_csv(output_path, index=False)
