# strategy_repository.py - Database Repository for Strategy entities (SQL Execution)
'use strict'

from sqlalchemy.sql import text
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional, Dict, Any
from datetime import datetime

from database.db import SessionLocal
from exceptions import DatabaseException, ValidationException
from utils.logger import get_logger

logger = get_logger(__name__)


def create_strategy(name: str, description: Optional[str] = None, is_active: bool = True) -> Dict[str, Any]:
    """
    Creates and persists a new Strategy record in the catalog.
    Uses raw SQL execution in alignment with project standards.
    """
    if not name or not name.strip():
        raise ValidationException("Strategy name is required and cannot be empty.")

    clean_name = name.strip()
    clean_desc = description.strip() if description else None

    session = SessionLocal()
    try:
        # Check uniqueness of strategy name using raw SELECT query
        existing = session.execute(
            text("SELECT id FROM strategies WHERE name = :name"),
            {"name": clean_name}
        ).fetchone()

        if existing:
            raise ValidationException(f"A strategy with the name '{clean_name}' already exists.")

        # Insert new strategy
        result = session.execute(
            text("""
                INSERT INTO strategies (name, description, is_active)
                VALUES (:name, :description, :is_active)
                RETURNING id, name, description, is_active, created_at, updated_at
            """),
            {
                "name": clean_name,
                "description": clean_desc,
                "is_active": is_active
            }
        )
        row = result.fetchone()
        session.commit()

        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "is_active": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
    except (SQLAlchemyError, Exception) as e:
        session.rollback()
        if isinstance(e, ValidationException):
            raise
        logger.error(f"Failed to create strategy: {e}")
        raise DatabaseException("Failed to persist strategy to database.", original_exception=e)
    finally:
        session.close()


def get_all_strategies() -> List[Dict[str, Any]]:
    """
    Retrieves all strategies in the catalog ordered by ID.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("SELECT id, name, description, is_active, created_at, updated_at FROM strategies ORDER BY id ASC")
        )
        rows = result.fetchall()
        
        strategies = []
        for row in rows:
            strategies.append({
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "is_active": row[3],
                "created_at": row[4],
                "updated_at": row[5]
            })
        return strategies
    except SQLAlchemyError as e:
        logger.error(f"Failed to fetch strategies: {e}")
        raise DatabaseException("Failed to retrieve strategies from database.", original_exception=e)
    finally:
        session.close()


def get_strategy_by_id(strategy_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single strategy by its Primary Key ID.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("SELECT id, name, description, is_active, created_at, updated_at FROM strategies WHERE id = :id"),
            {"id": strategy_id}
        )
        row = result.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "is_active": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
    except SQLAlchemyError as e:
        logger.error(f"Failed to fetch strategy by ID {strategy_id}: {e}")
        raise DatabaseException(f"Failed to retrieve strategy by ID {strategy_id}.", original_exception=e)
    finally:
        session.close()


def update_strategy(strategy_id: int, name: str, description: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Updates the name and description of an existing strategy.
    """
    if not name or not name.strip():
        raise ValidationException("Strategy name is required and cannot be empty.")

    clean_name = name.strip()
    clean_desc = description.strip() if description else None

    session = SessionLocal()
    try:
        # Check if strategy exists
        existing_strat = session.execute(
            text("SELECT name FROM strategies WHERE id = :id"),
            {"id": strategy_id}
        ).fetchone()

        if not existing_strat:
            return None

        # Check unique constraint if name is changing
        if existing_strat[0] != clean_name:
            dup = session.execute(
                text("SELECT id FROM strategies WHERE name = :name"),
                {"name": clean_name}
            ).fetchone()
            if dup:
                raise ValidationException(f"A strategy with the name '{clean_name}' already exists.")

        # Update the details
        result = session.execute(
            text("""
                UPDATE strategies
                SET name = :name, description = :description, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                RETURNING id, name, description, is_active, created_at, updated_at
            """),
            {
                "id": strategy_id,
                "name": clean_name,
                "description": clean_desc
            }
        )
        row = result.fetchone()
        session.commit()

        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "is_active": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
    except (SQLAlchemyError, Exception) as e:
        session.rollback()
        if isinstance(e, ValidationException):
            raise
        logger.error(f"Failed to update strategy {strategy_id}: {e}")
        raise DatabaseException("Failed to update strategy details in database.", original_exception=e)
    finally:
        session.close()


def set_strategy_status(strategy_id: int, is_active: bool) -> Optional[Dict[str, Any]]:
    """
    Sets the active/inactive status of a strategy (soft enable/disable).
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("""
                UPDATE strategies
                SET is_active = :is_active, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                RETURNING id, name, description, is_active, created_at, updated_at
            """),
            {
                "id": strategy_id,
                "is_active": is_active
            }
        )
        row = result.fetchone()
        if not row:
            return None
            
        session.commit()

        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "is_active": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to set active status for strategy {strategy_id}: {e}")
        raise DatabaseException("Failed to set strategy active status in database.", original_exception=e)
    finally:
        session.close()
