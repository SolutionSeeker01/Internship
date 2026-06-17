from enum import Enum

class SignalStatus(str, Enum):
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    ACTIVE = "ACTIVE"
    SL_HIT = "SL_HIT"
    T1_HIT = "T1_HIT"
    T2_HIT = "T2_HIT"
    T3_HIT = "T3_HIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
