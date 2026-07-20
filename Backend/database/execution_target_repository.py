# execution_target_repository.py - Database Repository for Signal Execution Targets
'use strict'

from sqlalchemy.sql import text
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any

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
                COALESCE(ba.is_connected, FALSE) AS is_connected,
                ba.access_token
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
            candidates.append({
                "client_id": row[0],
                "broker_exists": bool(row[1]),
                "is_connected": bool(row[2]),
                "access_token": row[3]
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
        # Build raw parameter placeholders dynamically for a single bulk statement
        # using standard SQL parameter binding to avoid injection vulnerabilities.
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
