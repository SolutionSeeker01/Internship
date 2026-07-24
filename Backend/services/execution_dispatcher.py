# execution_dispatcher.py - Execution Dispatcher Orchestrator
'use strict'

import asyncio
from typing import List, Dict, Any, Optional, Callable
from database.execution_target_repository import (
    claim_ready_execution_target,
    fetch_ready_target_ids
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionDispatcher:
    """
    Execution Dispatcher orchestrates target delivery from eligibility engine/polling
    to the Trade Engine.
    
    Implements Section 5.3 (Execution Dispatcher) of the Architecture Reference.
    
    Responsibilities:
      - Accepts or polls READY target IDs
      - Atomically claims execution targets via conditional UPDATE (status -> EXECUTING)
      - Enforces concurrency safety (prevents multiple workers from claiming same target)
      - Invokes Trade Engine with claimed target data
      
    Constraints:
      - Does NOT perform trading decisions, rules validation, margin calculation, or payload building
      - Does NOT write execution outcomes or perform retries
    """

    def __init__(self, trade_engine_invoker: Optional[Callable[[Dict[str, Any]], Any]] = None):
        """
        Initializes the Execution Dispatcher with an optional Trade Engine invoker callback.
        
        Args:
            trade_engine_invoker (Callable): Callback function/interface that takes claimed 
                                             target data dict and hands it off to Trade Engine.
        """
        self._notification_queue: asyncio.Queue[int] = asyncio.Queue()
        self._trade_engine_invoker = trade_engine_invoker

    def register_trade_engine_invoker(self, invoker: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Registers or updates the Trade Engine invoker callback.
        """
        self._trade_engine_invoker = invoker

    async def notify_target_ready(self, target_id: int) -> None:
        """
        In-process fast-path notification channel.
        
        Called by Eligibility Engine immediately after creating a READY target.
        Pushes target ID to the internal async queue for immediate processing.
        """
        await self._notification_queue.put(target_id)
        logger.debug(f"Pushed target ID {target_id} to in-process notification queue.")

    def notify_target_ready_sync(self, target_id: int) -> None:
        """
        Synchronous wrapper for in-process notification channel.
        Allows synchronous callers (e.g. background threads or eligibility engine)
        to enqueue target IDs without an active event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.notify_target_ready(target_id))
        except RuntimeError:
            # Fallback if no loop is running in current thread: target will be picked up by DB poller
            logger.debug(f"No running event loop for target ID {target_id}; poller fallback will process it.")

    def process_target(self, target_id: int) -> Optional[Any]:
        """
        Orchestrates atomic claim and Trade Engine invocation for a single target ID.
        
        Flow:
          1. Atomically claim target (conditional UPDATE status='READY' -> status='EXECUTING')
          2. If claim fails (0 rows updated / already claimed): return None
          3. If claim succeeds: invoke Trade Engine callback with claimed target data
          
        Implements Section 5.3, Section 7 (Layer 2 Idempotency), and Section 8 (Transaction Boundaries).
        
        Args:
            target_id (int): Primary key of the execution target.
            
        Returns:
            Optional[Any]: Result of trade_engine_invoker if claimed & invoked, or None if claim failed.
        """
        logger.info(f"Execution Dispatcher processing target ID {target_id}...")
        
        # 1. Atomic claim via conditional UPDATE (commit immediately in repo)
        claimed_target = claim_ready_execution_target(target_id)
        if not claimed_target:
            logger.warning(f"Target ID {target_id} could not be claimed (already claimed or not READY). Skipping.")
            return None

        # 2. Invoke Trade Engine if invoker registered
        if self._trade_engine_invoker:
            logger.info(f"Invoking Trade Engine for claimed target ID {target_id}...")
            return self._trade_engine_invoker(claimed_target)
        else:
            logger.warning(f"Target ID {target_id} claimed, but no Trade Engine invoker registered.")
            return claimed_target

    def poll_and_process_ready_targets(self, limit: int = 10) -> List[Any]:
        """
        Fallback path / Polling worker: Polls PostgreSQL for READY targets and processes them.
        
        Implements Section 5.3 DB polling fallback path using FOR UPDATE SKIP LOCKED queries.
        
        Args:
            limit (int): Maximum number of targets to fetch per poll cycle.
            
        Returns:
            List[Any]: List of trade engine invocation results for successfully claimed targets.
        """
        ready_ids = fetch_ready_target_ids(limit=limit)
        if not ready_ids:
            return []

        logger.info(f"Poller discovered {len(ready_ids)} READY target IDs: {ready_ids}")
        results = []
        for tid in ready_ids:
            res = self.process_target(tid)
            if res is not None:
                results.append(res)
        return results
