"""데이터 스키마 — 설계서 7장."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SPECIMEN_COLUMNS = [
    "specimen_id", "experiment_round", "substrate", "coated", "ratio_50nm",
    "hdtms_wt_pct", "silica_pu_solid_ratio", "sonication_min", "coat_count",
    "cure_temp_c", "cure_h", "source", "note",
]
MEASUREMENT_COLUMNS = [
    "specimen_id", "metric", "method", "condition", "floor", "abrasion_cycles",
    "repeat_no", "agg", "n", "value", "unit", "measured_on", "note",
]

SUBSTRATES = ["rubber_outsole", "rubber_plate", "eva", "tpu", "crocs_resin"]
METRICS = ["contact_angle", "slip_angle", "static_mu", "dcof"]
METHODS = ["dropsnake", "incline_static", "tribometer_dcof"]
CONDITIONS = ["dry", "wet", "unknown"]   # unknown = 팀원 확인 대기, 그래프·학습에서 제외 (R5 경고)
SOURCES = ["measured", "synthetic"]

# 시험법 ↔ 허용 지표 (R4)
METHOD_METRICS = {
    "dropsnake": {"contact_angle"},
    "incline_static": {"slip_angle", "static_mu"},
    "tribometer_dcof": {"dcof"},
}
METRIC_UNIT = {"contact_angle": "deg", "slip_angle": "deg", "static_mu": "mu", "dcof": "mu"}


class SafetyProfile(BaseModel):
    """탭 ① 입력."""
    age_group: Literal["child", "adult", "senior_65_74", "senior_75_plus"]
    sole_material: Literal["rubber", "eva", "tpu", "crocs_resin", "unknown"]
    shoe_type: Literal["sneaker", "daily", "safety", "crocs"]
    environment: Literal["indoor_dry", "indoor_wet", "bathroom_wet_tile", "kitchen_factory"]
    wear_state: Literal["good", "partial", "severe"]


@dataclass
class Finding:
    rule_id: str
    severity: Literal["error", "warning", "block", "info"]
    message: str
    row: Optional[int] = None          # measurements.csv 행 번호 (0부터)
    claim_id: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "severity": self.severity, "row": self.row,
            "claim_id": self.claim_id, "message": self.message, **self.detail,
        }


def _read(path: Path | str, columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{Path(path).name}: 필수 컬럼 누락 {missing}")
    return df


def load_specimens(path: Path | str | None = None) -> pd.DataFrame:
    df = _read(path or DATA_DIR / "specimens.csv", SPECIMEN_COLUMNS)
    df["coated"] = df["coated"].astype(str).str.lower().isin(["true", "1", "yes"])
    if "session" not in df.columns:
        df["session"] = "round " + df["experiment_round"].astype(str)
    return df


def load_measurements(path: Path | str | None = None) -> pd.DataFrame:
    df = _read(path or DATA_DIR / "measurements.csv", MEASUREMENT_COLUMNS)
    df["note"] = df["note"].fillna("")
    df["measured_on"] = df["measured_on"].fillna("")
    df["abrasion_cycles"] = df["abrasion_cycles"].astype(int)
    df["repeat_no"] = df["repeat_no"].astype(int)
    df["n"] = df["n"].fillna(1).astype(int)
    df["value"] = df["value"].astype(float)
    return df


def load_claims(path: Path | str | None = None) -> pd.DataFrame:
    return pd.read_csv(path or DATA_DIR / "claims.csv")
