"""팀 엑셀(마찰계수 내마모성 검증데이터.xlsx) → data/specimens.csv, data/measurements.csv

실행:  python scripts/import_excel.py "data/raw/마찰계수 내마모성 검증데이터.xlsx"

엑셀의 블록 구조(셀 위치가 아니라 제목 문구)를 따라 읽으므로, 같은 양식이면 행이 늘어나도 된다.
- 반복 측정값만 agg=raw 로 넣는다. 엑셀의 평균·μ·개선율 행은 앱이 다시 계산하므로 가져오지 않는다.
- 접촉각(발표 PPT 18p)은 엑셀에 없어 그대로 유지한다.
- 건너뛰는 블록: "마찰계수" 5° 간격 표(측정값 아님 — 팀 확인), "시편 질량" 표(스키마에 질량 지표 없음).
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"

# 최종 배합 (과제보고서) — 8/26·10/26 코팅 시편에 적용. 초기·8/25 시편은 배합 미기재.
FINAL = dict(ratio_50nm=0.75, hdtms_wt_pct=10, silica_pu_solid_ratio=1.0, sonication_min=20, cure_temp_c=70, cure_h=1)

SPECIMENS = [
    # id, round, session, substrate, coated, coat_count, formulation, note
    ("R2-U-00", 2, "초기 (브러시 1·2회 비교)", "rubber_outsole", False, None, {}, "코팅 x. 사포질 없음. 날짜 미기재 (과제보고서 2차 실험 8/14 추정)"),
    ("R2-C-B1", 2, "초기 (브러시 1·2회 비교)", "rubber_outsole", True, 1, {}, "브러시 1회 코팅. 배합 미기재"),
    ("R2-C-B2", 2, "초기 (브러시 1·2회 비교)", "rubber_outsole", True, 2, {}, "브러시 2회 코팅. 배합 미기재. 사포 20~100회 습윤 1회 측정 포함"),
    ("R3A-U-00", 3, "8/25", "rubber_outsole", False, None, {}, "미코팅, 사포질 X"),
    ("R3A-U-S", 3, "8/25", "rubber_outsole", False, None, {}, "미코팅, 사포질 O (횟수 미기재 → abrasion_cycles=0 으로 기록)"),
    ("R3A-C-01", 3, "8/25", "rubber_outsole", True, 2, {}, "코팅, 사포 0~100회(20회 간격). 배합 미기재"),
    ("R3-U-01", 3, "8/26 (3차 최종검증, 발표 기준)", "rubber_outsole", False, None, {}, "미코팅 대조군 (사포질 O, 횟수 미기재)"),
    ("R3-C-01", 3, "8/26 (3차 최종검증, 발표 기준)", "rubber_outsole", True, 2, FINAL, "최종 시제품 (브러시 2회 코팅, 70°C 열풍 1h, 상온 안정화 12h). 0회는 원본에 값 1개만 기록"),
    ("R4-U-01", 4, "10/26 (4차)", "rubber_outsole", False, None, {}, "미코팅, 사포 0~250회. 0·50·100회는 값 1개"),
    ("R4-C-01", 4, "10/26 (4차)", "rubber_outsole", True, 2, FINAL, "코팅, 사포 0~200회, 3회 반복"),
]

rows: list[dict] = []


def add(sid, cond, cycles, values, date, note="", method="incline_static", metric="slip_angle", floor="tile"):
    for i, v in enumerate(values, 1):
        if v is None:
            continue
        rows.append(dict(specimen_id=sid, metric=metric, method=method, condition=cond, floor=floor,
                         abrasion_cycles=int(cycles), repeat_no=i, agg="raw", n=1, value=float(v), unit="deg",
                         measured_on=date, note=note))


def first_text(row):
    return str(row[0]).strip() if row and row[0] is not None else ""


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

    def repeats(i0, ncols, col0=1):
        """i0부터 '평균' 행 전까지의 반복값을 열별로 모은다."""
        out = [[] for _ in range(ncols)]
        i = i0
        while i < n and "평균" not in first_text(R[i]):
            for c in range(ncols):
                out[c].append(R[i][col0 + c])
            i += 1
        return out

    # ---------------- 초기: 건조 / 습윤, 코팅x·브러시1·브러시2 × 5회
    for cond, head in (("dry", "1) 건조 환경"), ("wet", "2) 습윤 환경")):
        i = find(head) + 2
        cols = repeats(i, 3)
        for sid, vals in zip(("R2-U-00", "R2-C-B1", "R2-C-B2"), cols):
            add(sid, cond, 0, vals, "", "초기 실험, 날짜 미기재")
    i = find("3) 브러쉬 2회") + 2
    while i < n and first_text(R[i]).startswith("사포"):
        cyc = int(first_text(R[i]).replace("사포", "").replace("회", ""))
        add("R2-C-B2", "wet", cyc, [R[i][1]], "", "초기 실험, 1회 측정")
        i += 1

    # ---------------- 8/25
    i = find("검증데이터 8/25")
    j = find("수막형성X", i)
    dryv = repeats(j, 2)
    add("R3A-U-00", "dry", 0, dryv[0], "2026-08-25", "사포질 X")
    add("R3A-U-S", "dry", 0, dryv[1], "2026-08-25", "사포질 O, 횟수 미기재")
    j = find("수막형성O", j)
    wetv = repeats(j, 2)
    add("R3A-U-00", "wet", 0, wetv[0], "2026-08-25", "사포질 X")
    add("R3A-U-S", "wet", 0, wetv[1], "2026-08-25", "사포질 O, 횟수 미기재")
    j = find("코팅 신발", i, exact=True)
    cycles = [int(str(c).replace("회", "")) for c in R[j + 1][1:] if c is not None]
    j2 = find("수막형성X", j)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R3A-C-01", "dry", cyc, vals, "2026-08-25")
    j2 = find("수막형성O", j2)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R3A-C-01", "wet", cyc, vals, "2026-08-25")

    # ---------------- 8/26
    i = find("검증데이터 8/26")
    j = find("수막형성X", i)
    add("R3-U-01", "dry", 0, repeats(j, 1)[0], "2026-08-26", "사포질 O, 횟수 미기재")
    j = find("수막형성O", j)
    add("R3-U-01", "wet", 0, repeats(j, 1)[0], "2026-08-26", "사포질 O, 횟수 미기재")
    j = find("코팅 신발", i, exact=True)
    cycles = [int(str(c).replace("회", "")) for c in R[j + 1][1:] if c is not None]
    j2 = find("수막형성X", j)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R3-C-01", "dry", cyc, vals, "2026-08-26", "0회는 원본에 값 1개" if cyc == 0 else "")
    j2 = find("수막형성O", j2)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R3-C-01", "wet", cyc, vals, "2026-08-26", "0회는 원본에 값 1개" if cyc == 0 else "")

    # ---------------- 10/26
    i = find("검증데이터 10/26")
    j = find("미코팅 신발", i, exact=True)
    cycles = [int(str(c).replace("회", "")) for c in R[j + 1][1:] if c is not None]
    j2 = find("수막형성X", j)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R4-U-01", "dry", cyc, vals, "2026-10-26")
    j2 = find("수막형성O", j2)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R4-U-01", "wet", cyc, vals, "2026-10-26")
    j = find("코팅 신발", i, exact=True)
    cycles = [int(str(c).replace("회", "")) for c in R[j + 1][1:] if c is not None]
    j2 = find("수막형성X", j)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R4-C-01", "dry", cyc, vals, "2026-10-26")
    j2 = find("수막형성O", j2)
    for cyc, vals in zip(cycles, repeats(j2, len(cycles))):
        add("R4-C-01", "wet", cyc, vals, "2026-10-26")

    # ---------------- 접촉각 (PPT 18p) — 엑셀에 없음
    add("R3-U-01", "dry", 0, [95.6, 85.4], "2026-08-26", "PPT 18p", method="dropsnake", metric="contact_angle", floor="none")
    add("R3-C-01", "dry", 0, [156.3, 153.3, 152.0], "2026-08-26", "PPT 18p", method="dropsnake", metric="contact_angle", floor="none")

    meas = pd.DataFrame(rows)
    sp = pd.DataFrame([dict(specimen_id=s, experiment_round=r, session=ses, substrate=sub, coated=c, coat_count=cc,
                            ratio_50nm=f.get("ratio_50nm"), hdtms_wt_pct=f.get("hdtms_wt_pct"),
                            silica_pu_solid_ratio=f.get("silica_pu_solid_ratio"), sonication_min=f.get("sonication_min"),
                            cure_temp_c=f.get("cure_temp_c"), cure_h=f.get("cure_h"), source="measured", note=note)
                       for s, r, ses, sub, c, cc, f, note in SPECIMENS])
    sp = sp[["specimen_id", "experiment_round", "session", "substrate", "coated", "ratio_50nm", "hdtms_wt_pct",
             "silica_pu_solid_ratio", "sonication_min", "coat_count", "cure_temp_c", "cure_h", "source", "note"]]
    sp.to_csv(OUT / "specimens.csv", index=False, encoding="utf-8-sig")
    meas.to_csv(OUT / "measurements.csv", index=False, encoding="utf-8-sig")
    print(f"specimens {len(sp)}, measurements {len(meas)} → {OUT}")
    print(meas.groupby(["specimen_id", "condition"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "raw" / "마찰계수 내마모성 검증데이터.xlsx")
