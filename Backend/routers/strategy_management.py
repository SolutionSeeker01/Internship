# strategy_management.py - Strategy Catalog Master Management Router
'use strict'

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database.db import get_db
from models.user import User, UserRole
from dependencies.auth import get_current_user
from schemas.strategy import StrategyCreate, StrategyResponse
from database.strategy_repository import create_strategy
from exceptions import ValidationException, PlatformException
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/master/strategies",
    tags=["Strategy Management"]
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
