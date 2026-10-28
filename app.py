"""SoleFit — 수치 검증 AI 앱 (Streamlit). 실행: streamlit run app.py"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import solefit_core as sc
from solefit_core.gp import (
    INPUT_VARS, VAR_LABEL, TARGETS, DEFAULT_BOUNDS, CURRENT_OPTIMUM,
    make_synthetic, measured_training_table, partial_dependence,
)
from solefit_core.schema import SafetyProfile, DATA_DIR, MEASUREMENT_COLUMNS, SPECIMEN_COLUMNS

st.set_page_config(page_title="SoleFit — 수치 검증 AI", page_icon="🥾", layout="wide")

COLOR = {"dry": "#E4572E", "wet": "#1F4E79", "coat": "#2A9D8F", "unc": "#8D99AE"}
LEVEL_COLOR = {"in_range": "#2A9D8F", "near": "#E9C46A", "out_of_range": "#E76F51"}
SEV_ICON = {"error": "❌", "block": "⛔", "warning": "⚠️", "info": "✅"}

AGE = {"child": "어린이", "adult": "성인", "senior_65_74": "65~74세", "senior_75_plus": "75세 이상"}
MAT = {"rubber": "고무", "eva": "EVA", "tpu": "TPU", "crocs_resin": "크록스형 수지", "unknown": "모름"}
SHOE = {"sneaker": "운동화", "daily": "일상화", "safety": "안전화", "crocs": "크록스형"}
ENV = {"indoor_dry": "실내 건조", "indoor_wet": "실내 젖은 바닥", "bathroom_wet_tile": "욕실·젖은 타일", "kitchen_factory": "주방·식품공장"}
WEAR = {"good": "양호", "partial": "일부 마모", "severe": "홈 마모·심한 마모"}


# ------------------------------------------------------------------ 데이터 (세션 상태)
def _load_default():
    sp, me, cl = sc.load_specimens(), sc.load_measurements(), sc.load_claims()
    return sp, me, cl


if "specimens" not in st.session_state:
    sp, me, cl = _load_default()
    st.session_state.update(specimens=sp, measurements=me, claims=cl, dataset_version=1, uploaded_name=None)
if "mass" not in st.session_state:
    st.session_state.mass = sc.load_mass()

specimens: pd.DataFrame = st.session_state.specimens
mass: pd.DataFrame = st.session_state.mass
meas: pd.DataFrame = st.session_state.measurements
claims: pd.DataFrame = st.session_state.claims
report = sc.validate(meas, specimens)
clean = report.clean_rows(meas)
summary = sc.summarize(clean, specimens, mass=mass)   # 기본 세션 (팀 확정 통합본)
kpi = summary["kpi"]


def badge(severity: str, text: str):
    st.markdown(f"{SEV_ICON.get(severity, '•')} {text}")


def finding_table(rep: sc.ValidationReport, show_info=False):
    df = rep.to_frame()
    if not show_info:
        df = df[df["severity"] != "info"]
    if df.empty:
        st.success("문제 없음")
        return
    df = df.copy()
    df["severity"] = df["severity"].map(lambda s: f"{SEV_ICON[s]} {s}")
    st.dataframe(df, hide_index=True, use_container_width=True)


RULES_PLAIN = [
    ("R1", "μ = tanθ 다시 계산", "미끄러짐 시작각 θ에서 정적 마찰계수를 다시 계산해, 기록된 μ와 0.01 넘게 다르면 오류. 동적법 기준값이 tan(경사각)과 다르면 경고", "오류 / 경고"),
    ("R2", "평균·표준편차 다시 계산", "반복 측정 원값에서 평균과 표준편차를 앱이 직접 계산. 원값 없이 평균만 있으면 경고, 반복 편차가 15%를 넘어도 경고", "오류 / 경고"),
    ("R3", "물리적으로 가능한 범위", "접촉각 0~180°, 시작각 0~90°, 비율·wt%는 0 이상. 벗어나면 입력 실수로 보고 오류", "오류"),
    ("R4", "시험법 섞지 않기", "경사판 정적 μs와 동적 μk(경사판 동적법·마찰시험기)는 다른 값. 지표와 시험법이 맞지 않으면 오류", "오류"),
    ("R5", "같은 조건끼리 비교", "건조/습윤, 마모 횟수, 바닥재가 다르면 비교 결과에 ⚠️ 표시. 조건 미확인 데이터는 그래프에서 제외", "경고"),
    ("R6", "값 충돌 잡기", "같은 시편·조건에 서로 다른 값이 두 개 있으면 오류. 개선율은 기준 시편과 함께 다시 계산", "오류"),
    ("R7", "가상 데이터 격리", "가상(synthetic) 데이터는 실측과 절대 섞이지 않음. 섞으면 차단", "차단"),
    ("R8", "외삽 경고", "AI 추천 후보가 학습 데이터 범위 밖이면 '범위 밖' 표시 — 불확실성이 실제보다 작게 나올 수 있음", "경고"),
    ("R9", "데이터 부족 경고", "학습 행 수가 입력 변수 수 × 2보다 적으면 '신뢰도 낮음' 표시", "경고"),
]


def explain_validator():
    """검증기 설명 블록 — 홈·② 탭·데이터 관리에서 공통으로 사용."""
    st.markdown("""
**검증기는 "사람이 손으로 옮겨 적은 숫자를 믿지 않는다"는 원칙으로 동작합니다.**
엑셀의 반복 측정 **원값만** 받아서 평균·표준편차·마찰계수를 앱이 직접 다시 계산하고, 9가지 규칙으로 걸러낸 뒤에야 그래프와 AI 학습에 씁니다.
""")
    f1, f2, f3, f4 = st.columns(4)
    f1.markdown("**1. 입력**  \n엑셀 → CSV  \n(반복 측정 원값)")
    f2.markdown("**2. 검사**  \n규칙 R1~R9  \n오류 · 경고 · 통과")
    f3.markdown("**3. 확정**  \n오류 0건일 때만  \n새 데이터셋 버전")
    f4.markdown("**4. 사용**  \n그래프(1·2)  \nAI 학습(3)")
    st.markdown("""
| 표시 | 뜻 | 데이터는? |
| --- | --- | --- |
| ❌ 오류 | 계산이 안 맞거나 물리적으로 불가능한 값 | 그래프·학습에서 **제외**, 확정 불가 |
| ⚠️ 경고 | 쓸 수는 있지만 해석에 주의가 필요 | 사용하되 **표시** |
| ✅ 통과 | 재계산 결과가 기록과 일치 | 사용 |
| ⛔ 차단 | 가상 데이터가 실측에 섞임 | 즉시 차단 |
""")
    st.markdown("**규칙 9가지 (쉬운 설명)**")
    st.dataframe(pd.DataFrame(RULES_PLAIN, columns=["규칙", "한 줄 요약", "무엇을 확인하나", "걸리면"]), hide_index=True, use_container_width=True)
    st.latex(r"\mu_s = \tan\theta_{slip} \qquad (\theta_{slip}:\ \text{경사판에서 미끄러지기 시작한 각도})")
    st.caption("예: 47.5°에서 미끄러졌다면 μ = tan 47.5° = 1.09. 기록된 μ가 1.30이면 R1 오류.")


# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    st.title("🥾 SoleFit")
    st.caption("미끄럼 방지 밑창 코팅제 · 수치 검증 AI 프로토타입")
    st.markdown(f"**데이터셋 v{st.session_state.dataset_version}**  \n측정 {len(meas)}행 · 시편 {len(specimens)}개")
    if report.passed:
        st.success(f"검증 통과 · 경고 {len(report.warnings)}건")
    else:
        st.error(f"오류 {len(report.errors)}건 · 경고 {len(report.warnings)}건")
    st.divider()
    st.markdown("**프로토타입 고지**  \n이 앱은 시연용입니다. 추천 배합이 실제로 검증되었다는 뜻이 아니며, 가상 데이터는 실측과 구분해 표시됩니다.")

PAGES = ["홈", "1 · 실제 실험 결과", "2 · 마모 성능 추세", "3 · AI 최적화 데모", "4 · 안전관리 시나리오", "5 · 사회적 파급효과", "데이터 관리"]
page = st.sidebar.radio("화면", PAGES, label_visibility="collapsed")


# ================================================================== 홈
if page == "홈":
    st.title("미끄럼 방지를 위한 수막 차단형 신발 밑창 코팅제")
    st.markdown("PFAS-free 초소수성 · 자가재생형 코팅제의 **실험 수치를 검증**하고, 사용자 조건별 적용 가능성과 **다음 실험 배합**을 제안합니다. (팀 하이젠버그)")
    c1, c2, c3 = st.columns(3)
    c1.metric("정적 접촉각 (코팅)", f"{kpi.get('contact_angle_coated', '—')}°", f"미코팅 {kpi.get('contact_angle_uncoated', '—')}° 대비", delta_color="normal")
    mc = kpi.get("max_cycles", 200)
    c2.metric(f"습윤 정적 μ (0 → {mc}회 마모)", f"{kpi.get('mu_wet_0', '—')} → {kpi.get('mu_wet_max', '—')}", "자가재생: 마모 후 상승")
    c3.metric(f"건조 정적 μ (0 → {mc}회 마모)", f"{kpi.get('mu_dry_0', '—')} → {kpi.get('mu_dry_max', '—')}")
    if "dcof_coated_max" in kpi:
        c4, c5, c6 = st.columns(3)
        c4.metric("동마찰계수 (코팅, 경사각 평균)", f"{kpi['dcof_coated_0']} → {kpi['dcof_coated_max']}", f"0 → {mc}회 마모")
        c5.metric("동마찰계수 (미코팅, 경사각 평균)", f"{kpi['dcof_uncoated_0']} → {kpi['dcof_uncoated_max']}", f"0 → {mc}회 마모")
        c6.metric("검증 데이터", f"{len(clean)}행", f"세션 {len(summary['sessions'])}개 · 규칙 R1~R9")
    st.caption(f"{summary['session']} 세션 · 정마찰계수 μ = tan(미끄럼 시작각), 동마찰계수 = 경사판 동적법(경사각 35~50°) 보정값. 3회 반복 평균.")
    st.divider()
    st.subheader("SoleFit 주요 기능")
    feat = [
        ("📊", "1 · 실제 실험 결과", "코팅·미코팅 시편의 **정마찰계수(경사판 정적)** 와 **동마찰계수(경사판 동적, 경사각별)** 를 같은 조건끼리 나란히 비교합니다.", "모든 값은 반복 측정 원값에서 앱이 다시 계산하고 검증 배지를 붙입니다."),
        ("📈", "2 · 마모 성능 추세", "0~200회 마모에 따른 성능 유지·변화를 보고, **실제 측정값과 회귀 모델 예측값을 구분**해 추세를 분석합니다. 기존 배합이 마모에 따라 어떻게 저하·회복되는지 수치로 보여줍니다.", "예측 구간(95%)과 외삽 구간을 분리해 표시합니다."),
        ("🧠", "3 · AI 최적화 데모", "Gaussian Process 모델이 **다음 시험 조건**을 탐색하는 과정을 시연합니다. 가상 데이터 모드와 실제 데이터 모드를 명확히 구분합니다.", "실험 횟수가 제한된 재료 최적화용 도구입니다."),
        ("🛡️", "4 · 안전관리 시나리오", "**검증된 시험 조건**(고무 아웃솔·타일·사포 마모)과 **실제 적용 대상**(연령·재질·환경·마모)의 차이를 비교해 추가 검증 필요 여부를 판정합니다.", "어린이·고령층은 안내 방식만 바꾸고 배합은 바꾸지 않습니다."),
        ("🤝", "5 · 사회적 파급효과", "어린이·고령층을 위한 **밑창 점검·안전관리 서비스**로 확장될 가능성 — 점검 주기, 점검 주체, 리코팅 연계 흐름을 정리합니다.", "보고서의 RaaS(리코팅 구독) 모델과 연결됩니다."),
    ]
    cards = feat + [("🔍", "공통 기반 · 수치 검증기", "다섯 기능 모두 같은 검증기를 거칩니다. 엑셀의 원값만 받아 앱이 다시 계산하고, 9가지 규칙을 통과한 데이터만 그래프·추세·AI에 씁니다.", "새 실험은 데이터 관리에서 올리면 검증 → 확정 → 갱신이 한 번에 됩니다.")]
    for r in range(0, 6, 3):
        cols = st.columns(3, gap="medium")
        for col, (icon, title, body, foot) in zip(cols, cards[r:r + 3]):
            with col:
                st.markdown(f"""<div style="border:1px solid #D7DCE3;border-radius:10px;padding:14px 16px;margin-bottom:16px;min-height:230px;background:#F8FAFC">
<div style="font-size:26px">{icon}</div>
<h4 style="margin:6px 0 8px 0">{title}</h4>
<p style="margin:0 0 8px 0;line-height:1.55">{body}</p>
<p style="margin:0;color:#5B6472;font-size:0.88em">{foot}</p></div>""".replace("**", ""), unsafe_allow_html=True)
    st.write("")

    with st.expander("🔍 수치 검증기는 어떻게 작동하나요?", expanded=False):
        explain_validator()

    st.subheader("검증기 현황")
    cols = st.columns(3)
    cols[0].metric("오류", len(report.errors))
    cols[1].metric("경고", len(report.warnings))
    cols[2].metric("규칙", "R1 ~ R9")


# ================================================================== 1 · 실제 실험 결과
elif page == "1 · 실제 실험 결과":
    st.title("1 · 실제 실험 결과 — 코팅 vs 미코팅")
    st.caption("팀 엑셀의 반복 측정 원자료. 평균·표준편차·μ는 앱이 다시 계산하고, 모든 값은 수치 검증기(R1~R9)를 거칩니다.")
    ses_list = summary["sessions"]
    ses = st.selectbox("실험 세션", ses_list, index=ses_list.index(summary["session"]) if summary["session"] in ses_list else 0)
    ssum = sc.summarize(clean, specimens, ses, mass=mass)
    series, mu, ca, dcof = ssum["series"], ssum["mu"], ssum["contact_angle"], ssum["dcof"]

    st.subheader("정마찰계수 μs (경사판 정적법, μ = tanθ)")
    g1, g2 = st.columns([3, 2])
    with g1:
        fig = go.Figure()
        for cond in ("dry", "wet"):
            m = mu[mu["condition"] == cond]
            fig.add_bar(x=m["group"], y=m["mu"], name="건조 (Dry)" if cond == "dry" else "습윤 (Wet)", marker_color=COLOR[cond],
                        text=[f"{v:.2f}" for v in m["mu"]], textposition="outside",
                        customdata=m[["n"]].values, hovertemplate="%{x}<br>μs=%{y:.3f} · n=%{customdata[0]}<extra></extra>")
        fig.update_layout(title=f"코팅·미코팅 정마찰계수 — {ses}", yaxis_title="정마찰계수 μs", barmode="group", height=380, legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
    with g2:
        imp = pd.DataFrame(ssum["improvements"])
        if not imp.empty:
            st.markdown("**같은 마모 횟수의 미코팅 대비 코팅 μs 변화율**")
            show = imp.copy()
            show["기준"] = show.apply(lambda r: f"미코팅 {r['baseline_cycles']}회" + ("" if r["same_cycles"] else " ⚠️"), axis=1)
            show["조건"] = show["condition"].map({"dry": "건조", "wet": "습윤"})
            st.dataframe(show.rename(columns={"cycles": "마모", "baseline_mu": "미코팅", "coated_mu": "코팅", "pct": "변화율 %"})[["조건", "마모", "미코팅", "코팅", "변화율 %"]],
                         hide_index=True, use_container_width=True, height=380)

    if not dcof.empty:
        st.subheader("동마찰계수 μk (경사판 동적법 — 경사각별 보정값)")
        st.caption("경사판을 35·40·45·50°로 세워 미끄러지는 가속도로 보정한 동마찰계수. 경사각마다 조건이 달라 각도별로 따로 봅니다. 기준값(tanθ)은 검증기 R1이 확인합니다.")
        angles = sorted(a for a in dcof["test_angle_deg"].dropna().unique())
        pick = st.multiselect("경사각", angles, default=angles, format_func=lambda a: f"{a:.0f}°")
        d = dcof[dcof["test_angle_deg"].isin(pick)]
        fig = go.Figure()
        shade = {35.0: 0.35, 40.0: 0.55, 45.0: 0.75, 50.0: 1.0}
        for (label, coated, ang), g in d.groupby(["label", "coated", "test_angle_deg"], sort=False):
            g = g.sort_values("abrasion_cycles")
            base = COLOR["coat"] if coated else COLOR["unc"]
            fig.add_scatter(x=g["abrasion_cycles"], y=g["dcof"], mode="lines+markers", name=f"{label} {ang:.0f}°",
                            line=dict(color=base, dash="solid" if coated else "dot"), opacity=shade.get(ang, 0.8),
                            marker=dict(size=8, symbol="circle" if coated else "circle-open"),
                            hovertemplate=f"{label} 경사각 {ang:.0f}°<br>마모 %{{x}}회 · μk=%{{y:.3f}}<extra></extra>")
        am = ssum["dcof_angle_mean"]
        for coated, label in ((True, "코팅"), (False, "미코팅")):
            a = am[am["coated"] == coated].sort_values("abrasion_cycles")
            if not a.empty:
                fig.add_scatter(x=a["abrasion_cycles"], y=a["dcof_mean"], mode="lines", name=f"{label} 경사각 평균", line=dict(color=COLOR["coat"] if coated else COLOR["unc"], width=4, dash="solid" if coated else "dot"))
        fig.update_layout(xaxis_title="마모 횟수 (cycle)", yaxis_title="동마찰계수 μk", height=420, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
        k1, k2 = st.columns(2)
        am2 = am.copy(); am2["시편"] = am2["label"]
        with k1:
            st.markdown("**경사각 평균 μk (마모 횟수별)**")
            piv = am2.pivot(index="abrasion_cycles", columns="시편", values="dcof_mean").round(3)
            piv.index.name = "마모 횟수"
            st.dataframe(piv, use_container_width=True)
        with k2:
            st.markdown("**정마찰 vs 동마찰 한눈에 (0회 → 최대 마모)**")
            k = ssum["kpi"]
            st.dataframe(pd.DataFrame({
                "지표": ["정마찰 μs 건조", "정마찰 μs 습윤", "동마찰 μk (경사각 평균)"],
                "코팅": [f"{k.get('mu_dry_0')} → {k.get('mu_dry_max')}", f"{k.get('mu_wet_0')} → {k.get('mu_wet_max')}", f"{k.get('dcof_coated_0')} → {k.get('dcof_coated_max')}"],
                "미코팅": [f"{mu[(mu['group'].str.startswith('미코팅')) & (mu['condition']=='dry')]['mu'].round(3).tolist()}", f"{mu[(mu['group'].str.startswith('미코팅')) & (mu['condition']=='wet')]['mu'].round(3).tolist()}", f"{k.get('dcof_uncoated_0')} → {k.get('dcof_uncoated_max')}"],
            }), hide_index=True, use_container_width=True)
        if (dcof["condition"] == "unknown").any():
            st.info("동마찰계수 표에는 건조/습윤 조건이 적혀 있지 않습니다. 팀 확인 후 condition을 채우면 시판 안전화 Wet DCOF(0.40~0.60)와 직접 비교할 수 있어요.")

    st.subheader("초소수성 — 정적 접촉각")
    fig = go.Figure()
    for _, r in ca.iterrows():
        fig.add_bar(x=[r["label"]], y=[r["mean"]], error_y=dict(type="data", array=[r["std"]]),
                    marker_color=COLOR["coat"] if r["label"].startswith("코팅") else COLOR["unc"],
                    text=[f"{r['mean']:.1f}° (n={r['n']})"], textposition="outside", name=r["label"])
    fig.add_hline(y=150, line_dash="dash", annotation_text="초소수성 기준 150°", line_color="gray")
    fig.update_layout(title="정적 접촉각 (DropSnake, 8/26 시제품)", yaxis_title="접촉각 (°)", yaxis_range=[0, 180], showlegend=False, height=320)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("세션 측정값 표 (평균·표준편차·n·μ)"):
        st.dataframe(series.drop(columns=["estimated_from_graph"]).round(3), hide_index=True, use_container_width=True)
    st.subheader("값별 검증 결과")
    with st.expander("🔍 이 표는 무엇인가요? (검증기 규칙 설명)"):
        explain_validator()
    finding_table(report, show_info=False)


# ================================================================== 2 · 마모 성능 추세
elif page == "2 · 마모 성능 추세":
    st.title("2 · 마모 성능 추세 — 측정값과 예측값")
    st.caption("0~200회 사포 마모에 따른 성능 유지·변화를 보고, 실제 측정값(점)과 회귀 모델 예측(선·띠)을 구분해 추세를 분석합니다.")
    ses_list = summary["sessions"]
    ses = st.selectbox("실험 세션", ses_list, index=ses_list.index(summary["session"]) if summary["session"] in ses_list else 0)
    ssum = sc.summarize(clean, specimens, ses, mass=mass)
    series = ssum["series"]

    c = st.columns([1, 1, 1, 1])
    metric_choice = c[0].selectbox("지표", ["정마찰계수 μs (경사판 정적)", "미끄럼 시작각 θ", "동마찰계수 μk (경사각 평균)"])
    degree = c[1].radio("회귀 모델", [1, 2], index=1, format_func=lambda d: f"{d}차 다항", horizontal=True)
    extrap = c[2].slider("예측 범위 (회)", 200, 300, 250, 10)
    show_band = c[3].checkbox("95% 예측 구간", value=True)

    if metric_choice.startswith("동마찰"):
        am = ssum["dcof_angle_mean"].rename(columns={"dcof_mean": "mu"})
        src = am.assign(condition="angle_mean", std=am["dcof_std"], n=am["n_angles"])
        ycol, ylab, conds = "mu", "동마찰계수 μk (경사각 평균)", ["angle_mean"]
    elif metric_choice.startswith("미끄럼"):
        src, ycol, ylab, conds = series, "slip_angle", "미끄럼 시작각 (°)", ["dry", "wet"]
    else:
        src, ycol, ylab, conds = series, "mu", "정마찰계수 μs", ["dry", "wet"]

    fits = []
    fig = go.Figure()
    for (label, coated), g in src.groupby(["label", "coated"], sort=False):
        for cond in conds:
            gg = g[g["condition"] == cond].sort_values("abrasion_cycles")
            if len(gg) < 2:
                continue
            color = (COLOR["coat"] if coated else COLOR["unc"]) if cond == "angle_mean" else COLOR[cond]
            name = f"{label}" + ("" if cond == "angle_mean" else f" {'건조' if cond == 'dry' else '습윤'}")
            fig.add_scatter(x=gg["abrasion_cycles"], y=gg[ycol], mode="markers", name=f"{name} · 측정", marker=dict(color=color, size=10, symbol="circle" if coated else "circle-open"),
                            error_y=dict(type="data", array=gg["std"].fillna(0), visible=True, thickness=1))
            f = sc.fit_trend(src, label, cond, degree=degree, extrapolate_to=extrap, ycol=ycol)
            if f is None:
                continue
            fits.append(f)
            cv = f.curve
            inside, outside = cv[~cv["extrapolated"]], cv[cv["extrapolated"] | (cv["x"] == cv[~cv["extrapolated"]]["x"].max())]
            if show_band:
                fig.add_scatter(x=pd.concat([cv["x"], cv["x"][::-1]]), y=pd.concat([cv["hi"], cv["lo"][::-1]]), fill="toself",
                                fillcolor=color.replace(")", ",0.10)").replace("rgb", "rgba") if color.startswith("rgb") else color + "1A",
                                line=dict(color="rgba(0,0,0,0)"), showlegend=False, hoverinfo="skip")
            fig.add_scatter(x=inside["x"], y=inside["y_hat"], mode="lines", name=f"{name} · 예측(적합)", line=dict(color=color, width=2, dash="solid" if coated else "dot"))
            if len(outside) > 1:
                fig.add_scatter(x=outside["x"], y=outside["y_hat"], mode="lines", name=f"{name} · 외삽", line=dict(color=color, width=2, dash="dash"), opacity=0.6)
    xmax = float(src["abrasion_cycles"].max()) if not src.empty else 200
    if extrap > xmax:
        fig.add_vrect(x0=xmax, x1=extrap, fillcolor="gray", opacity=0.07, line_width=0, annotation_text="외삽 (측정 범위 밖 · 참고용)", annotation_position="top left")
    fig.update_layout(xaxis_title="마모 횟수 (cycle)", yaxis_title=ylab, height=480, legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("● 측정값(반복 평균 ± 표준편차) · ─ 회귀 적합 · ╌ 외삽 · 띠 = 95% 예측 구간. 외삽은 측정 범위 밖이라 참고용입니다.")

    if fits:
        t1, t2 = st.columns(2)
        with t1:
            st.markdown("**회귀 모델 요약**")
            tt = sc.trend_table(fits)
            tt["조건"] = tt["조건"].map({"dry": "건조", "wet": "습윤", "angle_mean": "경사각 평균"})
            st.dataframe(tt, hide_index=True, use_container_width=True)
        with t2:
            st.markdown("**기존 배합의 마모에 따른 성능 변화 (0회 → 최대 마모)**")
            dg = sc.degradation_summary(src, ycol=ycol)
            dg["조건"] = dg["조건"].map({"dry": "건조", "wet": "습윤", "angle_mean": "경사각 평균"})
            st.dataframe(dg, hide_index=True, use_container_width=True)
        st.markdown("""
**읽는 법** — 미코팅 시편은 마모가 진행될수록 μs가 떨어지는 **저하** 추세이고, 코팅 시편은 0회에서 가장 낮았다가 마모와 함께 **상승**합니다(경화 직후 PU 스킨층이 벗겨지며 내부 개질 실리카가 재노출되는 자가재생 거동).
R²가 높을수록 모델이 측정값을 잘 따라가고, RMSE는 측정값과 예측값의 평균 오차입니다. 외삽 구간의 띠가 급격히 넓어지는 것은 그 영역에 데이터가 없다는 뜻입니다.
""")

    ms = ssum["mass"]
    if not ms.empty:
        st.subheader("내마모성 — 사포질 횟수별 시편 질량 변화")
        fig = go.Figure()
        fig.add_scatter(x=ms["abrasion_cycles"], y=ms["coated_loss_pct"], mode="lines+markers", name="코팅", line=dict(color=COLOR["coat"]))
        fig.add_scatter(x=ms["abrasion_cycles"], y=ms["uncoated_loss_pct"], mode="lines+markers", name="미코팅", line=dict(color=COLOR["unc"], dash="dot"))
        fig.add_hline(y=0, line_color="gray", line_width=1)
        fig.update_layout(xaxis_title="마모 횟수 (cycle)", yaxis_title="질량 감소율 (%, 0회 대비)", height=300)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("양수 = 질량 감소(마모). 200회에서 두 시편 모두 질량이 늘어난 것은 측정 전 수분·사포 가루 등 외부 요인 가능성 — 팀 확인 필요.")

    st.subheader("다음 실험에서 개선할 점")
    for n_ in ssum["notes"]:
        st.markdown(f"- {n_}")


# ================================================================== 3 · AI 최적화 데모
elif page == "3 · AI 최적화 데모":
    st.title("3 · AI 최적화 데모 — 다음 시험 조건 탐색")
    st.markdown("실험 횟수가 제한된 재료 최적화에서 **다음에 어떤 배합·공정 조건을 시험해야 할지** 최적화 모델이 후보를 탐색하는 과정을 보여줍니다.")

    with st.expander("🧠 AI는 어떻게 추천하나요? (Gaussian Process · UCB)", expanded=False):
        e1, e2, e3 = st.columns(3)
        e1.markdown("**1. 지금까지의 실험을 학습**  \n6가지 배합·공정 변수 → 결과(습윤 μ 또는 접촉각)의 관계를 Gaussian Process 회귀로 학습합니다. 데이터가 몇 십 개뿐이어도 쓸 수 있는 방법입니다.")
        e2.markdown("**2. 예측값 + 불확실성**  \n보통의 AI는 '예측값' 하나만 주지만, GP는 **'얼마나 자신 없는지(σ)'** 도 같이 줍니다. 실험해 본 적 없는 영역일수록 σ가 큽니다.")
        e3.markdown("**3. 시험할 가치가 큰 후보 선택**  \n후보 2,000개를 만들어 **UCB = 예측값 + κ×σ** 가 큰 순서로 고릅니다. κ가 크면 '모르는 영역을 탐험', 작으면 '잘 아는 영역을 활용'합니다.")
        st.latex(r"\mathrm{UCB}(x) = \hat{\mu}(x) + \kappa\,\hat{\sigma}(x)")
        st.caption("κ(카파)는 아래 '탐색 강도' 슬라이더로 조절합니다. 기본값 2.0.")

    # ---------------- 모드 선택 (강조 카드)
    st.markdown("#### 어떤 데이터로 추천받을까요?")
    mode = st.radio("모드", ["🧪 가상 데이터로 시연", "🔬 실제 실험 데이터로 추천"], horizontal=True, label_visibility="collapsed")
    synthetic = mode.startswith("🧪")
    card_l, card_r = st.columns(2)
    on, off = "#1F4E79", "#B0B7C3"
    with card_l:
        c = on if synthetic else off
        st.markdown(f"""<div style="border:3px solid {c};border-radius:10px;padding:14px 16px;background:{c}14;height:100%">
<h4 style="margin:0 0 6px 0;color:{c}">🧪 가상 데이터로 시연 {'◀ 선택됨' if synthetic else ''}</h4>
<ul style="margin:0;padding-left:18px;line-height:1.7">
<li><b>목적</b>: AI 알고리즘이 어떻게 작동하는지 보여주기</li>
<li><b>데이터</b>: 컴퓨터가 만든 가상 실험값 (실제 측정 아님)</li>
<li><b>결과의 의미</b>: 추천 배합은 <b>실제 최적 배합이 아님</b></li>
<li><b>언제 쓰나</b>: 대회 시연, 알고리즘 설명</li>
</ul></div>""", unsafe_allow_html=True)
    with card_r:
        c = on if not synthetic else off
        st.markdown(f"""<div style="border:3px solid {c};border-radius:10px;padding:14px 16px;background:{c}14;height:100%">
<h4 style="margin:0 0 6px 0;color:{c}">🔬 실제 실험 데이터로 추천 {'◀ 선택됨' if not synthetic else ''}</h4>
<ul style="margin:0;padding-left:18px;line-height:1.7">
<li><b>목적</b>: 다음 실험에서 시험할 배합 후보 받기</li>
<li><b>데이터</b>: 검증기를 통과한 팀의 실측값 (8/26·10/26 세션)</li>
<li><b>결과의 의미</b>: 실제 데이터 기반이지만 <b>배합이 1종뿐이라 아직 참고용</b></li>
<li><b>언제 쓰나</b>: 배합을 바꾼 실험이 8~12개 이상 쌓인 뒤</li>
</ul></div>""", unsafe_allow_html=True)
    st.write("")

    c = st.columns([1, 1, 1])
    target = c[0].selectbox("목표 지표 (무엇을 높일까요?)", list(TARGETS), format_func=TARGETS.get)
    kappa = c[1].slider("탐색 강도 κ  (작게: 아는 영역 활용 ↔ 크게: 새 영역 탐험)", 0.0, 4.0, 2.0, 0.5)
    k = c[2].slider("추천 후보 수", 1, 10, 5)

    with st.expander("탐색 범위 (임시 값 — 화공 팀원이 실험 가능 범위로 확정)"):
        bounds = {}
        bc = st.columns(3)
        for i, v in enumerate(INPUT_VARS):
            lo, hi = DEFAULT_BOUNDS[v]
            step = 1 if v in ("coat_count", "activation_cycles") else (0.05 if v == "ratio_50nm" else 0.5)
            lo2, hi2 = bc[i % 3].slider(VAR_LABEL[v], float(lo if v != "activation_cycles" else 0), float(hi if v != "activation_cycles" else 400), (float(lo), float(hi)), float(step))
            bounds[v] = (lo2, hi2)

    if synthetic:
        st.warning("🧪 **가상 데이터 모드** — 아래 결과는 알고리즘 작동 시연용입니다. 실제 최적 배합이 아니며, 실측 데이터를 충분히 확보한 뒤 다시 학습해야 합니다.")
        n_syn = st.slider("가상 실험 수", 8, 60, 24)
        train = make_synthetic(n=n_syn, target=target, bounds=bounds)
    else:
        st.success("🔬 **실제 데이터 모드** — 검증기를 통과한 실측 데이터로만 학습합니다. 가상 데이터는 섞이지 않습니다(R7).")
        up = st.file_uploader("배합을 바꾼 새 실험 CSV 업로드 (specimens.csv 형식 + 목표 컬럼)", type="csv")
        if up is not None:
            train = pd.read_csv(up)
            train["source"] = "measured"
            if target not in train.columns:
                st.error(f"CSV에 '{target}' 컬럼이 필요합니다. 컬럼: {INPUT_VARS + [target]}")
                st.stop()
        else:
            train = measured_training_table(specimens, clean, target=target)
            st.info(f"업로드가 없으면 확정 실측 데이터셋(8/26·10/26 세션)에서 학습합니다 — 코팅 시편 {train['specimen_id'].nunique()}종, 마모 지점 {len(train)}행. "
                    "통합본 세션은 같은 측정의 재편집이라 중복 학습을 피해 제외합니다. 지금은 배합이 한 가지뿐이라 AI가 '마모 횟수'의 영향만 배울 수 있고, 배합 변수의 추천은 참고용입니다.")

    if st.button("GP 모델 학습 · 후보 계산", type="primary"):
        with st.spinner("학습 중..."):
            model = sc.fit_gp(train, target=target, bounds=bounds)
            top, findings = sc.recommend(model, kappa=kappa, k=k)
        st.session_state.gp = (model, top, findings, target)

    if "gp" in st.session_state and st.session_state.gp[3] == target:
        model, top, findings, _ = st.session_state.gp
        for f in findings:
            badge(f.severity, f.message)
        m1, m2, m3 = st.columns(3)
        m1.metric("학습 행 수", model.n_train, "가상" if model.source == "synthetic" else "실측")
        m2.metric("LOO RMSE", f"{model.loo_rmse:.3f}" if model.loo_rmse == model.loo_rmse else "—")
        m3.metric("95% 구간 포함률 (LOO)", f"{model.loo_coverage95:.0%}" if model.loo_coverage95 == model.loo_coverage95 else "—")

        st.subheader(("🧪 추천 후보 (가상 데이터 — 시연용)" if model.source == "synthetic" else "🔬 추천 후보 (실제 실험 데이터)"))
        show = top.copy()
        show["pred"] = [f"{m:.3f} ± {s:.3f}" for m, s in zip(show["pred_mean"], show["pred_std"])]
        show["외삽"] = show["extrapolated"].map({True: "⚠️ 범위 밖", False: ""})
        show["ratio_50nm"] = show["ratio_50nm"].round(2)
        show["hdtms_wt_pct"] = show["hdtms_wt_pct"].round(1)
        show["silica_pu_solid_ratio"] = show["silica_pu_solid_ratio"].round(2)
        show["sonication_min"] = show["sonication_min"].round(0)
        cols = ["rank"] + INPUT_VARS + ["pred", "외삽"]
        st.dataframe(show[cols].rename(columns={**VAR_LABEL, "rank": "순위", "pred": f"예측 {TARGETS[target]} ± σ"}), hide_index=True, use_container_width=True)
        st.caption(f"데이터 출처: **{model.source}** · 현 최적점: 50 nm 비율 0.75 · HDTMS 10 wt% · 실리카:PU 1:1 · 초음파 20분 · 도포 2회")
        out = top.copy(); out["source"] = model.source
        st.download_button("추천 후보 CSV 내보내기", out.to_csv(index=False).encode("utf-8-sig"), f"recommendations_{model.source}.csv", "text/csv")

        st.subheader("부분 의존 그래프 (다른 변수는 현 최적점에 고정)")
        pv = st.selectbox("변수", INPUT_VARS, format_func=VAR_LABEL.get)
        pdp = partial_dependence(model, pv)
        fig = go.Figure()
        fig.add_scatter(x=pd.concat([pdp[pv], pdp[pv][::-1]]), y=pd.concat([pdp["pred_mean"] + 1.96 * pdp["pred_std"], (pdp["pred_mean"] - 1.96 * pdp["pred_std"])[::-1]]),
                        fill="toself", fillcolor="rgba(31,78,121,0.15)", line=dict(color="rgba(0,0,0,0)"), name="95% 구간")
        fig.add_scatter(x=pdp[pv], y=pdp["pred_mean"], line=dict(color=COLOR["wet"]), name="예측 평균")
        tr = model.train
        fig.add_scatter(x=tr[pv], y=tr[target], mode="markers", marker=dict(color=COLOR["dry"], size=8), name=f"학습 데이터 ({model.source})")
        fig.update_layout(xaxis_title=VAR_LABEL[pv], yaxis_title=TARGETS[target], height=380)
        st.plotly_chart(fig, use_container_width=True)


# ================================================================== 4 · 안전관리 시나리오
elif page == "4 · 안전관리 시나리오":
    st.title("4 · 안전관리 시나리오 — 검증된 조건 vs 실제 적용 대상")
    st.caption("실험으로 검증된 시험 조건과 실제 적용 대상의 차이를 비교해, 지금 데이터로 안내할 수 있는지 아니면 추가 검증이 필요한지 판정합니다. 연령은 안내 방식만 바꾸고 화학 배합은 바꾸지 않습니다.")
    with st.expander("✅ 지금까지 검증된 시험 조건", expanded=False):
        st.dataframe(pd.DataFrame({
            "항목": ["기재(밑창 재질)", "바닥재", "수막 조건", "마모 방식", "측정 지표", "배합"],
            "검증된 조건": ["고무 아웃솔(러닝화), 고무판", "타일", "건조 / 분무 습윤", "사포 0~200회", "정마찰 μs(경사판), 동마찰 μk(경사판 동적), 접촉각", "500/50 nm 실리카 1:3, HDTMS 10 wt%, 실리카:PU 1:1, 브러시 2회, 70 °C 경화"],
            "검증되지 않은 것": ["EVA, TPU, 크록스형 발포 수지", "세제·유분 바닥, 금속 바닥", "세제 수막, 유분 수막", "실제 보행 마모, 굽힘 피로", "장기 내구(수개월), 마찰시험기 DCOF", "다른 배합"],
        }), hide_index=True, use_container_width=True)

    if "profile" not in st.session_state:
        st.session_state.profile = sc.SCENARIOS["A — 어린이 운동화"].model_dump()
    bcols = st.columns(3)
    for i, (name, prof) in enumerate(sc.SCENARIOS.items()):
        if bcols[i].button(f"시나리오 {name} 불러오기", use_container_width=True):
            st.session_state.profile = prof.model_dump()
    p = st.session_state.profile

    with st.form("safety_form"):
        c = st.columns(5)
        age = c[0].selectbox("연령대", list(AGE), index=list(AGE).index(p["age_group"]), format_func=AGE.get)
        mat = c[1].selectbox("밑창 재질", list(MAT), index=list(MAT).index(p["sole_material"]), format_func=MAT.get)
        shoe = c[2].selectbox("신발 종류", list(SHOE), index=list(SHOE).index(p["shoe_type"]), format_func=SHOE.get)
        env = c[3].selectbox("사용 환경", list(ENV), index=list(ENV).index(p["environment"]), format_func=ENV.get)
        wear = c[4].selectbox("마모 상태", list(WEAR), index=list(WEAR).index(p["wear_state"]), format_func=WEAR.get)
        run = st.form_submit_button("판정", type="primary")
    if run:
        st.session_state.profile = dict(age_group=age, sole_material=mat, shoe_type=shoe, environment=env, wear_state=wear)
        p = st.session_state.profile

    prof = SafetyProfile(**p)
    res = sc.assess_safety(prof, evidence=kpi)
    color = LEVEL_COLOR[res.level]
    st.markdown(f"""<div style="border-left:8px solid {color};padding:12px 16px;background:{color}22;border-radius:6px">
<h3 style="margin:0;color:{color}">{res.level_label}</h3>
<p style="margin:4px 0 0 0">{' · '.join(res.reasons)}</p></div>""", unsafe_allow_html=True)
    st.write("")
    a, b = st.columns(2)
    with a:
        st.markdown("**점검 방법**")
        st.markdown(f"- 점검 주체: **{res.inspector}**\n- {res.inspection_path}")
        st.markdown("**주의 사항**")
        for cau in res.cautions:
            st.markdown(f"- {cau}")
        if not res.restorable:
            st.error("심하게 닳은 밑창은 코팅으로 복원할 수 없습니다. 교체를 권장합니다.")
    with b:
        st.markdown("**근거 실측값 (고무 아웃솔, 팀 확정 통합본)**")
        st.dataframe(pd.DataFrame({
            "지표": ["접촉각", "습윤 μs (0회)", f"습윤 μs ({kpi.get('max_cycles', 200)}회 마모)", "건조 μs (0회)", f"건조 μs ({kpi.get('max_cycles', 200)}회 마모)", "동마찰 μk 경사각 평균 (0회 → 최대)"],
            "값": [f"{kpi.get('contact_angle_coated')}°", kpi.get("mu_wet_0"), kpi.get("mu_wet_max"), kpi.get("mu_dry_0"), kpi.get("mu_dry_max"), f"{kpi.get('dcof_coated_0', '—')} → {kpi.get('dcof_coated_max', '—')}"],
        }), hide_index=True, use_container_width=True)
        if res.extra_tests:
            st.markdown("**추천 전에 필요한 추가 시험**")
            for t in res.extra_tests:
                st.markdown(f"- [ ] {t}")
        else:
            st.markdown("**추가 시험**: 없음 (검증 범위 내)")
        st.caption(f"배합 변경: {'있음' if res.formulation_change else '없음 — 연령은 안내 방식만 바꿉니다'}")




# ================================================================== 5 · 사회적 파급효과
elif page == "5 · 사회적 파급효과":
    st.title("5 · 사회적 파급효과 — 어린이·고령층 밑창 점검·안전관리 서비스")
    st.markdown("""
넘어짐은 산업재해 사고 중 가장 많은 유형(2026년 1분기 7,216명, 26.4%)이고, 가정에서는 **어린이와 고령층**이 욕실·젖은 바닥에서 가장 자주 다칩니다.
SoleFit의 안전관리 시나리오(4)는 코팅 제품을 파는 도구가 아니라, **"지금 신고 있는 신발의 밑창이 안전한가"를 누구나 점검할 수 있게 하는 서비스**의 출발점입니다.
""")
    s1, s2, s3 = st.columns(3)
    cards = [
        (s1, "👶", "어린이 — 보호자 중심 점검", ["운동화 밑창 마모·코팅 상태를 보호자가 주 1회 눈으로 확인", "앱 체크리스트(홈 마모 · 젖은 바닥 미끄러짐 경험 · 밑창 재질)", "어린이라는 이유로 배합을 바꾸지 않고, 안내 방식만 보호자 중심으로"]),
        (s2, "👵", "고령층 — 복지기관 연계", ["75세 이상은 점검 결과를 보호자·노인복지관·방문요양을 통해 확인", "욕실·젖은 타일 환경은 실험 조건(타일 습윤)과 같아 현재 데이터로 안내 가능", "세제 수막 등 미검증 조건은 추가 시험 항목으로 자동 표시"]),
        (s3, "🏭", "습윤 작업장 — 안전관리자", ["조리실·식품공장·병원·세차장 근로자 안전화를 월 1회 점검 기록", "마모 횟수별 μs·μk 추세(2)로 교체·리코팅 시점 예측", "보고서의 리코팅 구독(RaaS) 모델과 연결"]),
    ]
    for col, icon, title, items in cards:
        with col:
            st.markdown(f"""<div style="border:1px solid #D7DCE3;border-radius:10px;padding:14px 16px;height:100%;background:#F8FAFC">
<div style="font-size:26px">{icon}</div><h4 style="margin:6px 0 8px 0">{title}</h4>
<ul style="margin:0;padding-left:18px;line-height:1.6">{''.join(f'<li>{i}</li>' for i in items)}</ul></div>""", unsafe_allow_html=True)
    st.write("")
    st.subheader("서비스 흐름 (프로토타입 → 확장)")
    f1, f2, f3, f4, f5 = st.columns(5)
    for col, step, body in ((f1, "① 입력", "연령·재질·환경·마모 상태 (현재 앱)"), (f2, "② 판정", "검증 범위 내 / 근접 / 범위 밖 (현재 앱)"),
                            (f3, "③ 점검 경로", "본인 · 보호자 · 복지기관 · 안전관리자 (현재 앱)"), (f4, "④ 사진 진단", "스마트폰 촬영으로 마모도 분석 (향후, 보고서 AI 비전)"),
                            (f5, "⑤ 리코팅 연계", "수거 → 리코팅 → 재배송, D-15 알림 (향후, RaaS)")):
        col.markdown(f"**{step}**  \n{body}")
    st.markdown("""
**지금 데이터로 말할 수 있는 것과 없는 것**

| 말할 수 있는 것 (검증됨) | 아직 말할 수 없는 것 (추가 검증 필요) |
| --- | --- |
| 고무 밑창 + 타일 + 습윤 조건에서 코팅이 마모 후에도 정마찰계수를 유지·상승 | EVA·TPU·크록스형 밑창에서의 효과 |
| 사포 200회 마모까지의 추세 | 실제 보행 수개월의 장기 내구 |
| 어린이·고령층 모두 **점검 경로**는 지금 바로 안내 가능 | 세제·유분 수막, 금속·목재 바닥 |
| 심하게 닳은 밑창은 코팅으로 복원되지 않는다는 안내 | 시판 안전화 DCOF와의 동일 조건 비교 |

이 구분을 앱이 자동으로 표시하기 때문에, 서비스로 확장해도 **검증되지 않은 안전 보장을 하지 않는다**는 점이 사회적 신뢰의 기반이 됩니다.
""")


# ================================================================== 데이터 관리
elif page == "데이터 관리":
    st.title("데이터 관리")
    st.caption("화공 팀원용. 팀 엑셀 양식이면 `python scripts/import_excel.py` → `python scripts/import_integrated.py` 순으로 CSV를 다시 만들 수 있고, 아래 템플릿에 직접 입력해 업로드해도 됩니다. 확정하면 새 데이터셋 버전이 됩니다.")

    t1, t2 = st.columns(2)
    t1.download_button("measurements.csv 템플릿", pd.DataFrame(columns=MEASUREMENT_COLUMNS).to_csv(index=False).encode("utf-8-sig"), "measurements_template.csv", "text/csv")
    t2.download_button("specimens.csv 템플릿", pd.DataFrame(columns=SPECIMEN_COLUMNS).to_csv(index=False).encode("utf-8-sig"), "specimens_template.csv", "text/csv")

    st.subheader("1. 업로드")
    u1, u2 = st.columns(2)
    up_m = u1.file_uploader("measurements.csv", type="csv", key="up_m")
    up_s = u2.file_uploader("specimens.csv (선택)", type="csv", key="up_s")

    if up_m is not None:
        new_meas = sc.load_measurements(io.BytesIO(up_m.getvalue()))
        new_sp = sc.load_specimens(io.BytesIO(up_s.getvalue())) if up_s is not None else specimens
        st.subheader("2. 검증 결과")
        new_rep = sc.validate(new_meas, new_sp)
        a, b, c = st.columns(3)
        a.metric("오류", len(new_rep.errors)); b.metric("경고", len(new_rep.warnings)); c.metric("행", len(new_meas))
        finding_table(new_rep)
        st.dataframe(new_meas, use_container_width=True, height=260)
        st.subheader("3. 확정")
        if new_rep.passed:
            if st.button("이 데이터로 확정 (새 버전)", type="primary"):
                st.session_state.measurements = new_meas
                st.session_state.specimens = new_sp
                st.session_state.dataset_version += 1
                st.session_state.uploaded_name = up_m.name
                st.session_state.pop("gp", None)
                st.success(f"데이터셋 v{st.session_state.dataset_version}로 확정되었습니다. 1·2·3 화면이 새 버전으로 갱신됩니다.")
                st.rerun()
        else:
            st.error("오류가 있는 동안에는 확정할 수 없습니다. 표시된 행을 수정해 다시 업로드하세요.")
    else:
        st.subheader("현재 확정 데이터셋")
        st.markdown(f"v{st.session_state.dataset_version}" + (f" · {st.session_state.uploaded_name}" if st.session_state.uploaded_name else " · 기본 (팀 엑셀 + 통합_최종 10/28 반입, 세션 5개, 동마찰계수 포함)"))
        st.markdown("**검증 리포트 (규칙별 건수)**")
        st.dataframe(pd.DataFrame([{"규칙": k, "건수": v} for k, v in sorted(report.by_rule().items())]), hide_index=True)
        with st.expander("measurements.csv"):
            st.dataframe(meas, use_container_width=True)
        with st.expander("specimens.csv"):
            st.dataframe(specimens, use_container_width=True)
        if st.button("기본 데이터셋으로 되돌리기"):
            sp, me, cl = _load_default()
            st.session_state.update(specimens=sp, measurements=me, claims=cl, dataset_version=1, uploaded_name=None)
            st.session_state.pop("gp", None)
            st.rerun()
