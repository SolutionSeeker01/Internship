# trade_engine.py - Core Orchestrator for Execution Pipeline
'use strict'

from typing import Dict, Any, Optional, Callable
from utils.logger import get_logger
from dev_tools.drm import emit_event

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
        execution_writer: Optional[Callable[[Any, Any], Any]] = None,
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
        order_spec = None

        try:
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

            from dev_tools.drm import global_event_bus, RuntimeEvent

            # Check if Context Builder rejected (e.g. session invalid or fetch error)
            if is_rejection(context):
                execution_result = context
                emit_event(
                    event_type="RUNTIME_VALIDATION_FAILED",
                    component="TRADE_ENGINE",
                    execution_target_id=target_id,
                    severity="ERROR",
                    payload={"fail_reason": getattr(context, "fail_reason", "CONTEXT_BUILD_FAILED")}
                )
            else:
                # Extract signal from context if not passed explicitly
                effective_signal = signal_data or (getattr(context, "signal", None) if context else None)
                symbol = effective_signal.get("symbol") if isinstance(effective_signal, dict) else getattr(effective_signal, "symbol", "")
                action = effective_signal.get("action") if isinstance(effective_signal, dict) else getattr(effective_signal, "action", "")

                emit_event(
                    event_type="EXECUTION_STARTED",
                    component="TRADE_ENGINE",
                    execution_target_id=target_id,
                    payload={"symbol": symbol, "action": action}
                )

                # 2. Runtime Validator
                if not execution_result and self._runtime_validator and context:
                    logger.debug(f"Trade Engine [Stage 2]: Running Runtime Validator for target ID {target_id}...")
                    val_result = self._runtime_validator(context)
                    if is_rejection(val_result):
                        logger.warning(f"Trade Engine [Stage 2]: Runtime Validator rejected target ID {target_id}.")
                        execution_result = val_result
                        emit_event(
                            event_type="RUNTIME_VALIDATION_FAILED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            severity="ERROR",
                            payload={"fail_reason": getattr(val_result, "fail_reason", "RUNTIME_VALIDATION_FAILED")}
                        )
                    else:
                        emit_event(
                            event_type="RUNTIME_VALIDATION_PASSED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            payload={"symbol": symbol}
                        )

                # 3. Risk Manager
                risk_budget = None
                if not execution_result and self._risk_manager and context:
                    logger.debug(f"Trade Engine [Stage 3]: Running Risk Manager for target ID {target_id}...")
                    risk_res = self._risk_manager(context)
                    if is_rejection(risk_res):
                        logger.warning(f"Trade Engine [Stage 3]: Risk Manager rejected target ID {target_id}.")
                        execution_result = risk_res
                        emit_event(
                            event_type="RISK_CHECK_FAILED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            severity="ERROR",
                            payload={"fail_reason": getattr(risk_res, "fail_reason", "RISK_REJECTED")}
                        )
                    else:
                        risk_budget = risk_res
                        emit_event(
                            event_type="RISK_CHECK_PASSED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            payload={
                                "capital_base": float(getattr(risk_budget, "capital_base", 0)),
                                "net_value": float(getattr(getattr(context, "funds", None), "net_value", 0)),
                                "available_cash": float(getattr(getattr(context, "funds", None), "available_cash", 0)),
                                "max_risk": float(getattr(risk_budget, "max_loss_rupees", 0))
                            }
                        )

                # 4. Quantity Calculator
                order_qty = None
                if not execution_result and self._quantity_calculator and risk_budget:
                    logger.debug(f"Trade Engine [Stage 4]: Running Quantity Calculator for target ID {target_id}...")
                    qty_res = self._quantity_calculator(risk_budget, effective_signal)
                    if is_rejection(qty_res):
                        logger.warning(f"Trade Engine [Stage 4]: Quantity Calculator rejected target ID {target_id}.")
                        execution_result = qty_res
                        emit_event(
                            event_type="QUANTITY_CALC_FAILED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            severity="ERROR",
                            payload={"fail_reason": getattr(qty_res, "fail_reason", "QUANTITY_BELOW_MINIMUM")}
                        )
                    else:
                        order_qty = qty_res
                        emit_event(
                            event_type="QUANTITY_CALCULATED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            payload={"quantity": getattr(order_qty, "quantity", 0)}
                        )

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
                        emit_event(
                            event_type="ORDER_SPEC_CREATED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            payload={"symbol": getattr(order_spec, "symbol", ""), "quantity": getattr(order_spec, "quantity", 0), "price": float(getattr(order_spec, "price", 0))}
                        )

                # 6. Broker Dispatcher
                if not execution_result and self._broker_dispatcher and order_spec:
                    logger.debug(f"Trade Engine [Stage 6]: Submitting order via Broker Dispatcher for target ID {target_id}...")
                    execution_result = self._broker_dispatcher(order_spec, context)
                    broker_order_id = getattr(execution_result, "broker_order_id", None)
                    if is_rejection(execution_result):
                        emit_event(
                            event_type="ENTRY_REJECTED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            severity="ERROR",
                            payload={"fail_reason": getattr(execution_result, "fail_reason", "BROKER_FAILED")}
                        )
                    else:
                        emit_event(
                            event_type="ENTRY_SUBMITTED",
                            component="TRADE_ENGINE",
                            execution_target_id=target_id,
                            broker_order_id=broker_order_id,
                            payload={}
                        )
        except Exception as stage_err:
            logger.error(
                f"Trade Engine caught unhandled exception during stage execution for target ID {target_id}: {stage_err}",
                exc_info=True
            )
            from models.execution_result import ExecutionResult
            signal_id = target_data.get("signal_id", 0) if isinstance(target_data, dict) else 0
            client_id = target_data.get("client_id", 0) if isinstance(target_data, dict) else 0
            execution_result = ExecutionResult(
                execution_target_id=target_id,
                signal_id=signal_id,
                client_id=client_id,
                outcome="BROKER_FAILED",
                fail_reason=f"INTERNAL_STAGE_ERROR: {str(stage_err)}",
                fail_category="PERMANENT"
            )

        # 7. Execution Writer (Unified persistence entry point for all outcomes per Section 4 & 5.13)
        if self._execution_writer and execution_result:
            logger.debug(f"Trade Engine [Stage 7]: Persisting execution result via Execution Writer for target ID {target_id}...")
            written_result = self._execution_writer(execution_result, order_spec)
            emit_event(
                event_type="EXECUTION_RECORDED",
                component="TRADE_ENGINE",
                execution_target_id=target_id,
                payload={"outcome": getattr(execution_result, "outcome", "")}
            )
            return written_result

        logger.info(f"Trade Engine completed orchestration for target ID {target_id}.")
        return execution_result
