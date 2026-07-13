import secrets
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, status, Depends
from schemas.auth import LoginRequest, LoginResponse, UserResponse
from schemas.bootstrap import BootstrapResponse, BootstrapState
from schemas.broker import BrokerSetupRequest, BrokerSetupResponse
from schemas.oauth import BrokerConnectResponse
from schemas.callback import BrokerCallbackRequest, BrokerCallbackResponse
from services.auth_service import authenticate_user, enforce_single_active_master
from security.jwt_handler import create_access_token
from security.encryption import encrypt_value, decrypt_value
from dependencies.auth import get_current_user
from models.user import User, UserRole
from models.broker_account import BrokerAccount
from models.platform_state import PlatformState
from database.db import SessionLocal
from sqlalchemy.exc import IntegrityError
from market_data.kite_client import start_market_data_service, is_market_service_running, restart_market_data_service
import asyncio
from services.brokers.factory import BrokerFactory

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest):
    """
    Authenticates user credentials and issues a signed JWT access token.
    """
    # Verify username and password against database records
    user = authenticate_user(payload.username, payload.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    # If the user is a MASTER, enforce the single active master session rule
    if user.role == UserRole.MASTER:
        session = SessionLocal()
        try:
            # Acquire row-level lock on the single platform_state row
            state = session.query(PlatformState).filter(PlatformState.id == 1).with_for_update().first()
            if not state:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Configuration Error: PlatformState row is missing in the database."
                )
            
            if state.active_master_user_id is None:
                # Case 1: Acquire platform ownership
                state.active_master_user_id = user.id
                session.commit()
            elif state.active_master_user_id == user.id:
                # Case 2: Preserve ownership for same user
                pass
            else:
                # Case 3: Locked by another MASTER, reject login
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another MASTER is currently operating the trading platform. Only one MASTER session is allowed at a time. Please wait until the current session ends."
                )
        except HTTPException:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database transaction failure during login validation: {e}"
            )
        finally:
            session.close()

    # Resolve user's active broker or default to ZERODHA
    session = SessionLocal()
    try:
        account = session.query(BrokerAccount).filter(BrokerAccount.user_id == user.id).first()
        user.active_broker = account.broker if account else "ZERODHA"
    finally:
        session.close()

    # Generate signed JWT token incorporating user claims
    # user.role is Enum type, we export its raw string value using .value
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        active_broker=user.active_broker
    )
    
    # Return explicit schema-driven Pydantic response model
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the authenticated user details for the active session.
    """
    return current_user

@router.get("/bootstrap", response_model=BootstrapResponse, status_code=status.HTTP_200_OK)
async def bootstrap(current_user: User = Depends(get_current_user)):
    """
    Evaluates the user's broker onboarding and session state.
    """
    session = SessionLocal()
    try:
        # Retrieve the user's broker account
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id
        ).first()

        # Step 2: Check if broker credentials have been configured
        if not account or not account.api_key or not account.api_secret:
            return BootstrapResponse(state=BootstrapState.BROKER_SETUP_REQUIRED)

        # Step 3: Check if access token is configured and fresh using broker-specific expiry policy
        token_expired = True
        if account.access_token:
            try:
                from services.brokers.factory import BrokerFactory
                api_key_check = decrypt_value(account.api_key)
                access_token_check = decrypt_value(account.access_token)
                broker = BrokerFactory.get_broker(
                    account.broker,
                    api_key=api_key_check,
                    access_token=access_token_check
                )
                token_expired = broker.is_token_expired(account.updated_at)
            except Exception as e:
                logger.warning(f"Error checking token expiration for broker {account.broker}: {e}")
                token_expired = True

        if account.access_token and not token_expired:
            # Sync database connection status to reflect active trading session
            if not account.is_connected:
                account.is_connected = True
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Another MASTER is currently operating the trading platform. Only one MASTER session is allowed at a time. Please wait until the current session ends."
                    )

            # If the background market service has stopped (e.g. backend restarted), auto-start it
            if not is_market_service_running():
                try:
                    api_key = decrypt_value(account.api_key)
                    access_token = decrypt_value(account.access_token)
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to process broker credentials"
                    )

                try:
                    loop = asyncio.get_running_loop()
                    start_market_data_service(
                        loop,
                        api_key,
                        access_token
                    )
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to start market data service"
                    )
            return BootstrapResponse(state=BootstrapState.FULLY_READY)

        # Step 5: Otherwise, OAuth login is required
        if account.is_connected:
            try:
                account.is_connected = False
                session.commit()
            except Exception as db_err:
                session.rollback()
                logger.error(f"Failed to commit database update for expired token: {db_err}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database persistence failure during connection status synchronization."
                )
        return BootstrapResponse(state=BootstrapState.BROKER_AUTH_REQUIRED)
        
    finally:
        session.close()

@router.get("/broker/connect", response_model=BrokerConnectResponse, status_code=status.HTTP_200_OK)
async def connect_broker(current_user: User = Depends(get_current_user)):
    """
    Generates a secure Zerodha Kite login redirect URL using the user's stored API credentials.
    """
    session = SessionLocal()
    try:
        # Check if another master account is already active/connected
        enforce_single_active_master(session, current_user.id)

        # Retrieve the user's broker account
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id
        ).first()

        # Step 2: Validate that broker credentials exist
        if not account or not account.api_key or not account.api_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Broker credentials not configured"
            )

        # Step 3: Decrypt the stored API key
        try:
            api_key = decrypt_value(account.api_key)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process stored credentials"
            )

        # Step 4 & 5: Generate and store a secure OAuth state token with a UTC timestamp
        oauth_state = secrets.token_urlsafe(32)
        account.oauth_state = oauth_state
        account.oauth_state_created_at = datetime.now(timezone.utc)
        
        # Step 6: Construct the login redirect URL via BrokerFactory
        try:
            broker = BrokerFactory.get_broker(
                current_user.active_broker,
                api_key=api_key
            )
            login_url = broker.get_login_url(
                state=oauth_state
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid API Key configured. Please update your broker credentials."
            )

        session.commit()

        return BrokerConnectResponse(login_url=login_url)

    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate broker connection"
        )
    finally:
        session.close()

@router.post("/broker/setup", response_model=BrokerSetupResponse, status_code=status.HTTP_200_OK)
async def setup_broker(
    payload: BrokerSetupRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Encrypts and registers the user's Zerodha Developer credentials in their BrokerAccount profile.
    """
    # 1. Encrypt credentials
    try:
        encrypted_key = encrypt_value(payload.api_key)
        encrypted_secret = encrypt_value(payload.api_secret)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process broker credentials"
        )

    session = SessionLocal()
    try:
        # 2. Check if broker account already exists
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id
        ).first()

        if account:
            # Case 2: Update existing credentials and clear session tokens
            account.api_key = encrypted_key
            account.api_secret = encrypted_secret
            account.access_token = None
            account.last_login_trading_day = None
            account.is_connected = False
            account.oauth_state = None
            account.oauth_state_created_at = None
        else:
            # Case 1: Create a new broker account
            account = BrokerAccount(
                user_id=current_user.id,
                account_name="Primary Account",
                api_key=encrypted_key,
                api_secret=encrypted_secret,
                is_connected=False
            )
            session.add(account)

        session.commit()
        return BrokerSetupResponse(message="Broker credentials saved successfully")

    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save broker credentials"
        )
    finally:
        session.close()


@router.post("/broker/callback", response_model=BrokerCallbackResponse, status_code=status.HTTP_200_OK)
async def broker_callback(
    payload: BrokerCallbackRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Handles the Zerodha OAuth callback by validating the state token,
    exchanging the request token for an access token, encrypting and storing
    the access token, and activating the broker connection.
    """
    session = SessionLocal()
    try:
        # Check if another master account is already active/connected
        enforce_single_active_master(session, current_user.id)

        # STEP 1: Retrieve authenticated user's BrokerAccount
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker == current_user.active_broker
        ).first()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Broker account not configured"
            )

        # STEP 2: Validate OAuth state exists
        if (
            not account.oauth_state or
            not account.oauth_state_created_at
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth session not found"
            )

        # STEP 3: Validate OAuth state expiry (10 minutes)
        state_created_at = account.oauth_state_created_at
        if state_created_at.tzinfo is None:
            state_created_at = state_created_at.replace(
                tzinfo=timezone.utc
            )

        if datetime.now(timezone.utc) - state_created_at > timedelta(minutes=10):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth session expired"
            )

        # STEP 4: Decrypt API credentials
        try:
            api_key = decrypt_value(account.api_key)
            api_secret = decrypt_value(account.api_secret)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process broker credentials"
            )

        # STEP 5 & 6: Resolve broker provider via Factory and exchange request token
        try:
            broker = BrokerFactory.get_broker(
                current_user.active_broker,
                api_key=api_key,
                api_secret=api_secret
            )
            callback_data = broker.handle_callback(
                params={"request_token": payload.request_token}
            )
            access_token = callback_data["access_token"]
            broker_username = callback_data["broker_username"]
            broker_user_id = callback_data["broker_user_id"]
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to authenticate broker"
            )

        # STEP 7: Verify connection credentials via authenticated lightweight query
        try:
            verifier_broker = BrokerFactory.get_broker(
                current_user.active_broker,
                api_key=api_key,
                access_token=access_token
            )
            verifier_broker.verify_connection()
        except Exception as ver_err:
            logger.error(f"Failed to verify broker session validity: {ver_err}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Broker connection verification failed. Stored session is invalid or broker is unreachable."
            )

        # Duplicate Broker Account Connection validation
        if broker_user_id:
            existing = session.query(BrokerAccount).filter(
                BrokerAccount.broker_user_id == broker_user_id,
                BrokerAccount.broker == current_user.active_broker,
                BrokerAccount.user_id != current_user.id
            ).first()
            if existing:
                # Clear temporary OAuth state fields but preserve credentials configuration
                account.oauth_state = None
                account.oauth_state_created_at = None
                session.commit()

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This Zerodha account is already connected to another platform user. Please configure different broker credentials."
                )

        # STEP 8: Encrypt access_token
        try:
            encrypted_access_token = encrypt_value(access_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process broker access token"
            )

        # STEP 9 & 10: Update BrokerAccount credentials & status, and clear OAuth state
        IST = ZoneInfo("Asia/Kolkata")
        today_ist = datetime.now(IST).date()

        account.access_token = encrypted_access_token
        account.broker_username = broker_username
        account.broker_user_id = broker_user_id
        account.is_connected = True
        account.last_login_trading_day = today_ist
        account.oauth_state = None
        account.oauth_state_created_at = None

        # Start or restart the market data service dynamically on the running loop before database commit
        try:
            loop = asyncio.get_running_loop()
            if is_market_service_running():
                restart_market_data_service(
                    loop,
                    api_key,
                    access_token
                )
            else:
                start_market_data_service(
                    loop,
                    api_key,
                    access_token
                )
        except Exception as startup_err:
            # If the market service fails to start, raise an HTTP 500 error which is caught by database rollback blocks
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start market data service"
            )

        # STEP 11: Commit transaction (Only happens if start/restart service succeeded)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another MASTER user established a broker connection at the same time. Only one active trading session is allowed. Please disconnect the existing session and try again."
            )

        return BrokerCallbackResponse(message="Broker connected successfully")

    except HTTPException:
        # Re-raise standard HTTP exceptions
        session.rollback()
        raise
    except Exception:
        # Fallback for unexpected server errors (HTTP 500)
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete broker authentication"
        )
    finally:
        session.close()


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(current_user: User = Depends(get_current_user)):
    """
    Deactivates the broker connection, terminates active websocket feeds,
    and invalidates the session upon user logout.
    """
    session = SessionLocal()
    try:
        # 1. Terminate the background market feed service
        from market_data.kite_client import stop_market_data_service
        stop_market_data_service()
        
        # 2. Deactivate the broker account connection in the database
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker == current_user.active_broker
        ).first()
        if account:
            account.is_connected = False

        # 3. Release platform ownership if current user is a MASTER and owns the lock
        if current_user.role == UserRole.MASTER:
            state = session.query(PlatformState).filter(PlatformState.id == 1).with_for_update().first()
            if state and state.active_master_user_id == current_user.id:
                state.active_master_user_id = None
        
        # 4. Commit all updates together
        session.commit()
            
        return {"status": "success", "message": "Logged out successfully."}
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )
    finally:
        session.close()

