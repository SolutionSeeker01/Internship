# strategy_management.py - Strategy Catalog Master Management Router
'use strict'

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from typing import List
from database.db import get_db
from models.user import User, UserRole
from dependencies.auth import get_current_user
from schemas.strategy import StrategyCreate, StrategyResponse, StrategyUpdate, StrategyStatusUpdate
from database.strategy_repository import create_strategy, get_all_strategies, update_strategy, set_strategy_status
from exceptions import ValidationException, PlatformException
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/master/strategies",
    tags=["Strategy Management"]
)


@router.get("", response_model=List[StrategyResponse])
def get_strategy_catalog(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves the entire Strategy Catalog list.
    Enforces MASTER role authorization.
    """
    # 1. Enforce MASTER-only access check
    if current_user.role != UserRole.MASTER:
        logger.warning(f"Unauthorized strategy catalog retrieval by user {current_user.id} with role {current_user.role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only MASTER users can retrieve the strategy catalog."
        )

    try:
        strategies = get_all_strategies()
        return strategies
    except PlatformException as plat_ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(plat_ex)
        )
    except Exception as e:
        logger.error(f"Unexpected failure during strategy catalog fetch: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during strategy catalog retrieval."
        )


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
def create_new_strategy(
    payload: StrategyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Creates a new Strategy entity inside the master catalog.
    Enforces MASTER role authorization.
    """
    # 1. Enforce MASTER-only access check
    if current_user.role != UserRole.MASTER:
        logger.warning(f"Unauthorized strategy creation attempt by user {current_user.id} with role {current_user.role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only MASTER users can manage the strategy catalog."
        )

    try:
        # 2. Persist using repository layer (ignores FastAPI parameters inside repository)
        strategy = create_strategy(
            name=payload.name,
            description=payload.description,
            is_active=True
        )
        return strategy
    except ValidationException as val_ex:
        # Wrap project validation exceptions to return standard 400 Bad Request
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_ex)
        )
    except PlatformException as plat_ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(plat_ex)
        )
    except Exception as e:
        logger.error(f"Unexpected failure during strategy creation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during strategy creation."
        )


@router.put("/{strategy_id}", response_model=StrategyResponse)
def update_existing_strategy(
    strategy_id: int,
    payload: StrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates the name and description of an existing strategy.
    Enforces MASTER role authorization.
    """
    # 1. Enforce MASTER-only access check
    if current_user.role != UserRole.MASTER:
        logger.warning(f"Unauthorized strategy update attempt by user {current_user.id} for strategy {strategy_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only MASTER users can update strategy details."
        )

    try:
        updated = update_strategy(
            strategy_id=strategy_id,
            name=payload.name,
            description=payload.description
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy with ID {strategy_id} does not exist in catalog."
            )
        return updated
    except ValidationException as val_ex:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_ex)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected failure during strategy update of ID {strategy_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during strategy update."
        )


@router.patch("/{strategy_id}/status", response_model=StrategyResponse)
def set_existing_strategy_status(
    strategy_id: int,
    payload: StrategyStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Toggles the active status of an existing strategy (soft enable/disable).
    Enforces MASTER role authorization.
    """
    # 1. Enforce MASTER-only access check
    if current_user.role != UserRole.MASTER:
        logger.warning(f"Unauthorized strategy status change attempt by user {current_user.id} for strategy {strategy_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only MASTER users can manage strategy statuses."
        )

    try:
        updated = set_strategy_status(
            strategy_id=strategy_id,
            is_active=payload.is_active
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy with ID {strategy_id} does not exist in catalog."
            )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected failure during strategy status update of ID {strategy_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during strategy status change."
        )
