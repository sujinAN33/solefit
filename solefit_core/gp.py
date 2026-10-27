"""탭 ③ Gaussian Process 실험 최적화 — 설계서 5.2장.

입력 6변수 → 목표(습윤 μ 또는 접촉각). Matern(ν=2.5) + WhiteKernel,
LHS 2,000개 후보에서 UCB = μ + κσ 상위 k개 추천. R8(외삽)·R9(표본 부족) 경고 포함.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from sklearn.exceptions import ConvergenceWarning

warnings.filterwarnings("ignore", category=ConvergenceWarning)
import pandas as pd
from scipy.stats import qmc
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from .schema import Finding

INPUT_VARS = ["ratio_50nm", "hdtms_wt_pct", "silica_pu_solid_ratio", "sonication_min", "coat_count", "activation_cycles"]
VAR_LABEL = {
    "ratio_50nm": "50 nm 입자 중량 비율", "hdtms_wt_pct": "HDTMS (실리카 대비 wt%)",
    "silica_pu_solid_ratio": "실리카:PU 고형분 비", "sonication_min": "초음파 분산 시간(분)",
    "coat_count": "도포 횟수", "activation_cycles": "표면 활성화(사포 마모 횟수)",
}
INTEGER_VARS = {"coat_count", "activation_cycles"}
# 임시 탐색 범위 — 화공 팀원이 실험 가능 범위로 확정해야 함 (설계서 5.2)
DEFAULT_BOUNDS = {
    "ratio_50nm": (0.5, 0.9), "hdtms_wt_pct": (5.0, 15.0), "silica_pu_solid_ratio": (0.6, 1.4),
    "sonication_min": (10.0, 30.0), "coat_count": (1, 4), "activation_cycles": (0, 200),
}
CURRENT_OPTIMUM = {"ratio_50nm": 0.75, "hdtms_wt_pct": 10.0, "silica_pu_solid_ratio": 1.0,
                   "sonication_min": 20.0, "coat_count": 2, "activation_cycles": 200}
TARGETS = {"wet_mu": "습윤 정적 μ (tanθ)", "contact_angle": "접촉각 (°)"}


@dataclass
class GPModel:
    gpr: GaussianProcessRegressor
    target: str
    bounds: dict
    x_min: np.ndarray
    x_max: np.ndarray
    y_mean: float
    y_std: float
    n_train: int
    train: pd.DataFrame
    loo_rmse: float
    loo_coverage95: float
    source: str                      # measured / synthetic
    findings: list[Finding] = field(default_factory=list)

    def _scale(self, X: np.ndarray) -> np.ndarray:
        return (X - self.x_min) / np.where(self.x_max - self.x_min == 0, 1, self.x_max - self.x_min)

    def predict(self, X: pd.DataFrame | np.ndarray):
        X = np.asarray(X, dtype=float)
        m, s = self.gpr.predict(self._scale(X), return_std=True)
        return m * self.y_std + self.y_mean, s * self.y_std


# ------------------------------------------------------------------ 가상 데이터
def _synthetic_truth(X: pd.DataFrame, target: str) -> np.ndarray:
    """현 최적점 근처에서 최대가 되는 가상 함수. 실제 배합 성능이 아님."""
    z = {k: (X[k].to_numpy(dtype=float) - CURRENT_OPTIMUM[k]) / (DEFAULT_BOUNDS[k][1] - DEFAULT_BOUNDS[k][0]) for k in INPUT_VARS}
    bump = np.exp(-(2.5 * z["ratio_50nm"] ** 2 + 2.0 * z["hdtms_wt_pct"] ** 2 + 2.5 * z["silica_pu_solid_ratio"] ** 2
                    + 1.0 * z["sonication_min"] ** 2 + 1.5 * z["coat_count"] ** 2))
    act = X["activation_cycles"].to_numpy(dtype=float) / 200.0      # 활성화할수록 μ 상승 (실험 경향 반영)
    if target == "wet_mu":
        return 0.45 + 0.35 * bump + 0.45 * act * (0.6 + 0.4 * bump)
    return 115 + 40 * bump - 5 * act


def make_synthetic(n: int = 24, target: str = "wet_mu", seed: int = 42, noise: float = 0.03, bounds: dict | None = None) -> pd.DataFrame:
    """고정 시드 가상 데이터 (source=synthetic). 화면·파일 모두에 synthetic 표시를 남긴다."""
    bounds = bounds or DEFAULT_BOUNDS
    rng = np.random.default_rng(seed)
    lo = np.array([bounds[k][0] for k in INPUT_VARS]); hi = np.array([bounds[k][1] for k in INPUT_VARS])
    sample = qmc.scale(qmc.LatinHypercube(d=len(INPUT_VARS), seed=seed).random(n), lo, hi)
    df = pd.DataFrame(sample, columns=INPUT_VARS)
    for k in INTEGER_VARS:
        df[k] = df[k].round().astype(int)
    y = _synthetic_truth(df, target)
    scale = 1.0 if target == "wet_mu" else 60.0
    df[target] = y + rng.normal(0, noise * scale, n)
    df["source"] = "synthetic"
    df["specimen_id"] = [f"SYN-{i+1:02d}" for i in range(n)]
    return df


# ------------------------------------------------------------------ 실측 → 학습표
def measured_training_table(specimens: pd.DataFrame, meas: pd.DataFrame, target: str = "wet_mu") -> pd.DataFrame:
    """검증 통과한 실측 데이터에서 코팅 시편 × 마모 횟수별 학습 행을 만든다."""
    rows = []
    coated = specimens[(specimens["coated"]) & (specimens["source"] == "measured")]
    coated = coated.dropna(subset=[k for k in INPUT_VARS if k != "activation_cycles"])   # 배합 미기재 시편 제외
    for _, s in coated.iterrows():
        if target == "wet_mu":
            g = meas[(meas["specimen_id"] == s["specimen_id"]) & (meas["metric"] == "slip_angle")
                     & (meas["condition"] == "wet") & (meas["method"] == "incline_static")]  # unknown 조건 제외
            for cyc, gg in g.groupby("abrasion_cycles"):
                raw = gg[gg["agg"] == "raw"]
                v = raw["value"].mean() if not raw.empty else gg["value"].iloc[0]
                rows.append({**{k: s[k] for k in INPUT_VARS if k != "activation_cycles"}, "activation_cycles": int(cyc),
                             target: float(np.tan(np.radians(v))), "source": "measured", "specimen_id": s["specimen_id"]})
        else:
            g = meas[(meas["specimen_id"] == s["specimen_id"]) & (meas["metric"] == "contact_angle")]
            if not g.empty:
                rows.append({**{k: s[k] for k in INPUT_VARS if k != "activation_cycles"}, "activation_cycles": 0,
                             target: float(g["value"].mean()), "source": "measured", "specimen_id": s["specimen_id"]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 학습
def _loo(gpr_factory, Xs: np.ndarray, ys: np.ndarray):
    n = len(ys)
    if n < 3:
        return float("nan"), float("nan")
    errs, hits = [], 0
    for i in range(n):
        mask = np.arange(n) != i
        g = gpr_factory().fit(Xs[mask], ys[mask])
        m, s = g.predict(Xs[i:i + 1], return_std=True)
        errs.append((m[0] - ys[i]) ** 2)
        hits += abs(m[0] - ys[i]) <= 1.96 * s[0]
    return float(np.sqrt(np.mean(errs))), hits / n


def fit_gp(train: pd.DataFrame, target: str = "wet_mu", bounds: dict | None = None, loo: bool = True) -> GPModel:
    bounds = bounds or DEFAULT_BOUNDS
    if train.empty:
        raise ValueError("학습 데이터가 없습니다")
    findings: list[Finding] = []
    src = "synthetic" if (train["source"] == "synthetic").any() else "measured"
    if train["source"].nunique() > 1:
        raise ValueError("R7: 실측과 가상 데이터를 한 모델에 섞을 수 없습니다")
    n = len(train)
    if n < 2 * len(INPUT_VARS):
        findings.append(Finding("R9", "warning", f"학습 행 {n}개 < 입력 변수 {len(INPUT_VARS)}개 × 2 — 예측 신뢰도 낮음. 추천은 참고용"))

    X = train[INPUT_VARS].to_numpy(dtype=float)
    y = train[target].to_numpy(dtype=float)
    x_min, x_max = X.min(axis=0), X.max(axis=0)
    span = np.where(x_max - x_min == 0, 1, x_max - x_min)
    Xs = (X - x_min) / span
    y_mean, y_std = float(y.mean()), float(y.std()) if y.std() > 0 else 1.0
    ys = (y - y_mean) / y_std

    def factory():
        k = ConstantKernel(1.0, (1e-2, 1e2)) * Matern(length_scale=np.ones(len(INPUT_VARS)), length_scale_bounds=(1e-2, 1e2), nu=2.5) \
            + WhiteKernel(noise_level=1e-2, noise_level_bounds=(1e-5, 1.0))
        return GaussianProcessRegressor(kernel=k, normalize_y=False, n_restarts_optimizer=3, random_state=0)

    gpr = factory().fit(Xs, ys)
    rmse, cov = _loo(factory, Xs, ys) if loo else (float("nan"), float("nan"))
    if not np.isnan(rmse):
        rmse *= y_std
    return GPModel(gpr, target, bounds, x_min, x_max, y_mean, y_std, n, train, rmse, cov, src, findings)


# ------------------------------------------------------------------ 추천
def recommend(model: GPModel, kappa: float = 2.0, k: int = 5, n_candidates: int = 2000, seed: int = 0) -> tuple[pd.DataFrame, list[Finding]]:
    b = model.bounds
    lo = np.array([b[v][0] for v in INPUT_VARS]); hi = np.array([b[v][1] for v in INPUT_VARS])
    cand = pd.DataFrame(qmc.scale(qmc.LatinHypercube(d=len(INPUT_VARS), seed=seed).random(n_candidates), lo, hi), columns=INPUT_VARS)
    for v in INTEGER_VARS:
        cand[v] = cand[v].round().astype(int)
    mean, std = model.predict(cand)
    cand["pred_mean"] = mean
    cand["pred_std"] = std
    cand["ucb"] = mean + kappa * std
    # R8: 학습 범위 밖 외삽 표시
    out = np.zeros(len(cand), dtype=bool)
    for j, v in enumerate(INPUT_VARS):
        out |= (cand[v].to_numpy() < model.x_min[j]) | (cand[v].to_numpy() > model.x_max[j])
    cand["extrapolated"] = out
    top = cand.sort_values("ucb", ascending=False).head(k).reset_index(drop=True)
    top.insert(0, "rank", range(1, len(top) + 1))
    findings = list(model.findings)
    n_ext = int(top["extrapolated"].sum())
    if n_ext:
        findings.append(Finding("R8", "warning", f"추천 후보 {n_ext}/{len(top)}개가 학습 데이터 범위 밖(외삽) — 불확실성이 과소평가될 수 있음"))
    if model.source == "synthetic":
        findings.append(Finding("R7", "info", "가상 데이터로 학습한 모델 — 추천 후보는 알고리즘 작동 시연용이며 실제 최적 배합이 아님"))
    return top, findings


def partial_dependence(model: GPModel, var: str, n: int = 40) -> pd.DataFrame:
    """다른 변수는 현 최적점에 고정, var만 움직여 예측 평균·σ."""
    lo, hi = model.bounds[var]
    xs = np.linspace(lo, hi, n)
    base = pd.DataFrame([CURRENT_OPTIMUM] * n)
    base[var] = xs.round() if var in INTEGER_VARS else xs
    m, s = model.predict(base[INPUT_VARS])
    return pd.DataFrame({var: base[var], "pred_mean": m, "pred_std": s})
