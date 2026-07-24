# Backend/services/order_state_machine.py
"""
Order State Machine - Lifecycle Transition Validation Module

Implements Section 6 (State Machine) of ARCHITECTURE_REFERENCE.md.
Responsible exclusively for validating legal state transitions for Order entities.
"""

from typing import Set, Dict, Tuple
from exceptions import PlatformException
from utils.logger import get_logger

logger = get_logger(__name__)


class IllegalStateTransitionError(PlatformException):
    """Raised when an illegal order state transition is attempted."""
    status_code: int = 400
    error_code: str = "ILLEGAL_STATE_TRANSITION"
    default_message: str = "Illegal order state transition attempted."



# Section 6 Supported States
SUPPORTED_ORDER_STATES: Set[str] = {
    "PLACED",
    "SUBMITTED",
    "OPEN",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED_BY_EXCHANGE",
    "FAILED"
}

# Section 6 Terminal States (no outgoing transitions allowed)
TERMINAL_ORDER_STATES: Set[str] = {
    "FILLED",
    "CANCELLED",
    "REJECTED_BY_EXCHANGE",
    "FAILED"
}

# Section 6 Allowed Transition Map
ALLOWED_ORDER_TRANSITIONS: Dict[str, Set[str]] = {
    "PLACED": {"SUBMITTED", "FAILED"},
    "SUBMITTED": {"OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED_BY_EXCHANGE"},
    "OPEN": {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED_BY_EXCHANGE"},
    "PARTIALLY_FILLED": {"FILLED", "CANCELLED"},
    "FILLED": set(),
    "CANCELLED": set(),
    "REJECTED_BY_EXCHANGE": set(),
    "FAILED": set()
}


def validate_order_state_transition(current_status: str, target_status: str) -> bool:
    """
    Validates whether a requested order state transition (current_status -> target_status)
    is legal according to Section 6 of ARCHITECTURE_REFERENCE.md.

    Args:
        current_status (str): The current status of the order.
        target_status (str): The requested target status.

    Returns:
        bool: True if the transition is legal.

    Raises:
        IllegalStateTransitionError: If the transition is illegal or invalid.
    """
    if current_status not in SUPPORTED_ORDER_STATES:
        logger.error(f"Invalid current status '{current_status}'. Allowed states: {SUPPORTED_ORDER_STATES}")
        raise IllegalStateTransitionError(f"Invalid current order status: '{current_status}'")

    if target_status not in SUPPORTED_ORDER_STATES:
        logger.error(f"Invalid target status '{target_status}'. Allowed states: {SUPPORTED_ORDER_STATES}")
        raise IllegalStateTransitionError(f"Invalid target order status: '{target_status}'")

    if current_status in TERMINAL_ORDER_STATES:
        logger.warning(f"Illegal transition from terminal state '{current_status}' to '{target_status}'")
        raise IllegalStateTransitionError(f"Cannot transition from terminal state '{current_status}' to '{target_status}'")

    allowed_targets = ALLOWED_ORDER_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        logger.warning(f"Illegal state transition attempted: '{current_status}' -> '{target_status}'")
        raise IllegalStateTransitionError(
            f"Illegal state transition from '{current_status}' to '{target_status}'. "
            f"Allowed transitions from '{current_status}': {sorted(list(allowed_targets))}"
        )

    logger.debug(f"Valid order state transition: '{current_status}' -> '{target_status}'")
    return True


def is_valid_order_state_transition(current_status: str, target_status: str) -> bool:
    """
    Pure boolean query function to check if a transition is legal without raising an exception.

    Args:
        current_status (str): Current status string.
        target_status (str): Target status string.

    Returns:
        bool: True if legal, False otherwise.
    """
    try:
        return validate_order_state_transition(current_status, target_status)
    except IllegalStateTransitionError:
        return False
