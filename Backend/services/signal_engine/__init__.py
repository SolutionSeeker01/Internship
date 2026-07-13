"""
signal_engine/__init__.py

Exposes the public interface of the Signal Engine package.
"""
from .target_calculator import calculate_targets, SignalTargets

__all__ = ["calculate_targets", "SignalTargets"]
