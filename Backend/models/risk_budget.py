# risk_budget.py - RiskBudget Passive DTO
'use strict'

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskBudget:
    """
    Passive immutable DTO carrying the allowable monetary risk budget for a trade attempt.

    Implements Section 5.7 (Risk Manager) of the Architecture Reference.

    Fields:
      - capital_base (Decimal): Client capital snapshot used for risk sizing (Net Account Value)
      - max_loss_rupees (Decimal): Maximum allowable monetary loss (1% of capital_base)
    """
    capital_base: Decimal
    max_loss_rupees: Decimal
