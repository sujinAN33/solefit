"""탭 ② 그래프용 집계 — 검증을 통과한 데이터만 받는다. 실험 세션(specimens.session) 단위로 묶는다."""

from __future__ import annotations

import math

import pandas as pd

DEFAULT_SESSION_KEY = "통합본"   # 기본 세션 (session 문자열에 포함) — 팀 확정 통합본


def sessions(specimens: pd.DataFrame) -> list[str]:
    if "session" not in specimens.columns:
        return []
    return list(dict.fromkeys(specimens["session"].dropna()))


def default_session(specimens: pd.DataFrame) -> str | None:
    ss = sessions(specimens)
    for s in ss:
        if DEFAULT_SESSION_KEY in s:
            return s
    return ss[0] if ss else None


def session_specimens(specimens: pd.DataFrame, session: str | None) -> pd.DataFrame:
    if session is None or "session" not in specimens.columns:
        return specimens
    return specimens[specimens["session"] == session]


def _label(specimens: pd.DataFrame, sid: str) -> str:
    sp = specimens.set_index("specimen_id")
    if sid not in sp.index:
        return sid
    r = sp.loc[sid]
    base = "코팅" if bool(r["coated"]) else "미코팅"
    # 같은 세션에 같은 종류 시편이 둘 이상이면 note 앞부분으로 구분
    same = specimens[(specimens["coated"] == bool(r["coated"]))]
    if "session" in specimens.columns:
        same = same[same["session"] == r.get("session")]
    if len(same) > 1:
        return f"{base} ({sid})"
    return base


def _stats(g: pd.DataFrame):
    raw = g[g["agg"] == "raw"]
    if not raw.empty:
        v = raw["value"].mean()
        sd = raw["value"].std(ddof=1) if len(raw) > 1 else float("nan")
        return v, sd, len(raw), False
    v = g["value"].iloc[0]
    return v, float("nan"), int(g["n"].iloc[0]), "눈대중" in str(g["note"].iloc[0])


def contact_angle_summary(meas: pd.DataFrame, specimens: pd.DataFrame | None = None) -> pd.DataFrame:
    g = meas[(meas["metric"] == "contact_angle") & (meas["agg"] == "raw")]
    out = g.groupby("specimen_id")["value"].agg(["mean", "std", "count"]).reset_index()
    out["label"] = out["specimen_id"].map(lambda s: _label(specimens, s) if specimens is not None else s)
    out["std"] = out["std"].fillna(0.0)
    out["meets_150"] = out["mean"] >= 150
    return out.rename(columns={"count": "n"})


def slip_angle_series(meas: pd.DataFrame, specimen_id: str, method: str = "incline_static") -> pd.DataFrame:
    """한 시편의 마모 횟수별 건조·습윤 미끄럼 시작각 + μ=tanθ. 조건 미확인(unknown) 행 제외."""
    g = meas[(meas["metric"] == "slip_angle") & (meas["specimen_id"] == specimen_id) & (meas["method"] == method)
             & (meas["condition"].isin(["dry", "wet"]))]
    rows = []
    for (cond, cyc), gg in g.groupby(["condition", "abrasion_cycles"]):
        v, sd, n, est = _stats(gg)
        rows.append({"specimen_id": specimen_id, "condition": cond, "abrasion_cycles": cyc, "slip_angle": v, "std": sd, "n": n,
                     "mu": round(math.tan(math.radians(v)), 3), "estimated_from_graph": est})
    cols = ["specimen_id", "condition", "abrasion_cycles", "slip_angle", "std", "n", "mu", "estimated_from_graph"]
    return pd.DataFrame(rows, columns=cols).sort_values(["condition", "abrasion_cycles"]).reset_index(drop=True)


def session_series(meas: pd.DataFrame, specimens: pd.DataFrame, session: str | None) -> pd.DataFrame:
    """세션 안의 모든 시편 시계열을 한 표로 (label 컬럼 포함)."""
    sp = session_specimens(specimens, session)
    parts = []
    for sid in sp["specimen_id"]:
        s = slip_angle_series(meas, sid)
        if not s.empty:
            s["label"] = _label(specimens, sid)
            s["coated"] = bool(sp.set_index("specimen_id").loc[sid, "coated"])
            parts.append(s)
    cols = ["specimen_id", "label", "coated", "condition", "abrasion_cycles", "slip_angle", "std", "n", "mu", "estimated_from_graph"]
    return pd.concat(parts, ignore_index=True)[cols] if parts else pd.DataFrame(columns=cols)


def mu_bars(series: pd.DataFrame) -> pd.DataFrame:
    """세션 시계열에서 막대 비교: 각 시편의 0회와 최대 마모 횟수 (미코팅 먼저)."""
    rows = []
    for (sid, label, coated), g in series.groupby(["specimen_id", "label", "coated"], sort=False):
        cycs = sorted(g["abrasion_cycles"].unique())
        picks = [cycs[0]] + ([cycs[-1]] if len(cycs) > 1 else [])
        for cyc in picks:
            for cond in ("dry", "wet"):
                h = g[(g["abrasion_cycles"] == cyc) & (g["condition"] == cond)]
                if h.empty:
                    continue
                name = label if (cyc == 0 and not coated and len(cycs) == 1) else f"{label} ({cyc}회)"
                rows.append({"group": name, "coated": coated, "cycles": cyc, "condition": cond, "mu": float(h["mu"].iloc[0]), "n": int(h["n"].iloc[0])})
    df = pd.DataFrame(rows, columns=["group", "coated", "cycles", "condition", "mu", "n"])
    return df.sort_values(["coated", "cycles", "condition"], kind="stable").reset_index(drop=True)


def improvements(series: pd.DataFrame) -> list[dict]:
    """같은 마모 횟수의 미코팅 대비 코팅 μ 변화율 (R5: 조건 일치 비교만)."""
    out = []
    unc = series[~series["coated"]]
    coat = series[series["coated"]]
    if unc.empty or coat.empty:
        return out
    unc_cycles = set(unc["abrasion_cycles"])
    for cond in ("dry", "wet"):
        c = coat[coat["condition"] == cond]
        u = unc[unc["condition"] == cond]
        for cyc in sorted(c["abrasion_cycles"].unique()):
            base_cyc = cyc if cyc in unc_cycles else (0 if 0 in unc_cycles else None)
            if base_cyc is None:
                continue
            b = u[u["abrasion_cycles"] == base_cyc]
            t = c[c["abrasion_cycles"] == cyc]
            if b.empty or t.empty:
                continue
            bm, tm = float(b["mu"].iloc[0]), float(t["mu"].iloc[0])
            out.append({"condition": cond, "cycles": int(cyc), "baseline_cycles": int(base_cyc), "baseline_mu": bm,
                        "coated_mu": tm, "pct": round((tm / bm - 1) * 100, 1), "same_cycles": base_cyc == cyc})
    return out


def dcof_series(meas: pd.DataFrame, specimens: pd.DataFrame, session: str | None) -> pd.DataFrame:
    """동적 마찰계수(DCOF) — 마찰시험기(tribometer_dcof) 또는 경사판 동적법(incline_dynamic, 경사각별).
    경사판 정적 μ와는 섞지 않는다(R4). 건조/습윤 미기재(unknown)도 표시하되 condition 컬럼에 남긴다."""
    sp = session_specimens(specimens, session)
    g = meas[(meas["metric"] == "dcof") & (meas["method"].isin(["tribometer_dcof", "incline_dynamic"]))
             & (meas["specimen_id"].isin(sp["specimen_id"]))]
    cols = ["specimen_id", "label", "coated", "method", "condition", "test_angle_deg", "abrasion_cycles", "dcof", "std", "n"]
    if g.empty:
        return pd.DataFrame(columns=cols)
    g = g.copy()
    g["test_angle_deg"] = g["test_angle_deg"].fillna(-1.0)
    rows = []
    spi = sp.set_index("specimen_id")
    for (sid, method, cond, ang, cyc), gg in g.groupby(["specimen_id", "method", "condition", "test_angle_deg", "abrasion_cycles"]):
        v, sd, n, _ = _stats(gg)
        rows.append({"specimen_id": sid, "label": _label(specimens, sid), "coated": bool(spi.loc[sid, "coated"]), "method": method,
                     "condition": cond, "test_angle_deg": (None if ang < 0 else ang), "abrasion_cycles": cyc, "dcof": v, "std": sd, "n": n})
    return pd.DataFrame(rows, columns=cols).sort_values(["coated", "test_angle_deg", "abrasion_cycles"]).reset_index(drop=True)


def dcof_by_angle_mean(dcof: pd.DataFrame) -> pd.DataFrame:
    """경사각을 평균한 마모 횟수별 DCOF (경사각별 값이 서로 다른 조건이므로 참고용)."""
    if dcof.empty:
        return pd.DataFrame(columns=["label", "coated", "abrasion_cycles", "dcof_mean", "dcof_std", "n_angles"])
    out = dcof.groupby(["label", "coated", "abrasion_cycles"])["dcof"].agg(["mean", "std", "count"]).reset_index()
    return out.rename(columns={"mean": "dcof_mean", "std": "dcof_std", "count": "n_angles"})


def mass_summary(mass: pd.DataFrame | None, session: str | None) -> pd.DataFrame:
    """사포질 횟수별 질량 변화율(%) — 0회 대비."""
    cols = ["abrasion_cycles", "uncoated_g", "coated_g", "uncoated_loss_pct", "coated_loss_pct"]
    if mass is None or mass.empty:
        return pd.DataFrame(columns=cols)
    m = mass[mass["session"] == session] if session and "session" in mass.columns else mass
    if m.empty:
        return pd.DataFrame(columns=cols)
    m = m.sort_values("abrasion_cycles").copy()
    u0, c0 = m["uncoated_g"].iloc[0], m["coated_g"].iloc[0]
    m["uncoated_loss_pct"] = ((u0 - m["uncoated_g"]) / u0 * 100).round(3)
    m["coated_loss_pct"] = ((c0 - m["coated_g"]) / c0 * 100).round(3)
    return m[cols].reset_index(drop=True)


def pending_rows(meas: pd.DataFrame) -> pd.DataFrame:
    g = meas[meas["condition"] == "unknown"]
    if g.empty:
        return pd.DataFrame()
    out = g.groupby(["specimen_id", "metric", "abrasion_cycles"])["value"].agg(["count", "mean", "std", "min", "max"]).reset_index()
    return out.rename(columns={"count": "n"})


def summarize(meas: pd.DataFrame, specimens: pd.DataFrame, session: str | None = None, mass: pd.DataFrame | None = None) -> dict:
    session = session or default_session(specimens)
    ca = contact_angle_summary(meas, specimens)
    series = session_series(meas, specimens, session)
    mu = mu_bars(series)
    imp = improvements(series)
    dcof = dcof_series(meas, specimens, session)
    mass_s = mass_summary(mass, session)

    kpi: dict = {}
    coated_ca = ca[ca["label"].str.startswith("코팅")]
    unc_ca = ca[ca["label"].str.startswith("미코팅")]
    if not coated_ca.empty:
        kpi["contact_angle_coated"] = round(float(coated_ca["mean"].iloc[0]), 1)
    if not unc_ca.empty:
        kpi["contact_angle_uncoated"] = round(float(unc_ca["mean"].iloc[0]), 1)
    coat = series[series["coated"]]
    if not coat.empty:
        cmax = int(coat["abrasion_cycles"].max())
        kpi["max_cycles"] = cmax
        for cond in ("dry", "wet"):
            s = coat[coat["condition"] == cond]
            if not s.empty:
                s0, sm = s[s["abrasion_cycles"] == 0], s[s["abrasion_cycles"] == cmax]
                if not s0.empty:
                    kpi[f"mu_{cond}_0"] = float(s0["mu"].iloc[0])
                if not sm.empty:
                    kpi[f"mu_{cond}_max"] = float(sm["mu"].iloc[0])

    if not dcof.empty:
        am = dcof_by_angle_mean(dcof)
        for coated, key in ((True, "coated"), (False, "uncoated")):
            d = am[am["coated"] == coated].sort_values("abrasion_cycles")
            if not d.empty:
                kpi[f"dcof_{key}_0"] = round(float(d["dcof_mean"].iloc[0]), 3)
                kpi[f"dcof_{key}_max"] = round(float(d["dcof_mean"].iloc[-1]), 3)
    pend = pending_rows(meas)
    notes = []
    for _, r in pend.iterrows():
        notes.append(f"{r['abrasion_cycles']}회 마모 {r['metric']} 원자료 {int(r['n'])}회가 건조/습윤 미확인 상태 — 확인 후 조건을 채우면 그래프에 들어간다.")
    single = series[series["n"] == 1]
    if not single.empty:
        notes.append("반복 1회뿐인 지점(" + ", ".join(f"{r['label']} {r['condition']} {r['abrasion_cycles']}회" for _, r in single.iterrows()) + ")은 표준편차를 그릴 수 없다 — 다음 실험에서 3회 반복 권장.")
    if any(not i["same_cycles"] for i in imp):
        notes.append("미코팅 시편이 마모 횟수별로 측정되지 않은 세션은 코팅 마모 후 값을 미코팅 0회와 비교한 것이다 — 같은 마모 횟수의 미코팅 대조군이 있는 10/26 세션 방식이 더 공정한 비교다.")
    notes += [
        "코팅 직후(0회) 습윤 μ가 미코팅보다 낮은 경향은 경화 직후 PU 스킨층이 평활하기 때문 — 제조 공정에 경화 후 표면 활성화 단계를 넣고 0회 값을 다시 측정할 것.",
    ]
    if dcof.empty:
        notes.append("동적 마찰계수(DCOF) 값이 이 세션에는 없다.")
    else:
        if (dcof["condition"] == "unknown").any():
            notes.append("동마찰계수 표에 건조/습윤 조건이 적혀 있지 않다 — 팀 확인 후 condition을 채우면 시판 안전화 Wet DCOF와 직접 비교할 수 있다.")
        notes.append("동마찰계수는 경사판 동적법(경사각 35~50°, 가속도 보정) 값이고 μ는 경사판 정적 값 — 측정 원리가 달라 같은 축에 겹쳐 그리지 않는다(R4). 경사각이 클수록 보정값의 변동이 커지므로 각도별로 따로 본다.")
    return {"session": session, "sessions": sessions(specimens), "contact_angle": ca, "series": series, "mu": mu,
            "dcof": dcof, "dcof_angle_mean": dcof_by_angle_mean(dcof), "mass": mass_s, "kpi": kpi, "improvements": imp, "notes": notes, "pending": pend}


# 하위 호환 (테스트·외부 호출)
def slip_angle_series_default(meas, specimens):
    return session_series(meas, specimens, default_session(specimens))
