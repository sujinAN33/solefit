"""팀 통합본(마찰계수 통합_최종.xlsx) → data/measurements.csv 에 '통합본' 세션 추가, data/mass.csv, DCOF.

실행:  python scripts/import_integrated.py "data/raw/마찰계수 통합_최종.xlsx"

- import_excel.py 가 만든 CSV 위에 세션 '통합본 (팀 확정)'을 덧붙인다 (R5-U-01 / R5-C-01).
- 통합본의 평균·μ·개선율 행은 가져오지 않는다 (앱이 재계산).
- '사포질 횟수별 시편 질량' 표 → data/mass.csv (내마모성 지표).
- '코팅/미코팅 신발 동마찰계수' 블록: 경사판 동적법(경사각 35~50°). 기준값 → metric=dcof_ref, 보정값 → metric=dcof,
  method=incline_dynamic, test_angle_deg=경사각. 건조/습윤이 표에 없어 condition=unknown (팀 확인 후 수정).
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"
SESSION = "통합본 (팀 확정, 10/27)"
FINAL = dict(ratio_50nm=0.75, hdtms_wt_pct=10, silica_pu_solid_ratio=1.0, sonication_min=20, cure_temp_c=70, cure_h=1)
DATE = "2026-10-27"


def first_text(row):
    for c in row[:3]:
        if c is not None:
            return str(c).strip()
    return ""


def main(xlsx: Path):
    ws = openpyxl.load_workbook(xlsx, data_only=True).worksheets[0]
    R = [list(r) for r in ws.iter_rows(values_only=True)]
    n = len(R)

    def find(text, start=0, exact=False):
        for i in range(start, n):
            t = first_text(R[i])
            if (t == text) if exact else (text in t):
                return i
        raise KeyError(text)

    def col0_of(row, label):
        for c, v in enumerate(row):
            if v is not None and str(v).strip() == label:
                return c
        raise KeyError(label)

    def col0(i):
        """'사포질횟수' 행에서 첫 데이터 열 인덱스."""
        return col0_of(R[i], "사포질횟수") + 1

    def repeats(i0, ncols, c0):
        out = [[] for _ in range(ncols)]
        i = i0
        while i < n and "평균" not in first_text(R[i]):
            for c in range(ncols):
                out[c].append(R[i][c0 + c])
            i += 1
        return out

    rows = []

    def add(sid, cond, cyc, vals, metric="slip_angle", method="incline_static", unit="deg", note="", angle=None):
        for k, v in enumerate(vals, 1):
            if v is None or (isinstance(v, str) and not v.strip().replace(".", "").isdigit()):
                continue
            rows.append(dict(specimen_id=sid, metric=metric, method=method, condition=cond, floor="tile",
                             abrasion_cycles=int(cyc), repeat_no=k, agg="raw", n=1, value=float(v), unit=unit,
                             measured_on=DATE, note=note, test_angle_deg=angle))

    for sid, head in (("R5-U-01", "미코팅 신발"), ("R5-C-01", "코팅 신발")):
        i = find(head, exact=True)
        j = find("사포질횟수", i)
        c0 = col0(j)
        cycles = [int(str(c).replace("회", "")) for c in R[j][c0:] if c is not None]
        jd = find("수막형성X", j)
        for cyc, vals in zip(cycles, repeats(jd, len(cycles), c0)):
            add(sid, "dry", cyc, vals)
        jw = find("수막형성O", jd)
        for cyc, vals in zip(cycles, repeats(jw, len(cycles), c0)):
            add(sid, "wet", cyc, vals)

    # ---- 동마찰계수 (경사판 동적법: 경사각 × 마모 횟수, 기준값/보정값)
    n_dcof = 0
    for sid, head in (("R5-C-01", "코팅 신발 동마찰계수"), ("R5-U-01", "미코팅 신발 동마찰계수")):
        try:
            i = find(head, exact=True)
        except KeyError:
            continue
        j = find("경사각", i)
        c0 = col0_of(R[j], "구분") + 1
        cycles = [int(str(c).replace("회", "")) for c in R[j][c0:] if c is not None]
        k = j + 1
        angle = None
        while k < n:
            row = R[k]
            t = first_text(row)
            if t.endswith("°"):
                angle = float(t.replace("°", ""))
            kind = next((str(c).strip() for c in row if c is not None and str(c).strip() in ("기준값", "보정값")), None)
            if kind is None:
                if not any(c is not None for c in row):
                    break
                k += 1
                continue
            metric = "dcof_ref" if kind == "기준값" else "dcof"
            for cyc, v in zip(cycles, row[c0:c0 + len(cycles)]):
                add(sid, "unknown", cyc, [v], metric=metric, method="incline_dynamic", unit="mu",
                    note="경사판 동적법 · 건조/습윤 미기재", angle=angle)
                n_dcof += v is not None and not isinstance(v, str)
            k += 1
    print(f"동마찰계수 {n_dcof}행 (incline_dynamic, condition=unknown — 팀 확인 필요)")

    # ---- 질량
    mass_rows = []
    try:
        i = find("시편 질량")
        j = find("사포질횟수", i)
        c0 = col0(j)
        k = j + 1
        while k < n and first_text(R[k]).endswith("회"):
            cyc = int(first_text(R[k]).replace("회", ""))
            mass_rows.append(dict(session=SESSION, abrasion_cycles=cyc, uncoated_g=R[k][c0], coated_g=R[k][c0 + 3], measured_on="2026-10-26"))
            k += 1
    except KeyError:
        pass
    if mass_rows:
        pd.DataFrame(mass_rows).to_csv(OUT / "mass.csv", index=False, encoding="utf-8-sig")
        print(f"mass.csv {len(mass_rows)}행")

    # ---- CSV 병합 (기존 통합본 세션 행은 교체)
    meas = pd.read_csv(OUT / "measurements.csv", encoding="utf-8-sig")
    meas = meas[~meas["specimen_id"].isin(["R5-U-01", "R5-C-01"])]
    meas = pd.concat([meas, pd.DataFrame(rows)], ignore_index=True)
    meas.to_csv(OUT / "measurements.csv", index=False, encoding="utf-8-sig")

    sp = pd.read_csv(OUT / "specimens.csv", encoding="utf-8-sig")
    sp = sp[~sp["specimen_id"].isin(["R5-U-01", "R5-C-01"])]
    new = pd.DataFrame([
        dict(specimen_id="R5-U-01", experiment_round=5, session=SESSION, substrate="rubber_outsole", coated=False, coat_count=None,
             source="measured", note="미코팅, 사포 0~200회 3회 반복 (8/25·10/26 데이터 통합)"),
        dict(specimen_id="R5-C-01", experiment_round=5, session=SESSION, substrate="rubber_outsole", coated=True, coat_count=2, **FINAL,
             source="measured", note="코팅 최종 시제품, 사포 0~200회 3회 반복 (8/26·10/26 데이터 통합)"),
    ])
    sp = pd.concat([sp, new], ignore_index=True)[sp.columns]
    sp.to_csv(OUT / "specimens.csv", index=False, encoding="utf-8-sig")
    print(f"통합본 세션 {len(rows)}행 추가 → measurements {len(meas)}행, specimens {len(sp)}개")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "raw" / "마찰계수 통합_최종.xlsx")
