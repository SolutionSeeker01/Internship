# client_strategies.py - Client Strategy Configuration Settings Router
'use strict'

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database.db import get_db
from models.user import User, UserRole
from dependencies.auth import get_current_user
from schemas.client_strategies import ClientStrategyBulkItem, ClientStrategyPreferenceResponse, ClientStrategyResponse
from database.strategy_repository import get_strategy_by_id
from database.client_strategy_preference_repository import (
    get_client_strategies_with_preferences,
    bulk_upsert_client_strategy_preferences
)
from exceptions import ValidationException, PlatformException
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/client/strategies",
    tags=["Client Strategy Settings"]
)


@router.get("", response_model=List[ClientStrategyResponse])
def get_client_strategies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves all available strategy catalog items joined with the client's preference configurations.
    Enforces CLIENT-only authorization.
    """
    if current_user.role != UserRole.CLIENT:
        logger.warning(f"Unauthorized client strategy config read attempt by user {current_user.id} with role {current_user.role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only CLIENT users can manage local trade settings."
        )

    try:
        preferences = get_client_strategies_with_preferences(current_user.id)
        return preferences
    except PlatformException as plat_ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(plat_ex)
        )
    except Exception as e:
        logger.error(f"Unexpected failure during client strategies query for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during trade settings retrieval."
        )


@router.put("", response_model=List[ClientStrategyPreferenceResponse])
def update_client_preferences_bulk(
    payload: List[ClientStrategyBulkItem],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bulk saves or updates active status preferences for multiple strategies.
    Validates existence and global status constraints before committing transaction.
    Enforces CLIENT-only authorization.
    """
    if current_user.role != UserRole.CLIENT:
        logger.warning(f"Unauthorized client strategy preference update by user {current_user.id} with role {current_user.role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only CLIENT users can update trade preferences."
        )

    # 1. Validate all items before invoking repository transaction
    validated_preferences = []
    for item in payload:
        strategy = get_strategy_by_id(item.strategy_id)
        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Strategy with ID {item.strategy_id} does not exist in catalog."
            )

        if not strategy.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Strategy '{strategy.get('name')}' has been globally disabled by the Administrator and cannot be configured."
            )
            
        validated_preferences.append({
            "strategy_id": item.strategy_id,
            "is_active": item.is_active
        })

    # 2. Persist bulk transaction using dedicated repository
    try:
        updated = bulk_upsert_client_strategy_preferences(
            client_id=current_user.id,
            preferences=validated_preferences
        )
        return updated
    except ValidationException as val_ex:
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
        logger.error(f"Unexpected failure during bulk client preference upsert for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while saving trade preferences."
        )
