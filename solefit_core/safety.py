"""탭 ① 맞춤 안전관리 — rules.yaml 기반 규칙 엔진."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .schema import SafetyProfile

RULES_PATH = Path(__file__).resolve().parent / "rules.yaml"
LEVEL_ORDER = {"in_range": 0, "near": 1, "out_of_range": 2}
LEVEL_LABEL = {"in_range": "검증 범위 내", "near": "근접 · 추가 검증 권장", "out_of_range": "검증 범위 밖 · 시험 필요"}

# 설계서 3장 시연 시나리오
SCENARIOS = {
    "A — 어린이 운동화": SafetyProfile(age_group="child", sole_material="rubber", shoe_type="sneaker",
                                  environment="indoor_wet", wear_state="partial"),
    "B — 고령자 일상화": SafetyProfile(age_group="senior_75_plus", sole_material="rubber", shoe_type="daily",
                                  environment="bathroom_wet_tile", wear_state="partial"),
    "C — 크록스형 신발": SafetyProfile(age_group="senior_65_74", sole_material="crocs_resin", shoe_type="crocs",
                                  environment="bathroom_wet_tile", wear_state="severe"),
}


@dataclass
class SafetyResult:
    level: str                      # in_range / near / out_of_range
    level_label: str
    reasons: list[str]
    inspector: str
    inspection_path: str
    cautions: list[str]
    extra_tests: list[str]
    restorable: bool
    formulation_change: bool
    evidence: dict = field(default_factory=dict)

    def as_dict(self):
        return self.__dict__


def load_rules(path: Path | str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def assess_safety(profile: SafetyProfile, rules: dict | None = None, evidence: dict | None = None) -> SafetyResult:
    rules = rules or load_rules()
    material = profile.sole_material
    forced = rules.get("shoe_type", {}).get(profile.shoe_type, {}).get("force_material")
    reasons: list[str] = []
    if forced and material != forced:
        reasons.append(f"신발 종류가 크록스형이므로 재질을 '{forced}'로 간주")
        material = forced

    m = rules["material"][material]
    level = m["level"]
    reasons.append(m["reason"])
    extra = list(m.get("extra_tests", []))

    w = rules["wear"][profile.wear_state]
    cautions = [w["note"]]
    if w.get("force_level"):
        if LEVEL_ORDER[w["force_level"]] > LEVEL_ORDER[level]:
            level = w["force_level"]
        reasons.append("마모 상태 때문에 코팅으로 복원 불가")

    e = rules["environment"][profile.environment]
    cautions.append(e["caution"])
    extra += e.get("extra_tests", [])

    a = rules["age"][profile.age_group]
    if a.get("note"):
        cautions.append(a["note"])

    # 범위 밖이면 추가 시험을 먼저 요구 — 배합 추천은 하지 않음
    if level == "out_of_range" and not extra:
        extra.append("습윤 마찰 시험(0·200회)")

    return SafetyResult(
        level=level, level_label=LEVEL_LABEL[level], reasons=reasons,
        inspector=a["inspector"], inspection_path=a["path"], cautions=cautions,
        extra_tests=list(dict.fromkeys(extra)), restorable=bool(w.get("restorable", True)),
        formulation_change=bool(a.get("formulation_change", False)),
        evidence=evidence or {},
    )
