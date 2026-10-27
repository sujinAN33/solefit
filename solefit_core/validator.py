"""수치 검증기 — 설계서 5.1장 규칙 R1~R9.

R1  μ = tanθ 재계산, 기록값과 차이 ≤ 0.01
R2  반복 측정 원값에서 평균·표준편차 재계산, n 표기 필수 (원자료 없는 평균값은 경고)
R3  물리 범위: 접촉각 0~180°, 시작각 0~90°, 비율·wt% 0 이상
R4  시험법 분리: 지표와 시험법이 맞아야 하고, DCOF는 마찰시험기에서만
R5  비교 조건 일치: 건조/습윤·마모 횟수·기재·바닥재가 같아야 비교
R6  개선율은 기준선 시편 ID와 함께, 같은 조건에 값이 두 개면 충돌
R7  synthetic 시편은 실측과 분리 (차단)
R8  추천 후보가 학습 범위 밖이면 외삽 경고   (gp.py)
R9  학습 행 수 < 입력 변수 수 × 2 이면 신뢰도 낮음 (gp.py)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .schema import (
    Finding, METHOD_METRICS, METRIC_UNIT, METRICS, METHODS, CONDITIONS, SOURCES,
)

MU_TOL = 0.01
KEY = ["specimen_id", "metric", "method", "condition", "floor", "abrasion_cycles"]


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, *a, **k):
        self.findings.append(Finding(*a, **k))

    @property
    def errors(self):
        return [f for f in self.findings if f.severity in ("error", "block")]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def by_rule(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.rule_id] = out.get(f.rule_id, 0) + 1
        return out

    def to_frame(self) -> pd.DataFrame:
        cols = ["rule_id", "severity", "row", "claim_id", "message"]
        if not self.findings:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([f.as_dict() for f in self.findings])[cols]

    def clean_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        """error/block 이 걸린 행을 제외한 데이터프레임."""
        bad = {f.row for f in self.errors if f.row is not None}
        return df[~df.index.isin(bad)]


def validate(meas: pd.DataFrame, specimens: pd.DataFrame | None = None) -> ValidationReport:
    rep = ValidationReport()
    _r3_ranges(meas, specimens, rep)
    _r4_method(meas, rep)
    _r1_mu_recalc(meas, rep)
    _r2_repeats(meas, rep)
    _r6_duplicates(meas, rep)
    if specimens is not None:
        _r7_synthetic(meas, specimens, rep)
    return rep


# ---------------------------------------------------------------- R3
def _r3_ranges(meas, specimens, rep):
    for i, r in meas.iterrows():
        v = r["value"]
        if r["metric"] not in METRICS:
            rep.add("R3", "error", f"알 수 없는 지표 '{r['metric']}'", row=i)
            continue
        if r["metric"] == "contact_angle" and not (0 <= v <= 180):
            rep.add("R3", "error", f"접촉각 {v}°는 0~180° 범위 밖", row=i)
        elif r["metric"] == "slip_angle" and not (0 <= v <= 90):
            rep.add("R3", "error", f"미끄럼 시작각 {v}°는 0~90° 범위 밖", row=i)
        elif r["metric"] in ("static_mu", "dcof") and v < 0:
            rep.add("R3", "error", f"마찰계수 {v}는 음수일 수 없음", row=i)
        if r["condition"] not in CONDITIONS:
            rep.add("R3", "error", f"condition은 dry/wet(/unknown)만 허용 ('{r['condition']}')", row=i)
        elif r["condition"] == "unknown":
            rep.add("R5", "warning", f"{r['specimen_id']} {r['metric']} {r['abrasion_cycles']}회: 건조/습윤 미확인 — 확인 전까지 그래프·학습에서 제외", row=i)
        if r["abrasion_cycles"] < 0:
            rep.add("R3", "error", "마모 횟수는 0 이상", row=i)
        if r["unit"] != METRIC_UNIT.get(r["metric"]):
            rep.add("R3", "error", f"{r['metric']}의 단위는 {METRIC_UNIT.get(r['metric'])} ('{r['unit']}')", row=i)
    if specimens is not None:
        for _, s in specimens.iterrows():
            for col in ("ratio_50nm", "hdtms_wt_pct", "silica_pu_solid_ratio", "sonication_min", "coat_count"):
                v = s.get(col)
                if pd.notna(v) and v < 0:
                    rep.add("R3", "error", f"시편 {s['specimen_id']}: {col}={v} 음수", detail={"specimen_id": s["specimen_id"]})
            if pd.notna(s.get("ratio_50nm")) and not (0 <= s["ratio_50nm"] <= 1):
                rep.add("R3", "error", f"시편 {s['specimen_id']}: ratio_50nm은 0~1 비율", detail={"specimen_id": s["specimen_id"]})
            if s.get("source") not in SOURCES:
                rep.add("R3", "error", f"시편 {s['specimen_id']}: source는 measured/synthetic", detail={"specimen_id": s["specimen_id"]})


# ---------------------------------------------------------------- R4
def _r4_method(meas, rep):
    for i, r in meas.iterrows():
        m, met = r["method"], r["metric"]
        if m not in METHODS:
            rep.add("R4", "error", f"알 수 없는 시험법 '{m}'", row=i)
        elif met not in METHOD_METRICS[m]:
            if met == "dcof":
                rep.add("R4", "error", "DCOF(동적 마찰계수)는 tribometer_dcof 시험에서만 기록 가능 — 경사판 정적 μ와 혼용 불가", row=i)
            else:
                rep.add("R4", "error", f"시험법 {m}에서는 지표 {met}를 기록할 수 없음", row=i)


# ---------------------------------------------------------------- R1
def _r1_mu_recalc(meas, rep):
    ang = meas[meas["metric"] == "slip_angle"]
    mu = meas[meas["metric"] == "static_mu"]
    join = ["specimen_id", "condition", "floor", "abrasion_cycles", "repeat_no"]
    merged = ang.reset_index().merge(mu.reset_index(), on=join, suffixes=("_a", "_m"))
    for _, r in merged.iterrows():
        calc = math.tan(math.radians(r["value_a"]))
        diff = abs(calc - r["value_m"])
        if diff > MU_TOL:
            rep.add("R1", "error",
                    f"{r['specimen_id']} {r['condition']} {r['abrasion_cycles']}회: θ={r['value_a']}° → tanθ={calc:.3f}, 기록 μ={r['value_m']} (차이 {diff:.3f})",
                    row=int(r["index_m"]), detail={"recomputed_mu": round(calc, 3)})
        else:
            rep.add("R1", "info", f"{r['specimen_id']} {r['condition']} {r['abrasion_cycles']}회: μ={r['value_m']} ✓ (tanθ={calc:.3f})",
                    row=int(r["index_m"]))


# ---------------------------------------------------------------- R2
def _r2_repeats(meas, rep):
    raw = meas[meas["agg"] == "raw"]
    mean_rows = meas[meas["agg"] == "mean"]
    raw_keys = set(map(tuple, raw[KEY].values))
    for i, r in mean_rows.iterrows():
        if r["n"] <= 1:
            rep.add("R2", "error", "평균값(agg=mean)인데 n이 1 이하 — 반복 횟수 표기 필수", row=i)
        elif tuple(r[KEY]) not in raw_keys:
            rep.add("R2", "warning", f"n={r['n']} 평균값만 있고 반복 측정 원값이 없음 — 표준편차 계산 불가, 원자료 요청 필요", row=i)
    for key, g in raw.groupby(KEY):
        if len(g) < 2:
            rep.add("R2", "warning", f"{key[0]} {key[1]} {key[3]} {key[5]}회: 반복 측정 1회뿐 — 평균·표준편차 산출 불가", row=int(g.index[0]))
        else:
            mean_v, sd = g["value"].mean(), g["value"].std(ddof=1)
            cv = sd / mean_v if mean_v else 0
            if cv > 0.15:
                rep.add("R2", "warning", f"{key[0]} {key[1]} {key[3]} {key[5]}회: 반복 {len(g)}회 평균 {mean_v:.1f} ± {sd:.1f} (CV {cv:.0%}) — 편차가 커서 재측정 또는 이상치 확인 권장", row=int(g.index[0]))
            else:
                rep.add("R2", "info", f"{key[0]} {key[1]} {key[3]} {key[5]}회: 반복 {len(g)}회 평균 {mean_v:.1f} ± {sd:.1f}", row=int(g.index[0]))
            # 같은 키의 mean 행이 있으면 재계산값과 대조
            m = mean_rows[(mean_rows[KEY] == pd.Series(key, index=KEY)).all(axis=1)]
            for j, mr in m.iterrows():
                calc = g["value"].mean()
                if abs(calc - mr["value"]) > 0.05 or mr["n"] != len(g):
                    rep.add("R2", "error", f"평균 재계산 {calc:.2f} (n={len(g)}) ≠ 기록 {mr['value']} (n={mr['n']})", row=j)


# ---------------------------------------------------------------- R6 (중복 값 충돌)
def _r6_duplicates(meas, rep):
    for key, g in meas[meas["agg"] == "mean"].groupby(KEY):
        if len(g) > 1 and g["value"].nunique() > 1:
            vals = ", ".join(f"{v}" for v in g["value"])
            for i in g.index:
                rep.add("R6", "error", f"같은 조건({key[0]} {key[1]} {key[3]} {key[5]}회)에 서로 다른 값 {vals} — 하나로 확정 필요", row=int(i))


# ---------------------------------------------------------------- R7
def _r7_synthetic(meas, specimens, rep):
    src = specimens.set_index("specimen_id")["source"].to_dict()
    for i, r in meas.iterrows():
        s = src.get(r["specimen_id"])
        if s is None:
            rep.add("R7", "error", f"시편 {r['specimen_id']}가 specimens.csv에 없음", row=i)
        elif s == "synthetic":
            rep.add("R7", "block", f"시편 {r['specimen_id']}는 가상 데이터 — 실측 데이터셋에 포함 불가", row=i)


# ---------------------------------------------------------------- 보고서 주장 검증 (R1·R4·R5·R6)
def _lookup(meas, specimen, metric, condition, cycles):
    g = meas[(meas["specimen_id"] == specimen) & (meas["metric"] == metric)
             & (meas["condition"] == condition) & (meas["abrasion_cycles"] == cycles)]
    if g.empty and metric == "static_mu":          # μ 행이 없으면 시작각에서 tanθ로 유도
        a = _lookup(meas, specimen, "slip_angle", condition, cycles)
        return None if a is None else math.tan(math.radians(a))
    if g.empty:
        return None
    raw = g[g["agg"] == "raw"]
    return raw["value"].mean() if not raw.empty else g["value"].iloc[0]


def validate_claims(claims: pd.DataFrame, meas: pd.DataFrame) -> ValidationReport:
    """보고서·발표자료의 서술 수치를 확정 데이터와 대조한다."""
    rep = ValidationReport()
    for _, c in claims.iterrows():
        cid = c["claim_id"]
        if c["claim_type"] == "dcof":
            has = not meas[(meas["metric"] == "dcof") & (meas["method"] == "tribometer_dcof")].empty
            if not has:
                rep.add("R4", "error", f"[{cid}] '{c['description']}' — DCOF 측정 데이터 없음. 실측은 경사판 정적 μ(tanθ)이므로 'DCOF'로 표기할 수 없음",
                        claim_id=cid)
            continue
        if c["claim_type"] == "value":
            actual = _lookup(meas, c["specimen_id"], c["metric"], c["condition"], int(c["abrasion_cycles"]))
            if actual is None:
                rep.add("R5", "warning", f"[{cid}] 대조할 측정값 없음: {c['description']}", claim_id=cid)
            elif abs(actual - float(c["claimed_value"])) > 0.1:
                mu_note = ""
                if c["metric"] == "slip_angle":
                    mu_note = f" (μ {math.tan(math.radians(float(c['claimed_value']))):.2f} vs {math.tan(math.radians(actual)):.2f})"
                rep.add("R6", "error", f"[{cid}] {c['source_doc']}: {c['description']} → 확정값 {actual:.1f}{c['unit'] if c['unit']!='deg' else '°'}{mu_note}", claim_id=cid,
                        detail={"claimed": float(c["claimed_value"]), "actual": round(float(actual), 2)})
            else:
                rep.add("R6", "info", f"[{cid}] ✓ {c['description']} = 확정값 {actual:.1f}", claim_id=cid)
            continue
        if c["claim_type"] == "improvement_pct":
            if pd.isna(c["baseline_id"]):
                rep.add("R6", "error", f"[{cid}] 개선율 주장에 기준선 시편 ID 없음", claim_id=cid)
                continue
            cyc = int(c["abrasion_cycles"])
            a = _lookup(meas, c["specimen_id"], c["metric"], c["condition"], cyc)
            # 기준선: 같은 마모 횟수 우선, 없으면 0회 (조건 불일치 경고)
            b = _lookup(meas, c["baseline_id"], c["metric"], c["condition"], cyc)
            b_cyc = cyc
            if b is None:
                b = _lookup(meas, c["baseline_id"], c["metric"], c["condition"], 0)
                b_cyc = 0
            if a is None or b is None:
                rep.add("R5", "warning", f"[{cid}] 개선율 재계산 불가 (측정값 없음)", claim_id=cid)
                continue
            if b_cyc != cyc:
                rep.add("R5", "warning", f"[{cid}] 기준선 {c['baseline_id']}은 마모 {b_cyc}회, 비교 대상은 {cyc}회 — 조건 불일치 비교", claim_id=cid)
            pct = (a - b) / b * 100
            if abs(pct - float(c["claimed_value"])) > 1.0:
                rep.add("R6", "error", f"[{cid}] {c['source_doc']}: '{c['description']}' → 확정값 기준 재계산 {a:.2f}/{b:.2f} = {pct:+.1f}% (주장 {c['claimed_value']}%). 주장의 기준선은 μ≈{a/(1+float(c['claimed_value'])/100):.2f}로 추정됨",
                        claim_id=cid, detail={"claimed": float(c["claimed_value"]), "actual": round(pct, 1)})
            else:
                rep.add("R6", "info", f"[{cid}] ✓ 개선율 {pct:+.1f}%", claim_id=cid)
    return rep
