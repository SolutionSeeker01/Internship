# signal_details_service.py - Orchestrates compiler layout for MASTER Signal Details visualization

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from database.signal_repository import get_signal_targets_with_usernames
from sqlalchemy.sql import text
from typing import Dict, Any

def compile_signal_details(db: Session, signal_id: int) -> Dict[str, Any]:
    """
    Orchestrates compiling the complete read-only Signal Details response.
    Retrieves the raw signal row and target execution mapping, aggregates summaries, 
    and returns a structured serialization dictionary.
    
    This service is strictly read-only and does not trigger or rerun any eligibility computations.
    """
    # 1. Fetch raw signal record
    # We query the signals table directly using a minimal SQL fetch to avoid model instantiation overhead.
    signal_sql = """
        SELECT id, signal_uuid, action, symbol, entry, stoploss, timeframe, signal_timestamp, status, created_at, validation_status, validation_reason, validated_at, t1, t2, t3, strategy_id
        FROM signals
        WHERE id = :signal_id;
    """
    signal_row = db.execute(text(signal_sql), {"signal_id": signal_id}).fetchone()
    
    if not signal_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal with ID #{signal_id} does not exist."
        )
        
    signal_data = dict(signal_row._mapping)
    
    # 2. Fetch associated execution target join rows
    raw_targets = get_signal_targets_with_usernames(db, signal_id)
    
    # 3. Aggregate summary statistics (Ownership of aggregation remains in the service layer)
    ready_count = sum(1 for t in raw_targets if t["status"] == "READY")
    skipped_count = sum(1 for t in raw_targets if t["status"] == "SKIPPED")
    
    # 4. Assemble the schema-structured dictionary representation
    return {
        "signal": signal_data,
        "summary": {
            "total": len(raw_targets),
            "ready": ready_count,
            "skipped": skipped_count
        },
        "targets": raw_targets
    }
