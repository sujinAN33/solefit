"""마모 성능 추세 — 측정값과 예측값을 구분한 회귀 분석 (팀 안내: '마찰계수 변화의 회귀 모델 및 예측 시각화').

각 시계열(시편 × 조건)에 대해 마모 횟수 x → 마찰계수 y 를 1차/2차 다항 회귀로 적합하고,
측정 구간(0~200회)의 적합 곡선과 그 밖(예: ~300회)의 외삽을 구분해 돌려준다.
측정 점은 반복 평균 ± 표준편차, 예측 곡선은 95% 예측 구간(잔차 기반 t 분포)과 함께 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class TrendFit:
    label: str
    condition: str
    degree: int
    coef: np.ndarray            # 높은 차수부터 (np.polyfit)
    r2: float
    rmse: float
    n: int
    x_min: float
    x_max: float
    slope_per_100: float        # 측정 구간 평균 기울기 (μ / 100회)
    curve: pd.DataFrame         # x, y_hat, lo, hi, extrapolated

    def predict(self, x):
        return np.polyval(self.coef, np.asarray(x, dtype=float))


def _fit(x: np.ndarray, y: np.ndarray, degree: int, x_pred: np.ndarray) -> tuple[np.ndarray, float, float, np.ndarray, np.ndarray]:
    coef = np.polyfit(x, y, degree)
    yhat = np.polyval(coef, x)
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    r2 = 1 - ss_res / ss_tot
    dof = max(len(x) - (degree + 1), 1)
    rmse = float(np.sqrt(ss_res / dof))
    # 예측 구간: 설계행렬 기반 (x^d ... 1)
    X = np.vander(x, degree + 1)
    Xp = np.vander(x_pred, degree + 1)
    XtX_inv = np.linalg.pinv(X.T @ X)
    lev = np.einsum("ij,jk,ik->i", Xp, XtX_inv, Xp)
    t = stats.t.ppf(0.975, dof)
    half = t * rmse * np.sqrt(1 + lev)
    yp = np.polyval(coef, x_pred)
    return coef, r2, rmse, yp, half


def fit_trend(series: pd.DataFrame, label: str, condition: str, degree: int = 2, extrapolate_to: float | None = 300,
              ycol: str = "mu", xcol: str = "abrasion_cycles") -> TrendFit | None:
    g = series[(series["label"] == label) & (series["condition"] == condition)].sort_values(xcol)
    if len(g) < degree + 2:
        if len(g) >= 2 and degree > 1:
            return fit_trend(series, label, condition, degree=1, extrapolate_to=extrapolate_to, ycol=ycol, xcol=xcol)
        return None
    x = g[xcol].to_numpy(dtype=float)
    y = g[ycol].to_numpy(dtype=float)
    x_end = max(x.max(), extrapolate_to or x.max())
    x_pred = np.linspace(x.min(), x_end, 61)
    coef, r2, rmse, yp, half = _fit(x, y, degree, x_pred)
    curve = pd.DataFrame({"x": x_pred, "y_hat": yp, "lo": yp - half, "hi": yp + half, "extrapolated": x_pred > x.max() + 1e-9})
    slope = float((np.polyval(coef, x.max()) - np.polyval(coef, x.min())) / max(x.max() - x.min(), 1) * 100)
    return TrendFit(label, condition, degree, coef, float(r2), rmse, len(g), float(x.min()), float(x.max()), slope, curve)


def trend_table(fits: list[TrendFit]) -> pd.DataFrame:
    rows = []
    for f in fits:
        y0, y1 = float(f.predict(f.x_min)), float(f.predict(f.x_max))
        rows.append({"시편": f.label, "조건": f.condition, "모델": f"{f.degree}차 다항", "R²": round(f.r2, 3), "RMSE": round(f.rmse, 3),
                     "측정 지점": f.n, f"{int(f.x_min)}회 적합값": round(y0, 3), f"{int(f.x_max)}회 적합값": round(y1, 3),
                     "평균 변화 (μ/100회)": round(f.slope_per_100, 3),
                     "판정": "상승" if f.slope_per_100 > 0.02 else ("저하" if f.slope_per_100 < -0.02 else "유지")})
    return pd.DataFrame(rows)


def degradation_summary(series: pd.DataFrame, ycol: str = "mu") -> pd.DataFrame:
    """기존 배합의 마모에 따른 성능 변화: 시편·조건별 0회 대비 최대 마모 지점의 변화율."""
    rows = []
    for (label, cond), g in series.groupby(["label", "condition"]):
        g = g.sort_values("abrasion_cycles")
        if len(g) < 2:
            continue
        y0, y1 = float(g[ycol].iloc[0]), float(g[ycol].iloc[-1])
        rows.append({"시편": label, "조건": cond, "0회": round(y0, 3), f"{int(g['abrasion_cycles'].iloc[-1])}회": round(y1, 3),
                     "변화율 (%)": round((y1 / y0 - 1) * 100, 1), "최저점 (회)": int(g.loc[g[ycol].idxmin(), "abrasion_cycles"]),
                     "최저값": round(float(g[ycol].min()), 3)})
    return pd.DataFrame(rows)
