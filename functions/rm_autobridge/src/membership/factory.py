"""Factory for creating membership handlers."""

from typing import Dict, Type
from .base import MembershipHandler
from ..config import get_config
from ..models import Frequency


class MembershipFactory:
    """Factory for creating appropriate membership handlers."""

    # Handler registry - to be populated with concrete handlers
    _handlers: Dict[Frequency, Type[MembershipHandler]] = {}

    @classmethod
    def register_handler(cls, frequency: Frequency, handler_class: Type[MembershipHandler]):
        """Register a handler for a frequency type.

        Args:
            frequency: Frequency enum value
            handler_class: Handler class to register
        """
        cls._handlers[frequency] = handler_class

    @classmethod
    def create_handler(cls, membership_type: str) -> MembershipHandler:
        """Create appropriate handler for a membership type.

        Args:
            membership_type: Membership type name from CRM

        Returns:
            Appropriate MembershipHandler instance

        Raises:
            ValueError: If membership type is unknown or no handler registered
        """
        config = get_config()

        # Get frequency category from config
        category = config.get_membership_category(membership_type)

        # Convert category string to Frequency enum
        try:
            frequency = Frequency(category)
        except ValueError:
            raise ValueError(f"Unknown frequency category: {category}")

        # Get handler class
        handler_class = cls._handlers.get(frequency)
        if not handler_class:
            raise ValueError(f"No handler registered for frequency: {frequency}")

        return handler_class()

    @classmethod
    def list_supported_frequencies(cls) -> list[Frequency]:
        """Get list of supported frequencies.

        Returns:
            List of Frequency enums with registered handlers
        """
        return list(cls._handlers.keys())
