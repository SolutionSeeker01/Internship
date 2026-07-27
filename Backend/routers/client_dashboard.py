# client_dashboard.py - CLIENT Dashboard and Portfolio REST Router
'use strict';

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List
from datetime import datetime

from database.db import get_db
from models.user import User
from models.broker_account import BrokerAccount
from dependencies.auth import get_current_user
from services.brokers.factory import BrokerFactory
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/client",
    tags=["Client Dashboard"]
)


def get_active_broker_client(current_user: User, db: Session) -> Any:
    """
    Helper to load the user's active broker account and return an instantiated BaseBroker client using the common factory.
    """
    account = db.query(BrokerAccount).filter(
        BrokerAccount.user_id == current_user.id
    ).first()

    if not account or not account.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Broker account credentials not configured. Please complete broker setup."
        )

    if not account.is_connected or not account.access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Broker account session is expired or not authenticated. Please connect your broker."
        )

    try:
        # Instantiate broker client using the common factory
        broker = BrokerFactory.create(account)
        return broker
    except Exception as e:
        logger.error(f"Failed to initialize broker adapter for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to broker adapter integration."
        )


@router.get("/dashboard/summary")
def get_dashboard_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns aggregate client profile status, session status, and cash margins.
    """
    account = db.query(BrokerAccount).filter(
        BrokerAccount.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Broker account credentials not configured. Please complete broker setup."
        )

    # 1. Evaluate connection and validity status
    connection_status = "CONNECTED" if (account.is_connected and account.access_token) else "EXPIRED"

    # 2. Query margins from broker for cash totals
    available_cash = 0.0
    utilized_margin = 0.0
    net_value = 0.0
    margin_utilization_pct = 0.0

    if connection_status == "CONNECTED":
        try:
            broker = get_active_broker_client(current_user, db)
            margins = broker.get_margins()
            available_cash = margins.get("available_cash", 0.0)
            utilized_margin = margins.get("utilized_margin", 0.0)
            net_value = margins.get("net_value", available_cash)
            total = net_value if net_value > 0 else (available_cash + utilized_margin)
            if total > 0:
                margin_utilization_pct = round((utilized_margin / total) * 100, 2)
        except Exception as e:
            logger.warning(f"Failed to fetch live margins for dashboard summary of user {current_user.id}: {e}")

    # 3. Compile summary data
    summary_payload = {
        "broker_name": account.broker,
        "connection_status": connection_status,
        "available_cash": available_cash,
        "net_cash": net_value,
        "net_value": net_value,
        "capital_base": net_value,
        "utilized_margin": utilized_margin,
        "margin_utilization_pct": margin_utilization_pct,
        
        # Keep platform/strategy properties as placeholders
        "today_pnl": 0.0,
        "daily_drawdown_pct": 0.0,
        "risk_status": "SAFE",
        "max_drawdown_limit_pct": 5.0,
        "auto_trading_enabled": True,
        "active_strategies": 0,
        "disabled_strategies": 0
    }

    # 4. Query client strategy preference counts dynamically from repository summary helper
    try:
        from database.client_strategy_preference_repository import get_client_strategy_summary
        summary_stats = get_client_strategy_summary(current_user.id)
        summary_payload["active_strategies"] = summary_stats.get("active_strategies", 0)
        summary_payload["disabled_strategies"] = summary_stats.get("disabled_strategies", 0)
    except Exception as e:
        logger.error(f"Failed to fetch client strategy preference summary for user {current_user.id}: {e}")

    return summary_payload


@router.get("/portfolio/positions")
def get_portfolio_positions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns today's active net trading positions fetched dynamically from the broker adapter.
    """
    broker = get_active_broker_client(current_user, db)
    try:
        raw_positions = broker.get_positions()
        
        # Standardize position schema
        positions = []
        for pos in raw_positions:
            qty = pos.get("quantity", 0)
            direction = "LONG" if qty >= 0 else "SHORT"
            
            positions.append({
                "symbol": pos.get("symbol"),
                "exchange": pos.get("exchange"),
                "quantity": qty,
                "direction": direction,
                "average_price": pos.get("average_price", 0.0),
                "last_traded_price": pos.get("last_price", 0.0),
                "unrealized_pnl": pos.get("pnl", 0.0),
                
                # Platform placeholders
                "strategy_name": "Strategy Active",
                "stop_loss_price": 0.0
            })
        return {"positions": positions}
    except Exception as e:
        logger.error(f"Failed to fetch positions from broker: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve portfolio positions from broker."
        )
