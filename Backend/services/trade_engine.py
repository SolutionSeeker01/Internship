# trade_engine.py - Core Orchestrator for Execution Pipeline
'use strict'

from typing import Dict, Any, Optional, Callable
from utils.logger import get_logger

logger = get_logger(__name__)


class TradeEngine:
    """
    Core orchestrator for the Trade Engine execution pipeline.
    
    Implements Section 5.4 (Trade Engine - Thin Coordinator Pattern) of the Architecture Reference.
    
    Responsibilities:
      - Receives claimed ExecutionTarget data dictionary from Execution Dispatcher
      - Orchestrates the execution pipeline sequence strictly as defined in Section 4:
          1. ExecutionContext Builder
          2. Runtime Validator
          3. Risk Manager
          4. Quantity Calculator
          5. Order Builder
          6. Broker Dispatcher
          7. Execution Writer
      - Returns ExecutionResult (passive DTO)
      
    Constraints:
      - Contains ZERO business logic (validation, risk checks, quantity math, payload building)
      - Receives stage dependencies via constructor injection (P2, P9)
      - Performs NO direct database writes (delegates to Execution Writer - P3)
      - Performs NO retries internally (retries handled by Broker Dispatcher - P8)
      - Operates in a 100% broker-agnostic manner (P4)
    """

    def __init__(
        self,
        context_builder: Optional[Callable[[Dict[str, Any]], Any]] = None,
        runtime_validator: Optional[Callable[[Any, Any], Any]] = None,
        risk_manager: Optional[Callable[[Any, Any], Any]] = None,
        quantity_calculator: Optional[Callable[[Any, Any], Any]] = None,
        order_builder: Optional[Callable[[Any, Any, Any, Any], Any]] = None,
        broker_dispatcher: Optional[Callable[[Any], Any]] = None,
        execution_writer: Optional[Callable[[Any], Any]] = None,
    ):
        """
        Constructor dependency injection for all pipeline stages.
        """
        self._context_builder = context_builder
        self._runtime_validator = runtime_validator
        self._risk_manager = risk_manager
        self._quantity_calculator = quantity_calculator
        self._order_builder = order_builder
        self._broker_dispatcher = broker_dispatcher
        self._execution_writer = execution_writer

    def execute(self, target_data: Dict[str, Any], signal_data: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """
        Orchestrates the sequential execution pipeline for a claimed target.
        
        Flow (Section 4):
          1. ExecutionContext Builder -> build context (or return RUNTIME_REJECTED ExecutionResult)
          2. Runtime Validator -> validate context (or return RUNTIME_REJECTED ExecutionResult)
          3. Risk Manager -> evaluate risk budget (or return RISK_REJECTED ExecutionResult)
          4. Quantity Calculator -> calculate order quantity (or return RISK_REJECTED ExecutionResult)
          5. Order Builder -> construct broker-agnostic OrderSpec
          6. Broker Dispatcher -> submit order & receive confirmation/failure
          7. Execution Writer -> persist result & write order record
          
        Args:
            target_data (Dict[str, Any]): Claimed execution target dictionary
            signal_data (Optional[Dict[str, Any]]): Optional pre-loaded signal data (or fetched via Context Builder)
            
        Returns:
            Optional[Any]: ExecutionResult returned from pipeline completion or stage rejection.
        """
        target_id = target_data.get("id")
        logger.info(f"Trade Engine starting pipeline orchestration for target ID {target_id}...")

        execution_result = None

        # 1. ExecutionContext Builder
        context = None
        if self._context_builder:
            logger.debug(f"Trade Engine [Stage 1]: Building ExecutionContext for target ID {target_id}...")
            context = self._context_builder(target_data)

        # Helper to check if a stage returned an ExecutionResult rejection DTO
        def is_rejection(res: Any) -> bool:
            return res is not None and getattr(res, "outcome", None) in (
                "RUNTIME_REJECTED", "RISK_REJECTED", "BROKER_FAILED", "INTERNAL_ERROR"
            )

        # Check if Context Builder rejected (e.g. session invalid or fetch error)
        if is_rejection(context):
            execution_result = context
        else:
            # Extract signal from context if not passed explicitly
            effective_signal = signal_data or (getattr(context, "signal", None) if context else None)

            # 2. Runtime Validator
            if not execution_result and self._runtime_validator and context:
                logger.debug(f"Trade Engine [Stage 2]: Running Runtime Validator for target ID {target_id}...")
                val_result = self._runtime_validator(context)
                if is_rejection(val_result):
                    logger.warning(f"Trade Engine [Stage 2]: Runtime Validator rejected target ID {target_id}.")
                    execution_result = val_result

            # 3. Risk Manager
            risk_budget = None
            if not execution_result and self._risk_manager and context:
                logger.debug(f"Trade Engine [Stage 3]: Running Risk Manager for target ID {target_id}...")
                risk_res = self._risk_manager(context)
                if is_rejection(risk_res):
                    logger.warning(f"Trade Engine [Stage 3]: Risk Manager rejected target ID {target_id}.")

                    execution_result = risk_res
                else:
                    risk_budget = risk_res

            # 4. Quantity Calculator
            order_qty = None
            if not execution_result and self._quantity_calculator and risk_budget:
                logger.debug(f"Trade Engine [Stage 4]: Running Quantity Calculator for target ID {target_id}...")
                qty_res = self._quantity_calculator(risk_budget, effective_signal)
                if is_rejection(qty_res):
                    logger.warning(f"Trade Engine [Stage 4]: Quantity Calculator rejected target ID {target_id}.")
                    execution_result = qty_res
                else:
                    order_qty = qty_res

            # 5. Order Builder
            order_spec = None
            if not execution_result and self._order_builder:
                logger.debug(f"Trade Engine [Stage 5]: Running Order Builder for target ID {target_id}...")
                capabilities = getattr(context, "capabilities", None) if context else None
                order_res = self._order_builder(effective_signal, order_qty, context, capabilities)
                if is_rejection(order_res):
                    logger.warning(f"Trade Engine [Stage 5]: Order Builder rejected target ID {target_id}.")
                    execution_result = order_res
                else:
                    order_spec = order_res

            # 6. Broker Dispatcher
            if not execution_result and self._broker_dispatcher and order_spec:

                logger.debug(f"Trade Engine [Stage 6]: Submitting order via Broker Dispatcher for target ID {target_id}...")
                execution_result = self._broker_dispatcher(order_spec)

        # 7. Execution Writer (Unified persistence entry point for all outcomes per Section 4 & 5.13)
        if self._execution_writer and execution_result:
            logger.debug(f"Trade Engine [Stage 7]: Persisting execution result via Execution Writer for target ID {target_id}...")
            return self._execution_writer(execution_result)

        logger.info(f"Trade Engine completed orchestration for target ID {target_id}.")
        return execution_result
