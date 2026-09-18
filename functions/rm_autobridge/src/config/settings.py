"""Configuration management for RouteManager."""

from pathlib import Path
from typing import Dict, Any, List
import yaml


class Config:
    """Configuration loader and manager."""

    def __init__(self, config_dir: Path = None):
        """Initialize configuration.

        Args:
            config_dir: Path to configuration directory. Defaults to project config/ dir.
        """
        if config_dir is None:
            # Assume we're in src/config, go up two levels to find config/
            config_dir = Path(__file__).parent.parent.parent / "config"

        self.config_dir = Path(config_dir)
        self._membership_tiers: Dict[str, List[str]] = {}
        self._service_rules: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        """Load all configuration files."""
        self._load_membership_tiers()
        self._load_service_rules()

    def _load_membership_tiers(self):
        """Load membership tier definitions from YAML."""
        config_file = self.config_dir / "membership_tiers.yaml"
        if not config_file.exists():
            raise FileNotFoundError(f"Membership tiers config not found: {config_file}")

        with open(config_file, "r") as f:
            self._membership_tiers = yaml.safe_load(f)

    def _load_service_rules(self):
        """Load service rules from YAML."""
        config_file = self.config_dir / "service_rules.yaml"
        if not config_file.exists():
            raise FileNotFoundError(f"Service rules config not found: {config_file}")

        with open(config_file, "r") as f:
            self._service_rules = yaml.safe_load(f)

    def get_membership_category(self, membership_type: str) -> str:
        """Get the frequency category for a membership type.

        Args:
            membership_type: The membership type name from CRM

        Returns:
            Frequency category (annual, monthly, weekly, etc.)

        Raises:
            ValueError: If membership type is not found in configuration
        """
        for category, membership_list in self._membership_tiers.items():
            if category.endswith("_groups"):
                # Handle grouped memberships (like quarterly_drain_groups)
                for group_num, members in membership_list.items():
                    if membership_type in members:
                        return category.replace("_groups", "")
            elif isinstance(membership_list, list) and membership_type in membership_list:
                return category

        raise ValueError(f"Unknown membership type: {membership_type}")

    def get_service_time(self, service_type: str) -> int:
        """Get service time in minutes for a service type.

        Args:
            service_type: Type of service (standard, drain, fill)

        Returns:
            Service time in minutes
        """
        return self._service_rules["service_times"].get(service_type.lower(), 20)

    def get_recurrence_days(self, frequency: str) -> int:
        """Get number of days between recurrences.

        Args:
            frequency: Frequency type (weekly, bi_monthly, etc.)

        Returns:
            Number of days between visits
        """
        return self._service_rules["recurrence_patterns"].get(frequency, 7)

    def get_service_group_range(self, group: int) -> tuple[int, int]:
        """Get day range for a service group.

        Args:
            group: Service group number (1-4)

        Returns:
            Tuple of (start_day, end_day)
        """
        range_list = self._service_rules["service_group_weeks"].get(group, [1, 7])
        return (range_list[0], range_list[1])

    def get_dd_quarter(self, dd_service_group: int, frequency: str) -> int:
        """Get the quarter/period for D&D service.

        Args:
            dd_service_group: D&D service group number
            frequency: Frequency type (quarterly, semi_annual, monthly)

        Returns:
            Quarter/period number
        """
        dd_groups = self._service_rules["dd_service_groups"].get(frequency, {})
        return dd_groups.get(dd_service_group, 1)

    @property
    def membership_tiers(self) -> Dict[str, Any]:
        """Get all membership tier configurations."""
        return self._membership_tiers

    @property
    def service_rules(self) -> Dict[str, Any]:
        """Get all service rules."""
        return self._service_rules


# Global config instance
_config_instance = None


def get_config(config_dir: Path = None) -> Config:
    """Get or create global config instance.

    Args:
        config_dir: Optional config directory path

    Returns:
        Config instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(config_dir)
    return _config_instance
