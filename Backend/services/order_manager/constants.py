# Backend/services/order_manager/constants.py
"""
Order Manager Constants & Position State Definitions

Phase 1 Foundation Module defining Position State strings and derived Protection Modes.
"""


class PositionState:
    """Canonical Position Lifecycle States."""
    PROTECTED = "PROTECTED"
    BROKER_PROTECTED = "BROKER_PROTECTED"
    SL_CANCEL_PENDING = "SL_CANCEL_PENDING"
    SOFTWARE_TRAILING_ACTIVE = "SOFTWARE_TRAILING_ACTIVE"
    EXIT_PENDING = "EXIT_PENDING"
    TARGET_ORDER_PENDING = "TARGET_ORDER_PENDING"

    PARTIALLY_PROTECTED = "PARTIALLY_PROTECTED"
    CLOSED = "CLOSED"


class ProtectionMode:
    """Pure derived Protection Modes (Derived strictly from PositionState)."""
    BROKER = "BROKER"
    TRANSITIONING = "TRANSITIONING"
    SOFTWARE = "SOFTWARE"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"
