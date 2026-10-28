# SoleFit — 수치 검증 AI 앱 (하이젠버그 캡스톤)

미끄럼 방지 밑창 코팅제의 실험 수치를 검증하고, 사용자 조건별 적용 가능성과 다음 실험 배합 후보를 보여주는 Streamlit 프로토타입.
설계서(캡스톤 수치검증 AI 앱 개발 설계서)의 3가지 기능을 구현한다.

화면 구성은 팀 안내(10/28)에 맞춘 5영역이다.

| 화면 | 기능 | 핵심 모듈 |
| --- | --- | --- |
| 1 · 실제 실험 결과 | 코팅·미코팅의 정마찰계수 μs(경사판 정적)와 동마찰계수 μk(경사판 동적, 경사각 35~50°) 비교, 접촉각, 값별 검증 배지 | `summarize.py`, `validator.py` |
| 2 · 마모 성능 추세 | 0~200회 마모 추세, **측정값 vs 회귀 예측값** 구분(1·2차 다항, 95% 예측 구간, 외삽 표시), 기존 배합 성능 저하·회복 분석, 질량 변화 | `trend.py` |
| 3 · AI 최적화 데모 | GP + UCB로 다음 시험 조건 탐색, 가상/실측 분리, 부분 의존 그래프 | `gp.py` |
| 4 · 안전관리 시나리오 | 검증된 시험 조건 vs 실제 적용 대상 차이 → 등급·점검 경로·추가 검증 | `safety.py`, `rules.yaml` |
| 5 · 사회적 파급효과 | 어린이·고령층·습윤 작업장 점검 서비스 활용 가능성, 말할 수 있는 것/없는 것 | `app.py` |
| 데이터 관리 | CSV 템플릿·업로드·검증·확정(버전) | `schema.py`, `validator.py` |

## 실행

```bash
cd solefit
python -m venv .venv && .venv\Scripts\activate      # Windows (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

테스트: `pytest tests/` (pytest가 없으면 `python tests/test_core.py`)

## 데이터 (출처: 팀 엑셀, 10/28 `마찰계수 통합_최종.xlsx` 반입)

- `data/raw/` — 팀 엑셀 원본. CSV 재생성: `python scripts/import_excel.py` → `python scripts/import_integrated.py` 순서.
- `data/specimens.csv` — 시편 12개(배합·공정·세션). 한 행 = 시편 하나.
- `data/measurements.csv` — 반복 측정 원값 299행(`agg=raw`). 평균·표준편차·μ=tanθ는 앱이 계산한다. 동마찰계수 행은 `test_angle_deg`(경사각) 컬럼을 가진다.
- `data/mass.csv` — 사포질 횟수별 시편 질량 (내마모성).

| 세션 | 시편 | 내용 |
| --- | --- | --- |
| 초기 (브러시 1·2회 비교) | R2-U-00, R2-C-B1, R2-C-B2 | 건조·습윤 5회 반복, 브러시 2회 시편의 사포 20~100회 습윤 1회 측정 |
| 8/25 | R3A-U-00, R3A-U-S, R3A-C-01 | 미코팅 사포질 X/O, 코팅 사포 0~100회(20회 간격) 3회 반복 |
| **8/26 (3차 최종검증, 발표 기준)** | R3-U-01, R3-C-01 | 발표 PPT의 그래프 원자료. 코팅 0회는 값 1개 |
| 10/26 (4차) | R4-U-01, R4-C-01 | 미코팅·코팅 모두 사포 0~200(250)회, 같은 마모 횟수끼리 비교 가능 |
| **통합본 (팀 확정, 10/27)** — 앱 기본 | R5-U-01, R5-C-01 | `마찰계수 통합_최종.xlsx`. 정마찰: 미코팅·코팅 0~200회 × 건조·습윤 × 3회 반복. 동마찰: 경사각 35·40·45·50° × 0~200회 기준값/보정값. GP 학습에서는 중복을 피해 제외 |

엑셀에서 가져오지 않은 것: 5° 간격 "마찰계수" 표(측정값 아님, 팀 확인), 시편 질량 표, 엑셀의 평균·μ·개선율 행(앱이 재계산). 접촉각은 PPT 18p 값.
동마찰계수(경사판 동적법): 경사각 θ에서 미끄러지는 가속도로 보정한 값. 기준값(≈tanθ) → `metric=dcof_ref`, 보정값 → `metric=dcof`, `method=incline_dynamic`. 엑셀에 건조/습윤이 없어 `condition=unknown`으로 두었고(R5 경고), 팀 확인 후 채울 것. R1이 기준값 ≠ tanθ(미코팅 50° 0회 0.179 — 1.179 오타 추정)를 경고로 표시한다.
- `data/claims.csv` — 보고서·발표의 서술 수치 (팀 내부 점검용, 앱 화면에는 표시하지 않음). `solefit_core.validate_claims(claims, meas)`로 확정 데이터와 대조할 수 있다.

8/26 세션과 통합본의 코팅 50~200회 집계는 PPT 값과 일치한다(미코팅 건조/습윤 μ 0.77/0.96, 코팅 0회 0.64/0.57, 200회 1.58/1.09). 발표 전에 보고서 본문 수치도 같은 값으로 맞출 것.

## 검증 규칙 (R1~R9)

| ID | 규칙 | 실패 시 |
| --- | --- | --- |
| R1 | μ = tanθ 재계산, 기록값과 차이 ≤ 0.01. 동적법 기준값 ≠ tan(경사각) | 오류 / 경고 |
| R2 | 반복 원값에서 평균·표준편차 재계산, n 필수 (평균만 있으면 경고) | 오류/경고 |
| R3 | 물리 범위 (접촉각 0~180°, 시작각 0~90°, 비율 ≥ 0) | 오류 |
| R4 | 시험법 분리 — 동마찰(dcof)은 incline_dynamic·tribometer_dcof에서만 | 오류 |
| R5 | 비교 조건 일치 (건조/습윤·마모·기재) | 경고 |
| R6 | 개선율 재계산·같은 조건의 값 충돌 | 오류 |
| R7 | synthetic 시편은 실측과 분리 | 차단 |
| R8 | 추천 후보가 학습 범위 밖이면 외삽 경고 | 경고 |
| R9 | 학습 행 < 입력 변수 × 2 이면 신뢰도 낮음 | 경고 |

## 화공 팀원이 확정해야 하는 것

1. `rules.yaml` — 재질별 등급·안내 문구·추가 시험 목록
2. `gp.py`의 `DEFAULT_BOUNDS` — 실험 가능한 탐색 범위
3. 초기·8/25 세션 시편의 배합(`specimens.csv` 빈 칸) — 채우면 GP 학습 데이터가 늘어난다
4. 미코팅 "사포질 O"의 사포 횟수 (8/25, 8/26)
5. 동마찰계수 측정의 건조/습윤 조건, 기준값 오타(미코팅 50° 0회 0.179)
6. 평탄면 고유 접촉각 θ (Cassie–Baxter 역산용, 미구현)

## 구조

```
solefit/
├─ app.py                 Streamlit UI
├─ solefit_core/          UI 독립 로직 (Colab에서 import 가능, 향후 FastAPI로 감쌈)
│  ├─ schema.py           데이터 스키마·로더·SafetyProfile
│  ├─ validator.py        R1~R7 + 보고서 주장 검증
│  ├─ safety.py + rules.yaml
│  ├─ summarize.py        세션별 집계 (μs · 경사각별 μk · 질량)
│  ├─ trend.py            회귀 추세 (측정 vs 예측, 95% 구간, 외삽, 성능 저하표)
│  └─ gp.py               GP 학습·UCB 추천·가상 데이터·R8/R9
├─ scripts/import_excel.py       팀 엑셀(검증데이터) → CSV
├─ scripts/import_integrated.py  팀 통합본 → 통합본 세션 + mass.csv
├─ data/                  raw/(엑셀 원본 2개) · specimens · measurements · mass · claims
└─ tests/test_core.py     규칙별·세션별·DCOF·추세·시나리오 A·B·C 골든 테스트 (23개)
```
