from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database.db import SessionLocal
from models.user import User, UserRole
from dependencies.auth import get_current_user
from security.password import hash_password
from schemas.user_management import UserCreateRequest, UserStatusUpdateRequest, UserManagementResponse, UserUpdateRequest, UserPasswordResetRequest

router = APIRouter(prefix="/users", tags=["User Management"])

# Dependency to get db session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_master_role(current_user: User = Depends(get_current_user)):
    """
    Enforces that only active users with the MASTER role can access these routes.
    """
    if current_user.role != UserRole.MASTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Master role required"
        )
    return current_user

@router.post("", response_model=UserManagementResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_master_role)
):
    """
    Creates a new user (MASTER or CLIENT). Only accessible by MASTER.
    """
    # Check if username already exists case-insensitively
    existing_username = db.query(User).filter(User.username == payload.username).first()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Check if email already exists
    existing_email = db.query(User).filter(User.email == payload.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address already registered"
        )



    # Hash the password
    password_hash = hash_password(payload.password)

    new_user = User(
        username=payload.username,
        email=payload.email,
        password_hash=password_hash,
        role=UserRole(payload.role),
        fullname=payload.fullname,
        is_active=True
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

@router.get("", response_model=List[UserManagementResponse], status_code=status.HTTP_200_OK)
async def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_master_role)
):
    """
    Returns a list of all users. Only accessible by MASTER.
    """
    return db.query(User).order_by(User.id.asc()).all()

@router.patch("/{user_id}/status", response_model=UserManagementResponse, status_code=status.HTTP_200_OK)
async def update_user_status(
    user_id: int,
    payload: UserStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_master_role)
):
    """
    Enables or disables user status. Only accessible by MASTER.
    Prevent users from disabling their own account.
    """
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify your own active status"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.is_active = payload.is_active

    try:
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user status"
        )

@router.patch("/{user_id}", response_model=UserManagementResponse, status_code=status.HTTP_200_OK)
async def edit_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_master_role)
):
    """
    Modifies user's Full Name, Email, and Role. Accessible only by MASTER.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Email uniqueness check (excluding current user record)
    existing_email = db.query(User).filter(User.email == payload.email, User.id != user_id).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address already registered"
        )

    user.fullname = payload.fullname
    user.email = payload.email
    user.role = UserRole(payload.role)

    try:
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user details"
        )

@router.patch("/{user_id}/password", status_code=status.HTTP_200_OK)
async def reset_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_master_role)
):
    """
    Resets the selected user's password. Accessible only by MASTER.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Hash new password
    user.password_hash = hash_password(payload.password)

    try:
        db.commit()
        return {"message": "Password reset successful"}
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )
