"""
services/signal_engine/target_calculator.py

Isolated, stateless Target Calculator for Signal System V1.

This module is the single source of truth for computing targets on an accepted signal.
It has zero dependencies on the webhook router, validator, repository, or any ORM model.
The rest of the application calls only:

    targets = calculate_targets(action, entry, stoploss)

The internal algorithm is hidden behind this interface.
To replace the algorithm in the future, modify only this file.

V1 Algorithm — Risk-Based Symmetric Multipliers
------------------------------------------------
Risk  = abs(entry - stoploss)

BUY:
    T1 = entry + (1 × Risk)   → 1:1 risk-reward
    T2 = entry + (2 × Risk)   → 1:2 risk-reward
    T3 = entry + (3 × Risk)   → 1:3 risk-reward

SELL:
    T1 = entry - (1 × Risk)   → 1:1 risk-reward
    T2 = entry - (2 × Risk)   → 1:2 risk-reward
    T3 = entry - (3 × Risk)   → 1:3 risk-reward

Properties:
    - Fully deterministic: same inputs always produce identical outputs.
    - No randomness, no market-data dependency, no external calls.
    - Reproducible for audit trails.
    - Precision: results are rounded to 2 decimal places (standard tick precision).
"""

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalTargets:
    """
    Immutable result of a target calculation.

    Attributes:
        t1: Target 1 — 1:1 risk-reward level.
        t2: Target 2 — 1:2 risk-reward level.
        t3: Target 3 — 1:3 risk-reward level.
    """
    t1: float
    t2: float
    t3: float


def calculate_targets(action: str, entry: float, stoploss: float) -> SignalTargets:
    """
    Compute T1, T2, T3 for an accepted signal using the V1 risk-based algorithm.

    Args:
        action:   Signal direction — must be "BUY" or "SELL" (case-insensitive).
        entry:    Entry price level.
        stoploss: Stop-loss price level.

    Returns:
        SignalTargets: An immutable dataclass containing t1, t2, t3.

    Raises:
        ValueError: If action is not BUY or SELL, or if entry equals stoploss
                    (zero-risk signals cannot produce meaningful targets).
    """
    action_upper = action.strip().upper()

    if action_upper not in ("BUY", "SELL"):
        raise ValueError(
            f"Target calculation failed: action must be 'BUY' or 'SELL', got '{action}'."
        )

    risk = abs(entry - stoploss)

    if risk == 0:
        raise ValueError(
            f"Target calculation failed: entry ({entry}) equals stoploss ({stoploss}). "
            "Zero-risk signals cannot produce meaningful targets."
        )

    if action_upper == "BUY":
        t1 = round(entry + (1 * risk), 2)
        t2 = round(entry + (2 * risk), 2)
        t3 = round(entry + (3 * risk), 2)
    else:  # SELL
        t1 = round(entry - (1 * risk), 2)
        t2 = round(entry - (2 * risk), 2)
        t3 = round(entry - (3 * risk), 2)

    targets = SignalTargets(t1=t1, t2=t2, t3=t3)

    logger.debug(
        f"Targets calculated: action={action_upper} entry={entry} sl={stoploss} "
        f"risk={risk} T1={t1} T2={t2} T3={t3}"
    )

    return targets
