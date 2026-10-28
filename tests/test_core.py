"""설계서 10장 테스트 계획 — pytest 또는 `python -m pytest tests/` (pytest 없으면 `python tests/test_core.py`)."""

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import solefit_core as sc  # noqa: E402
from solefit_core.gp import make_synthetic, measured_training_table, _synthetic_truth, CURRENT_OPTIMUM, INPUT_VARS  # noqa: E402


def _data():
    return sc.load_specimens(), sc.load_measurements(), sc.load_claims()


# ---------------------------------------------------------------- 기본 데이터셋
def test_default_dataset_passes():
    sp, me, _ = _data()
    rep = sc.validate(me, sp)
    assert rep.passed, rep.to_frame()
    assert {f.rule_id for f in rep.findings if f.severity in ("info", "warning")} <= {"R1", "R2", "R5"}
    # R5(조건 미확인)는 동마찰계수 행에만 (엑셀에 건조/습윤 미기재)
    dcof_rows = set(me.index[me["metric"].isin(["dcof", "dcof_ref"])])
    assert all(f.row in dcof_rows for f in rep.warnings if f.rule_id == "R5")


# ---------------------------------------------------------------- 골든: 불일치 4건
def test_report_inconsistencies_detected():
    sp, me, cl = _data()
    rep = sc.validate_claims(cl, me)
    err = {f.claim_id: f for f in rep.errors}
    assert set(err) == {"C1", "C2", "C3", "C4"}, err.keys()
    assert err["C1"].rule_id == "R6" and err["C1"].detail["actual"] == 43.8
    assert err["C2"].rule_id == "R6" and err["C2"].detail["actual"] == 29.7
    assert err["C3"].rule_id == "R6" and abs(err["C3"].detail["actual"] - 13.8) < 0.3
    assert err["C4"].rule_id == "R4"
    ok = {f.claim_id for f in rep.findings if f.severity == "info"}
    assert ok == {"C5", "C6"}


# ---------------------------------------------------------------- 규칙별
def _mu_row(me, sid="R3-C-01", cond="wet", cyc=200, rep=1, mu=1.30):
    base = me[(me["specimen_id"] == sid) & (me["metric"] == "slip_angle") & (me["condition"] == cond)
              & (me["abrasion_cycles"] == cyc) & (me["repeat_no"] == rep)].iloc[0].to_dict()
    return {**base, "metric": "static_mu", "unit": "mu", "value": mu}


def test_r1_mu_recalc_pass_and_fail():
    sp, me, _ = _data()
    ang = me[(me["specimen_id"] == "R3-C-01") & (me["metric"] == "slip_angle") & (me["condition"] == "wet")
             & (me["abrasion_cycles"] == 200) & (me["repeat_no"] == 1)]["value"].iloc[0]
    ok = pd.concat([me, pd.DataFrame([_mu_row(me, mu=round(math.tan(math.radians(ang)), 2))])], ignore_index=True)
    assert not [f for f in sc.validate(ok, sp).errors if f.rule_id == "R1"]
    bad = pd.concat([me, pd.DataFrame([_mu_row(me, mu=1.30)])], ignore_index=True)
    r1 = [f for f in sc.validate(bad, sp).errors if f.rule_id == "R1"]
    assert len(r1) == 1 and r1[0].detail["recomputed_mu"] == round(math.tan(math.radians(ang)), 3)


def test_r3_ranges():
    sp, me, _ = _data()
    me = me.copy()
    me.loc[0, "value"] = 190.0
    rep = sc.validate(me, sp)
    assert any(f.rule_id == "R3" and f.row == 0 for f in rep.errors)


def test_r4_dcof_on_incline_rejected():
    sp, me, _ = _data()
    row = me[me["metric"] == "slip_angle"].iloc[-1].copy(); row["metric"] = "dcof"; row["method"] = "incline_static"; row["unit"] = "mu"
    me = pd.concat([me, row.to_frame().T], ignore_index=True)
    me["abrasion_cycles"] = me["abrasion_cycles"].astype(int); me["value"] = me["value"].astype(float); me["n"] = me["n"].astype(int); me["repeat_no"] = me["repeat_no"].astype(int)
    rep = sc.validate(me, sp)
    assert any(f.rule_id == "R4" and "dcof" in f.message for f in rep.errors)


def test_r6_duplicate_conflict():
    sp, me, _ = _data()
    row = me[me["metric"] == "slip_angle"].iloc[-1].copy(); row["agg"] = "mean"; row["n"] = 3; row["repeat_no"] = 1
    row2 = row.copy(); row2["value"] = row["value"] + 5
    me = pd.concat([me, row.to_frame().T, row2.to_frame().T], ignore_index=True)
    me["abrasion_cycles"] = me["abrasion_cycles"].astype(int); me["value"] = me["value"].astype(float); me["n"] = me["n"].astype(int); me["repeat_no"] = me["repeat_no"].astype(int)
    rep = sc.validate(me, sp)
    assert sum(f.rule_id == "R6" for f in rep.errors) == 2


def test_r7_synthetic_blocked():
    sp, me, _ = _data()
    sp = sp.copy(); sp.loc[sp["specimen_id"] == "R3-C-01", "source"] = "synthetic"
    rep = sc.validate(me, sp)
    assert any(f.severity == "block" and f.rule_id == "R7" for f in rep.findings)
    assert not rep.passed


def test_r2_mean_without_raw_warns_only():
    sp, me, _ = _data()
    row = me[me["metric"] == "slip_angle"].iloc[0].copy(); row["agg"] = "mean"; row["n"] = 3; row["abrasion_cycles"] = 999
    me = pd.concat([me, row.to_frame().T], ignore_index=True)
    me["abrasion_cycles"] = me["abrasion_cycles"].astype(int); me["value"] = me["value"].astype(float); me["n"] = me["n"].astype(int); me["repeat_no"] = me["repeat_no"].astype(int)
    rep = sc.validate(me, sp)
    assert rep.passed
    assert len([f for f in rep.warnings if f.rule_id == "R2" and "원값이 없음" in f.message]) == 1


# ---------------------------------------------------------------- 골든: 시나리오 A·B·C
def test_scenario_a_child_sneaker():
    r = sc.assess_safety(sc.SCENARIOS["A — 어린이 운동화"])
    assert r.level == "in_range"
    assert r.inspector == "보호자"
    assert r.formulation_change is False
    assert r.extra_tests == []


def test_scenario_b_senior_daily():
    r = sc.assess_safety(sc.SCENARIOS["B — 고령자 일상화"])
    assert r.level == "in_range"
    assert "복지기관" in r.inspector
    assert any("소재 적합성" in c for c in r.cautions)


def test_scenario_c_crocs():
    r = sc.assess_safety(sc.SCENARIOS["C — 크록스형 신발"])
    assert r.level == "out_of_range"
    assert r.restorable is False
    assert any("접착" in t for t in r.extra_tests) and any("습윤 마찰" in t for t in r.extra_tests)
    assert not any("복원" in c and "가능" in c for c in r.cautions)


def test_shoe_type_crocs_forces_material():
    p = sc.SafetyProfile(age_group="adult", sole_material="rubber", shoe_type="crocs", environment="indoor_wet", wear_state="good")
    assert sc.assess_safety(p).level == "out_of_range"


# ---------------------------------------------------------------- 집계
def test_summary_matches_ppt():
    """8/26 세션 집계가 발표 PPT 값과 일치하는지."""
    sp, me, _ = _data()
    ses = [x for x in sc.sessions(sp) if "8/26" in x][0]
    s = sc.summarize(me, sp, ses)
    assert "8/26" in s["session"]
    assert s["kpi"]["contact_angle_coated"] == 153.9 and s["kpi"]["contact_angle_uncoated"] == 90.5
    assert s["kpi"]["mu_wet_0"] == 0.57 and s["kpi"]["mu_wet_max"] == round(math.tan(math.radians(47.5)), 3)
    assert s["kpi"]["mu_dry_0"] == 0.637 and s["kpi"]["mu_dry_max"] == 1.576
    unc = s["mu"][(s["mu"]["group"] == "미코팅")].set_index("condition")["mu"]
    assert round(unc["dry"], 2) == 0.77 and round(unc["wet"], 2) == 0.96
    wet200 = [i for i in s["improvements"] if i["condition"] == "wet" and i["cycles"] == 200][0]
    assert abs(wet200["pct"] - 13.8) < 0.2


def test_default_is_integrated_session():
    sp, me, _ = _data()
    s = sc.summarize(me, sp, mass=sc.load_mass())
    assert "통합본" in s["session"]
    assert s["kpi"]["mu_wet_max"] == round(math.tan(math.radians(47.5)), 3) and s["kpi"]["mu_dry_max"] == 1.576
    assert all(i["same_cycles"] for i in s["improvements"])        # 미코팅도 마모 횟수별로 있음
    assert len(s["mass"]) == 5 and s["mass"]["coated_loss_pct"].iloc[0] == 0


def test_dcof_incline_dynamic_imported():
    """통합_최종 엑셀의 경사판 동적법 DCOF: 경사각별 보정값이 들어오고 μs 집계와 섞이지 않는다."""
    sp, me, _ = _data()
    d = me[me["metric"] == "dcof"]
    assert len(d) == 32 and set(d["method"]) == {"incline_dynamic"}
    assert set(d["test_angle_deg"].unique()) == {35.0, 40.0, 45.0, 50.0}
    s = sc.summarize(me, sp)
    assert not s["dcof"].empty and "dcof_coated_max" in s["kpi"] and "dcof_uncoated_0" in s["kpi"]
    assert s["kpi"]["mu_wet_max"] == round(math.tan(math.radians(47.5)), 3)   # μs는 DCOF와 섞이지 않음
    am = s["dcof_angle_mean"]
    assert set(am["abrasion_cycles"]) == {0, 50, 100, 150, 200}
    # 코팅 40° 0회 보정값 0.664 (엑셀 원값)
    row = s["dcof"][(s["dcof"]["coated"]) & (s["dcof"]["test_angle_deg"] == 40.0) & (s["dcof"]["abrasion_cycles"] == 0)]
    assert abs(float(row["dcof"].iloc[0]) - 0.664) < 1e-9


def test_r1_flags_dcof_reference_typo():
    sp, me, _ = _data()
    rep = sc.validate(me, sp)
    w = [f for f in rep.warnings if f.rule_id == "R1" and "기준값" in f.message]
    assert any("0.179" in f.message for f in w)          # 미코팅 50° 0회 기준값 0.179 (1.179 오타 추정)
    assert rep.passed                                     # 경고이므로 데이터는 유지


def test_trend_fits_measured_vs_predicted():
    sp, me, _ = _data()
    s = sc.summarize(me, sp)
    f_unc = sc.fit_trend(s["series"], "미코팅", "wet", degree=2, extrapolate_to=250)
    f_coat = sc.fit_trend(s["series"], "코팅", "wet", degree=2, extrapolate_to=250)
    assert f_unc.slope_per_100 < 0 < f_coat.slope_per_100          # 미코팅 저하, 코팅 상승
    assert f_coat.r2 > 0.9 and f_unc.r2 > 0.9
    cv = f_coat.curve
    assert cv["extrapolated"].sum() > 0 and (~cv["extrapolated"]).sum() > 0
    assert (cv[cv["extrapolated"]]["hi"] - cv[cv["extrapolated"]]["lo"]).iloc[-1] > (cv[~cv["extrapolated"]]["hi"] - cv[~cv["extrapolated"]]["lo"]).iloc[0]
    tt = sc.trend_table([f_unc, f_coat])
    assert list(tt["판정"]) == ["저하", "상승"]
    dg = sc.degradation_summary(s["series"])
    assert len(dg) == 4


def test_all_sessions_summarize():
    sp, me, _ = _data()
    assert len(sc.sessions(sp)) == 5
    for ses in sc.sessions(sp):
        s = sc.summarize(me, sp, ses)
        assert not s["series"].empty and not s["mu"].empty
    s4 = sc.summarize(me, sp, [x for x in sc.sessions(sp) if "10/26" in x][0])
    assert all(i["same_cycles"] for i in s4["improvements"])   # 같은 마모 횟수 비교


# ---------------------------------------------------------------- GP
def test_gp_recovers_synthetic_optimum():
    train = make_synthetic(n=40, seed=1)
    model = sc.fit_gp(train, loo=False)
    top, findings = sc.recommend(model, kappa=0.5, k=3, n_candidates=3000)
    best = top.iloc[0]
    truth = _synthetic_truth(pd.DataFrame([CURRENT_OPTIMUM]), "wet_mu")[0]
    assert best["pred_mean"] > 0.8 * truth
    assert best["activation_cycles"] >= 120          # 활성화가 μ를 올린다는 경향을 학습했는지
    assert any(f.rule_id == "R7" for f in findings)  # 가상 데이터 표시


def test_gp_measured_small_sample_warns_r9():
    sp, me, _ = _data()
    train = measured_training_table(sp, me)
    model = sc.fit_gp(train, loo=False)
    top, findings = sc.recommend(model, k=3)
    assert any(f.rule_id == "R9" for f in findings)   # 10행 < 6변수 × 2


def test_gp_refuses_mixed_sources():
    sp, me, _ = _data()
    mixed = pd.concat([make_synthetic(n=8), measured_training_table(sp, me)], ignore_index=True)
    try:
        sc.fit_gp(mixed, loo=False)
    except ValueError as e:
        assert "R7" in str(e)
    else:
        raise AssertionError("mixed sources accepted")


def test_unknown_condition_excluded_from_graphs_and_training():
    sp, me, _ = _data()
    base = me[(me["metric"] == "slip_angle") & (me["specimen_id"] == "R3-C-01")].iloc[-1].to_dict()
    extra = pd.DataFrame([{**base, "condition": "unknown", "abrasion_cycles": 50,
                           "repeat_no": i, "agg": "raw", "n": 1, "value": v, "unit": "deg"} for i, v in enumerate([30, 35, 40, 45, 50], 1)])
    me2 = pd.concat([me, extra], ignore_index=True)
    rep0 = sc.validate(me, sp)
    rep = sc.validate(me2, sp)
    assert rep.passed and sum(f.rule_id == "R5" for f in rep.warnings) == sum(f.rule_id == "R5" for f in rep0.warnings) + 5
    assert any(f.rule_id == "R2" and "CV" in f.message for f in rep.warnings)
    s = sc.summarize(me2, sp)
    assert not s["pending"].empty and int(s["pending"]["n"].iloc[0]) == 5
    assert set(s["series"]["condition"]) == {"dry", "wet"}
    assert len(measured_training_table(sp, me2)) == 10   # unknown 행은 학습에 들어가지 않음 (8/26·10/26 각 5개 마모 지점)


def test_gp_loo_runs():
    model = sc.fit_gp(make_synthetic(n=12), loo=True)
    assert model.loo_rmse == model.loo_rmse and 0 <= model.loo_coverage95 <= 1


if __name__ == "__main__":
    import traceback
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except Exception:
                fails += 1; print("FAIL", name); traceback.print_exc()
    sys.exit(1 if fails else 0)
