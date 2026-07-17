# client_strategy_preference_repository.py - Client strategy preferences DB repository
'use strict'

from sqlalchemy.sql import text
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any

from database.db import SessionLocal
from exceptions import DatabaseException
from utils.logger import get_logger

logger = get_logger(__name__)


def get_client_strategies_with_preferences(client_id: int) -> List[Dict[str, Any]]:
    """
    Retrieves all available strategy catalog items joined with the client's preference
    settings if defined. Falls back to client_active=False as the default UI state.
    """
    session = SessionLocal()
    try:
        sql = """
            SELECT 
                s.id AS strategy_id,
                s.name,
                s.description,
                s.is_active AS global_active,
                COALESCE(p.is_active, FALSE) AS client_active
            FROM strategies s
            LEFT OUTER JOIN client_strategy_preferences p
              ON s.id = p.strategy_id AND p.client_id = :client_id
            ORDER BY s.id ASC;
        """
        result = session.execute(text(sql), {"client_id": client_id})
        rows = result.fetchall()
        
        output = []
        for row in rows:
            output.append({
                "strategy_id": row[0],
                "name": row[1],
                "description": row[2],
                "global_active": row[3],
                "client_active": row[4]
            })
        return output
    except SQLAlchemyError as e:
        logger.error(f"Failed to fetch client strategy preferences for user {client_id}: {e}")
        raise DatabaseException("Failed to fetch client strategy preferences from database.", original_exception=e)
    finally:
        session.close()


def bulk_upsert_client_strategy_preferences(
    client_id: int, 
    preferences: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Saves or updates multiple strategy preferences in a single database transaction.
    Only writes client_id, strategy_id, and is_active parameters.
    """
    session = SessionLocal()
    try:
        updated_records = []
        for pref in preferences:
            strategy_id = pref["strategy_id"]
            is_active = pref["is_active"]

            # Check if record exists
            existing = session.execute(
                text("SELECT id FROM client_strategy_preferences WHERE client_id = :client_id AND strategy_id = :strategy_id"),
                {"client_id": client_id, "strategy_id": strategy_id}
            ).fetchone()

            if existing:
                # UPDATE
                result = session.execute(
                    text("""
                        UPDATE client_strategy_preferences
                        SET is_active = :is_active, updated_at = CURRENT_TIMESTAMP
                        WHERE client_id = :client_id AND strategy_id = :strategy_id
                        RETURNING id, client_id, strategy_id, is_active
                    """),
                    {
                        "client_id": client_id,
                        "strategy_id": strategy_id,
                        "is_active": is_active
                    }
                )
            else:
                # INSERT
                result = session.execute(
                    text("""
                        INSERT INTO client_strategy_preferences (client_id, strategy_id, is_active)
                        VALUES (:client_id, :strategy_id, :is_active)
                        RETURNING id, client_id, strategy_id, is_active
                    """),
                    {
                        "client_id": client_id,
                        "strategy_id": strategy_id,
                        "is_active": is_active
                    }
                )
            row = result.fetchone()
            updated_records.append({
                "id": row[0],
                "client_id": row[1],
                "strategy_id": row[2],
                "is_active": row[3]
            })
            
        session.commit()
        return updated_records
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed bulk upsert of client strategy preferences for client {client_id}: {e}")
        raise DatabaseException("Failed to persist client strategy preferences in database transaction.", original_exception=e)
    finally:
        session.close()


def get_client_strategy_summary(client_id: int) -> Dict[str, int]:
    """
    Computes active and disabled strategy metrics by applying administration gating precedence.
    """
    try:
        strategies = get_client_strategies_with_preferences(client_id)
        active_count = sum(1 for s in strategies if s.get("global_active") and s.get("client_active"))
        disabled_count = len(strategies) - active_count
        return {
            "active_strategies": active_count,
            "disabled_strategies": disabled_count
        }
    except Exception as e:
        logger.error(f"Failed to calculate strategy preference summary metrics for client {client_id}: {e}")
        return {
            "active_strategies": 0,
            "disabled_strategies": 0
        }
