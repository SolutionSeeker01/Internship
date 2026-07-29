# execution_target_repository.py - Database Repository for Signal Execution Targets
'use strict'

from sqlalchemy.sql import text
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional

from database.db import SessionLocal
from exceptions import DatabaseException
from utils.logger import get_logger

logger = get_logger(__name__)


def get_eligible_candidates(strategy_id: int) -> List[Dict[str, Any]]:
    """
    Retrieves all clients who have actively subscribed to the given strategy,
    joined with their broker connection profile attributes.
    
    Only returns candidates if the strategy itself is globally active (is_active = TRUE)
    and the client's preference record is active (is_active = TRUE).
    Does not apply any broker-level filtering (e.g. connectivity, session validity)
    as those evaluations belong strictly to the service layer.
    
    Args:
        strategy_id (int): Catalog primary key for the target strategy.
        
    Returns:
        List[Dict[str, Any]]: Normalized candidate dictionaries containing:
            - client_id (int)
            - broker_exists (bool)
            - is_connected (bool)
            - access_token (str or None)
    """
    session = SessionLocal()
    try:
        sql = """
            SELECT 
                csp.client_id,
                (ba.id IS NOT NULL) AS broker_exists,
                (ba.access_token IS NOT NULL AND TRIM(ba.access_token) != '') AS is_connected,
                TRIM(ba.access_token) AS access_token
            FROM client_strategy_preferences csp
            INNER JOIN strategies s
              ON s.id = csp.strategy_id
            LEFT OUTER JOIN broker_accounts ba 
              ON ba.user_id = csp.client_id
            WHERE csp.strategy_id = :strategy_id
              AND csp.is_active = TRUE
              AND s.is_active = TRUE;
        """
        result = session.execute(text(sql), {"strategy_id": strategy_id})
        rows = result.fetchall()
        
        candidates = []
        for row in rows:
            token = row[3].strip() if row[3] else None
            candidates.append({
                "client_id": row[0],
                "broker_exists": bool(row[1]),
                "is_connected": bool(token),
                "access_token": token
            })
        return candidates
    except SQLAlchemyError as e:
        logger.error(f"Failed to retrieve eligible candidates for strategy ID {strategy_id}: {e}")
        raise DatabaseException(
            f"Failed to retrieve eligible candidates for strategy ID {strategy_id} from database.", 
            original_exception=e
        )
    finally:
        session.close()


def bulk_insert_execution_targets(targets: List[Dict[str, Any]]) -> int:
    """
    Saves multiple generated execution targets in a single database round-trip.
    Uses ON CONFLICT DO NOTHING against (signal_id, client_id) to ensure idempotency.
    
    Args:
        targets (List[Dict[str, Any]]): List of target dictionaries. Each dict must contain:
            - signal_id (int)
            - client_id (int)
            - status (str)
            - skip_reason (str or None)
            
    Returns:
        int: Number of rows successfully inserted.
    """
    if not targets:
        return 0

    session = SessionLocal()
    try:
        values_clause_parts = []
        bind_params = {}
        
        for i, target in enumerate(targets):
            val_sig = f"sig_{i}"
            val_cli = f"cli_{i}"
            val_sts = f"sts_{i}"
            val_skp = f"skp_{i}"
            
            values_clause_parts.append(f"(:{val_sig}, :{val_cli}, :{val_sts}, :{val_skp})")
            
            bind_params[val_sig] = target["signal_id"]
            bind_params[val_cli] = target["client_id"]
            bind_params[val_sts] = target["status"]
            bind_params[val_skp] = target.get("skip_reason")

        sql = f"""
            INSERT INTO signal_execution_targets (
                signal_id, 
                client_id, 
                status, 
                skip_reason
            )
            VALUES {", ".join(values_clause_parts)}
            ON CONFLICT (signal_id, client_id) DO NOTHING;
        """
        
        result = session.execute(text(sql), bind_params)
        inserted_count = result.rowcount
        session.commit()
        
        logger.info(f"Bulk inserted {inserted_count} execution target records (total processed: {len(targets)}).")
        return inserted_count
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed bulk insertion of execution targets: {e}")
        raise DatabaseException("Failed to persist bulk execution targets into database.", original_exception=e)
    finally:
        session.close()


def claim_ready_execution_target(target_id: int) -> Optional[Dict[str, Any]]:
    """
    Atomically claims a READY execution target for processing by updating its status
    to EXECUTING and setting claimed_at timestamp.
    
    Implements Section 8 (Transaction Boundaries & Atomic Claim) and Section 7 (Layer 2 Idempotency)
    using conditional UPDATE with immediate commit. Returns target data if successfully claimed,
    or None if another worker already claimed or processed the target.
    
    Args:
        target_id (int): Primary key of the execution target to claim.
        
    Returns:
        Optional[Dict[str, Any]]: Dictionary containing claimed target fields if successful,
                                 or None if claim failed (0 rows updated).
    """
    session = SessionLocal()
    try:
        sql = """
            UPDATE signal_execution_targets
            SET status = 'EXECUTING',
                claimed_at = NOW()
            WHERE id = :target_id 
              AND status = 'READY'
            RETURNING id, signal_id, client_id, status, claimed_at;
        """
        result = session.execute(text(sql), {"target_id": target_id})
        row = result.fetchone()
        session.commit()
        
        if not row:
            logger.info(f"Atomic claim failed for target ID {target_id}: Target is not in READY status or already claimed.")
            return None
            
        logger.info(f"Successfully claimed target ID {target_id} (status: EXECUTING, signal_id: {row[1]}, client_id: {row[2]}).")
        return {
            "id": row[0],
            "signal_id": row[1],
            "client_id": row[2],
            "status": row[3],
            "claimed_at": row[4]
        }
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error during atomic claim for target ID {target_id}: {e}")
        raise DatabaseException(f"Failed atomic claim for execution target ID {target_id}.", original_exception=e)
    finally:
        session.close()


def fetch_ready_target_ids(limit: int = 10) -> List[int]:
    """
    Polls the database for READY execution target IDs using FOR UPDATE SKIP LOCKED,
    and atomically transitions claimed targets to EXECUTING within the locked transaction
    to preserve row lock intentions across multi-worker deployments.
    
    Args:
        limit (int): Maximum number of READY target IDs to fetch.
        
    Returns:
        List[int]: List of target IDs successfully fetched and claimed.
    """
    session = SessionLocal()
    try:
        sql = """
            WITH target_batch AS (
                SELECT id 
                FROM signal_execution_targets
                WHERE status = 'READY'
                ORDER BY id ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE signal_execution_targets set_target
            SET status = 'EXECUTING',
                claimed_at = NOW()
            FROM target_batch
            WHERE set_target.id = target_batch.id
            RETURNING set_target.id;
        """
        result = session.execute(text(sql), {"limit": limit})
        rows = result.fetchall()
        session.commit()
        return [row[0] for row in rows]
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to fetch READY target IDs: {e}")
        raise DatabaseException("Failed to fetch READY execution target IDs from database.", original_exception=e)
    finally:
        session.close()
