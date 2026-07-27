# risk_manager.py - Risk Manager Service
'use strict'

from decimal import Decimal, ROUND_FLOOR
from typing import Union

from models.execution_context import ExecutionContext
from models.execution_result import ExecutionResult, create_rejection_result
from models.risk_budget import RiskBudget


def evaluate_risk(context: ExecutionContext) -> Union[RiskBudget, ExecutionResult]:
    """
    Evaluates client account solvency and determines the maximum allowable risk budget for a trade.

    Implements Section 5.7 (Risk Manager) of the Architecture Reference.

    Responsibilities:
      - Reads ExecutionContext.funds.net_value (Net Account Value / Equity)
      - Verifies net_value > 0
      - Calculates RiskBudget.max_loss_rupees = net_value * 0.01 (1% of Net Account Value) via Decimal
      - Returns RiskBudget DTO on success
      - Returns ExecutionResult(outcome="RISK_REJECTED", fail_reason="INSUFFICIENT_FUNDS") if net_value <= 0

    Constraints:
      - Sizing rule: Risk Budget = 1% of Net Account Value (net_value)
      - NO quantity calculation (owned by Quantity Calculator - Stage 4)
      - Pure deterministic evaluation using exact Decimal arithmetic
    """
    # Read net_value (Net Account Value) from ExecutionContext.funds
    net_value = context.funds.net_value if context.funds else Decimal("0")

    # Solvency Check: net_value > 0
    if net_value <= Decimal("0"):
        return create_rejection_result(
            context,
            outcome="RISK_REJECTED",
            fail_reason="INSUFFICIENT_FUNDS",
            fail_category="PERMANENT"
        )

    # 1% Risk Budget calculation via Decimal based on Net Account Value (capital_base)
    max_loss_rupees = (net_value * Decimal("0.01")).quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)

    return RiskBudget(
        capital_base=net_value,
        max_loss_rupees=max_loss_rupees
    )
