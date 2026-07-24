# risk_budget.py - RiskBudget Passive DTO
'use strict'

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskBudget:
    """
    Passive immutable DTO carrying the allowable monetary risk budget for a trade attempt.
    
    Implements Section 5.7 (Risk Manager) of the Architecture Reference v1.3.
    
    Fields:
      - available_cash (Decimal): Client available trading capital snapshot
      - max_loss_rupees (Decimal): Maximum allowable monetary loss (1% of available_cash)
    """
    available_cash: Decimal
    max_loss_rupees: Decimal
