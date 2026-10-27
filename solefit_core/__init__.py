"""solefit_core — 수치 검증 · 안전관리 규칙 · GP 최적화 (UI 독립 패키지)."""

from .schema import (
    SafetyProfile,
    Finding,
    load_specimens,
    load_measurements,
    load_claims,
    SPECIMEN_COLUMNS,
    MEASUREMENT_COLUMNS,
)
from .validator import validate, validate_claims, ValidationReport
from .safety import assess_safety, SafetyResult, load_rules, SCENARIOS
from .summarize import summarize, contact_angle_summary, slip_angle_series, session_series, mu_bars, sessions, default_session
from .gp import fit_gp, recommend, make_synthetic, DEFAULT_BOUNDS, INPUT_VARS, GPModel

__all__ = [
    "SafetyProfile", "Finding", "load_specimens", "load_measurements", "load_claims",
    "SPECIMEN_COLUMNS", "MEASUREMENT_COLUMNS",
    "validate", "validate_claims", "ValidationReport",
    "assess_safety", "SafetyResult", "load_rules", "SCENARIOS",
    "summarize", "contact_angle_summary", "slip_angle_series", "session_series", "mu_bars", "sessions", "default_session",
    "fit_gp", "recommend", "make_synthetic", "DEFAULT_BOUNDS", "INPUT_VARS", "GPModel",
]

__version__ = "0.1.0"
