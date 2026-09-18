from pathlib import Path
from typing import List
from dataclasses import dataclass

from ..models import Property, OrderInput, ServiceType
from ..membership import MembershipFactory
from ..io import CSVReader, CSVWriter
from ..scheduling import BusinessDayCalendar, GlobalScheduler


@dataclass
class GenerationResult:
    service_orders: List[OrderInput]
    drain_orders: List[OrderInput]
    fill_orders: List[OrderInput]
    manual_orders: List[dict]
    errors: List[dict]
    total_properties: int
    successful_properties: int
    failed_properties: int


class OrderGenerator:

    def __init__(self):
        self.csv_reader = CSVReader()
        self.csv_writer = CSVWriter()

    def generate(
        self,
        input_bytes: bytes,
        month: int,
        year: int,
        *,
        run_id: str,
    ) -> GenerationResult:
        """Generate service orders for a specific month.

        This method:
        1. Reads properties from CSV bytes
        2. Creates business day calendar and scheduler
        3. Generates full year of orders for each property with load balancing
        4. Filters to requested month
        5. Categorizes by service type
        6. Stamps run_id onto every generated order

        Args:
            input_bytes: CSV filelike object from ZohoCRM bulk read
            month: Target month (1-12)
            year: Target year
            run_id: Autobridge run identifier; written to every order's
                customFields["Autobridge Run"]. Required, non-empty.

        Returns:
            GenerationResult with categorized orders and statistics
        """
        if not run_id:
            raise ValueError("OrderGenerator.generate: run_id must be a non-empty string")

        properties, read_errors = self.csv_reader.read_properties(input_bytes)

        calendar = BusinessDayCalendar(
            year
        )  # Calandar only includes business days (non-weekend, non-holiday)
        scheduler = GlobalScheduler(calendar)

        all_orders = []
        generation_errors = []

        for prop in properties:
            try:
                year_orders = self._generate_property_orders(prop, year, scheduler)
                month_orders = self._filter_to_month(year_orders, month, year)

                all_orders.extend(month_orders)

            except Exception as e:
                generation_errors.append(
                    {
                        "Property Name": prop.property_name,
                        "Record Id": prop.record_id,
                        "Error Reason": f"Generation failed: {e!s}",
                    }
                )

        for order in all_orders:
            order.run_id = run_id

        # Combine all errors
        all_errors = read_errors + generation_errors

        # Categorize orders by type
        result = self._categorize_orders(all_orders, all_errors, len(properties) + len(read_errors))

        return result

    def _generate_property_orders(
        self, property: Property, year: int, scheduler: GlobalScheduler
    ) -> List[OrderInput]:
        """Generate all orders for a property for the entire year.

        Args:
            property: Property details
            year: Year to generate for
            scheduler: GlobalScheduler for business day scheduling and load balancing

        Returns:
            List of all service orders for the year
        """
        handler = MembershipFactory.create_handler(property.maintenance_membership)

        return handler.generate_orders(property, year, scheduler)

    def _filter_to_month(self, orders: List[OrderInput], month: int, year: int) -> List[OrderInput]:
        """Filter orders to only those in the requested month.

        Args:
            orders: List of all orders
            month: Target month (1-12)
            year: Target year

        Returns:
            Filtered list of orders
        """
        filtered = []

        for order in orders:
            # Check if order has eligibility date
            if order.eligibility_start is None:
                # Manual schedule - include regardless
                filtered.append(order)
            elif order.eligibility_start.month == month and order.eligibility_start.year == year:
                # Order is in target month
                filtered.append(order)

        return filtered

    def _categorize_orders(
        self, orders: List[OrderInput], errors: List[dict], total_count: int
    ) -> GenerationResult:
        """Categorize orders by service type.

        Args:
            orders: All service orders
            errors: List of error records
            total_count: Total number of properties processed

        Returns:
            GenerationResult with categorized orders
        """
        service_orders = []
        drain_orders = []
        fill_orders = []
        manual_orders = []
        order_identifiers = set()

        for order in orders:
            self._record_order_identifier(order, order_identifiers)

            if order.eligibility_start is None:  # When is order.eligibility_start None?
                manual_orders.append(order)
            elif order.service_type == ServiceType.STANDARD:
                service_orders.append(order)
            elif order.service_type == ServiceType.DRAIN:
                drain_orders.append(order)
            elif order.service_type == ServiceType.FILL:
                fill_orders.append(order)

        filtered_errors = self._filter_resolved_errors(errors, order_identifiers)

        return GenerationResult(
            service_orders=service_orders,
            drain_orders=drain_orders,
            fill_orders=fill_orders,
            manual_orders=manual_orders,
            errors=filtered_errors,
            total_properties=total_count,
            successful_properties=total_count - len(filtered_errors),
            failed_properties=len(filtered_errors),
        )

    @staticmethod
    def _record_order_identifier(order: OrderInput, identifiers: set):
        """Capture identifiers for properties that produced orders."""
        if order.zoho_id:
            identifiers.add(str(order.zoho_id))

        if order.name:
            property_name = order.name.split(":", 1)[0].strip()
            if property_name:
                identifiers.add(property_name)

    @staticmethod
    def _filter_resolved_errors(errors: List[dict], identifiers: set) -> List[dict]:
        # Remove error entries for properties that produced orders.
        filtered_errors = []

        for error in errors:
            error_identifier = error.get("Record Id") or error.get("Property Name")

            if error_identifier and str(error_identifier) in identifiers:
                continue

            filtered_errors.append(error)

        return filtered_errors

    def write_output(self, result: GenerationResult, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write service orders
        self.csv_writer.write_orders(result.service_orders, output_dir / "Service_Orders.csv")

        # Write drain orders
        self.csv_writer.write_orders(result.drain_orders, output_dir / "Drain_Orders.csv")

        # Write fill orders
        self.csv_writer.write_orders(result.fill_orders, output_dir / "Fill_Orders.csv")

        # Write manual schedule
        self.csv_writer.write_orders(result.manual_orders, output_dir / "Manual_Schedule.csv")

        # Write errors
        self.csv_writer.write_errors(result.errors, output_dir / "Errors.csv")
