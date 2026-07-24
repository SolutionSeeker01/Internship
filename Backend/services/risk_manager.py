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
    
    Implements Section 5.7 (Risk Manager) of the Architecture Reference v1.3.
    
    Responsibilities:
      - Reads ExecutionContext.funds.available_cash
      - Verifies available_cash > 0
      - Calculates RiskBudget.max_loss_rupees = available_cash * 0.01 (1%) via Decimal
      - Returns RiskBudget DTO on success
      - Returns ExecutionResult(outcome="RISK_REJECTED", fail_reason="INSUFFICIENT_FUNDS") if not solvent
      
    Constraints:
      - NO quantity calculation (owned by Quantity Calculator - Stage 4)
      - NO margin requirement check (owned by Order Builder - Stage 5 & Broker RMS - Stage 6)
      - Pure deterministic evaluation using exact Decimal arithmetic
    """
    # Read available_cash from ExecutionContext.funds
    available_cash = context.funds.available_cash if context.funds else Decimal("0")
    
    # Solvency Check: available_cash > 0
    if available_cash <= Decimal("0"):
        return create_rejection_result(
            context,
            outcome="RISK_REJECTED",
            fail_reason="INSUFFICIENT_FUNDS",
            fail_category="PERMANENT"
        )

    # 1% Risk Budget calculation via Decimal
    max_loss_rupees = (available_cash * Decimal("0.01")).quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)

    return RiskBudget(
        available_cash=available_cash,
        max_loss_rupees=max_loss_rupees
    )
