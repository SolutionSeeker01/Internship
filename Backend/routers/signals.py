from fastapi import APIRouter, Depends, Query, status
from typing import List, Dict, Any
from dependencies.auth import get_current_user
from models.user import User, UserRole
from fastapi import HTTPException
from database.signal_repository import get_accepted_signals, get_rejected_signals

router = APIRouter(prefix="/signals", tags=["Signals"])

@router.get("/accepted", response_model=List[Dict[str, Any]], status_code=status.HTTP_200_OK)
def get_accepted(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves a paginated list of accepted signals for the Signal Monitor.
    Only accessible by MASTER users.
    """
    if current_user.role != UserRole.MASTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only MASTER users can access signal monitoring."
        )
    return get_accepted_signals(limit=limit, offset=offset)

@router.get("/rejected", response_model=List[Dict[str, Any]], status_code=status.HTTP_200_OK)
def get_rejected(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves a paginated list of rejected signals for the Audit Log.
    Only accessible by MASTER users.
    """
    if current_user.role != UserRole.MASTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only MASTER users can access rejected signals."
        )
    return get_rejected_signals(limit=limit, offset=offset)
