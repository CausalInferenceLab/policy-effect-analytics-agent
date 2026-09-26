# 분석계획(plan.yaml) 작성 가이드

> 원칙: **데이터를 열기 전에** 확정하고 커밋한다(사전등록). 데이터를 본 뒤 바꾼 항목은 `amendments`에 날짜와 사유를 남긴다. 에이전트는 plan.yaml에 없는 추정을 "탐색적(exploratory)"으로만 보고해야 한다.
> 필드 구성은 GSA OES Analysis Plan의 섹션과 1:1로 대응된다(아래 표). 스키마 구현은 `core/schema/plan.py`(Develop)가 맡고, 이 문서는 **내용 기준**을 정한다.

## 1. 필수 필드와 결정 기준

| 필드 | 조가 결정할 것 | 최소 기준 | OES 대응 섹션 |
|---|---|---|---|
| `question` | 한 문장의 인과 질문 | "X가 Y를 (얼마나) 바꿨나" 형식. 추정대상(estimand: ATT/ATE/효과 시점)을 명시 | Project description / Hypotheses |
| `unit` | 분석 단위 × 시간 단위 | 처치가 배정되는 단위보다 작으면 클러스터링 수준을 따로 적는다 | Data structure |
| `treatment` | 무엇을, 누구에게, 언제 | 날짜 단위 시점, 발표일과 시행일 구분, 강도(dose) 변화 시점, 출처 URL | Intervention |
| `control` | 대조군 정의와 제외 규칙 | 오염(spillover) 우려 단위는 제외하거나 별도 표시. 후보 풀을 사전에 고정 | Comparison / Sample |
| `period` | 사전·사후 창, 제외 구간 | 사전 시점 ≥ 8(월/분기) 권장. 제외 구간(예: 코로나)은 사유와 함께 적는다 | Data |
| `outcome` | 1차 결과 1개, 2차 결과 ≤ 3개 | 변수명, 출처 데이터셋 ID·URL, 집계식, 단위 | Outcome measures |
| `covariates` | 통제변수 | **처치 이후 값이 처치 영향을 받는 변수는 금지**(나쁜 통제) | Statistical models |
| `estimator` | 주 추정량 1개와 강건성 추정량 | 시차 도입이면 TWFE를 주 추정량으로 쓰지 않는다. SE 방식과 클러스터 수를 적는다 | Statistical models / Inference |
| `assumptions` | 식별 가정 목록 | 가정마다 **검증 방법 + 합격 기준**을 짝지어 적는다 | Balance checks / Limitations |
| `refutation` | 반증 테스트 | placebo 시점, placebo 결과, placebo 단위, 표본 민감도 중 최소 2개 | Robustness |
| `abstain_if` | 기권 조건 | 기계가 판정할 수 있는 조건. 충족되면 효과 수치 대신 "식별 불가 + 사유"를 출력 | Inference criteria / Limitations |
| `concurrent_policies` | 동시 정책 | 날짜, 적용 범위, 처리 방법(통제·제외·한계 기술) | Limitations |
| `reporting` | 보고 규칙 | 신뢰구간과 효과크기를 함께 보고. 다중비교 보정 방식. 금지 표현 | Inference criteria |
| `amendments` | 변경 이력 | 날짜, 변경 내용, 사유, 데이터 열람 전/후 여부 | Deviations |

### 가정 → 검증 매핑 (자주 쓰는 것)
| 가정 | 검증 | 합격 기준 예시 |
|---|---|---|
| 평행추세 | 이벤트스터디 사전 계수의 결합검정 + 그림 | 사전 계수 결합 p ≥ 0.10, 사전 계수 최대 절대값 < 사후 효과의 50% |
| 사전 반응 없음(no anticipation) | 발표일 기준 추정과 시행일 기준 추정 비교 | 발표~시행 구간 계수가 유의하지 않음 |
| SUTVA / 파급 없음 | 대조군을 거리 링별로 나눠 추정 | 인접 링과 원거리 링의 추정치 차이가 유의하지 않음 |
| 동시 정책 없음 | 동시 정책 목록을 만들고 해당 기간을 제외하거나 통제 | 제외 전후 추정치 부호가 유지됨 |
| SCM 적합도 | 사전 RMSPE, 가중치 집중도 | 처치 단위의 사전 RMSPE가 placebo 분포 하위 50% 안에 있음 |
| 측정 일관성 | 결과 변수의 정의·단위·경계 변경 이력 점검 | 변경이 있으면 crosswalk 또는 구간 분리 |

### 기권(abstain) 조건 작성 요령
- **판정 가능해야 한다**: "추세가 다르면"(✕) → "사전 계수 결합검정 p < 0.10"(○)
- 최소 세트: ① 사전추세 실패 ② 처치 단위 또는 클러스터 수 부족(예: 처치 클러스터 < 2 이면 순열추론만 허용, 대조 < 5 이면 기권) ③ 결과 결측률 과다 ④ 제거할 수 없는 동시 충격 ⑤ 반증 테스트 실패(placebo 효과가 주 효과의 50% 이상).
- 기권은 실패가 아니다. 리포트에는 "무엇 때문에, 어떤 데이터가 있으면 식별 가능한지"를 적는다.

---

## 2. 예시: T1 녹색교통지역 5등급 운행제한 → 도심 NO₂

```yaml
# cases/green_zone_seoul/plan.yaml
meta:
  case_id: green_zone_seoul
  version: 1
  registered_at: 2026-10-05        # 데이터 열람 전 커밋 시점
  authors: [조이름]
  status: preregistered            # preregistered | amended | final

question:
  text: "서울 녹색교통지역(사대문 안) 5등급 차량 운행제한은 제한 시간대(06-21시) 도심 측정소의 NO2 농도를 낮췄는가?"
  estimand: ATT                    # 처치 측정소의 평균 처치효과
  effect_window: "2019-12 ~ 2021-12, 월별 동적효과 + 기간 평균"
  hypothesis: "NO2 감소(단측 아님, 양측 검정)"

unit:
  observation: station_hour        # 측정소 × 시간
  treatment_assignment: station    # 처치 배정 단위
  cluster: station

treatment:
  name: 5등급 차량 운행제한(녹색교통지역)
  definition: "측정소 좌표가 녹색교통지역 경계(16.7km2) 내부"
  boundary_source: "서울시 녹색교통지역 경계 (https://news.seoul.go.kr/traffic/greentraffic) - 공간파일 확보 여부 확인 필요"
  timeline:
    announced: null                # 1주차에 서울시 보도자료로 확정
    pilot_start: 2019-07
    enforcement_start: 2019-12-01  # 과태료 부과 시작(월 확인됨, 일자는 확인 필요)
    intensity_change: 2021-01-01   # 저감장치 미개발 차종 유예 종료(2020-12-31)
  hours_active: "06:00-21:00, 주말·공휴일 포함"

control:
  pool: "서울 내 녹색교통지역 밖 도로변대기·도시대기 측정소"
  exclude:
    - rule: "녹색교통지역 경계로부터 1km 이내 측정소"
      reason: "우회 교통 파급(SUTVA)"
  fixed_before_data: true

period:
  pre: [2017-01-01, 2019-06-30]
  pilot: [2019-07-01, 2019-11-30]  # 추정에서 제외, 사전 반응 점검용
  post: [2019-12-01, 2021-12-31]
  excluded: []                     # 코로나는 제외하지 않고 민감도 분석으로 처리

outcome:
  primary:
    name: no2_ppm
    source: "에어코리아 최종확정 측정자료 (https://www.airkorea.or.kr/web/last_amb_hour_data?pMENU_NO=123)"
    aggregation: "시간값 그대로, -999는 결측"
  secondary:
    - {name: pm25_ugm3, note: "2차 생성 비중이 커서 효과가 희석될 것으로 예상"}
    - {name: co_ppm}

covariates:
  include:
  - {name: temp, source: "기상청 ASOS 서울(108) 시간자료"}
  - {name: wind_speed, source: "ASOS"}
  - {name: wind_dir_sector, source: "ASOS"}
  - {name: humidity, source: "ASOS"}
  - {name: precip, source: "ASOS"}
  forbidden: ["교통량(처치의 매개변수)"]

estimator:
  primary:
    method: DDD
    spec: "log(no2) ~ treat_station x post x active_hour | station^hour_of_day + date^hour_of_day + weather"
    library: pyfixest
    se: "측정소 클러스터 + wild cluster bootstrap (처치 클러스터 수 적음)"
  robustness:
    - {method: DiD_event_study, note: "제한 시간대만, 월별 계수"}
    - {method: SCM, library: CausalPy, unit: "처치 측정소 평균의 일평균 시계열"}
    - {method: permutation_inference, note: "대조 측정소에 가짜 처치를 배정해 순위 p값"}

assumptions:
  - id: parallel_trends
    check: "이벤트스터디 사전 24개월 계수 결합검정 + 그림"
    pass_if: "joint p >= 0.10"
  - id: no_anticipation
    check: "시범운영 기간(2019-07~11) 계수"
    pass_if: "유의하지 않거나 본 효과의 50% 미만"
  - id: no_spillover
    check: "1~3km 링 측정소를 처치로 둔 추정"
    pass_if: "링 효과가 유의하지 않음"
  - id: night_hours_valid_placebo
    check: "비제한 시간(21-06시)의 DiD"
    pass_if: "효과가 제한 시간 효과의 1/3 미만"
    note: "야간에도 5등급 차량이 줄면(차량 폐차 등) DDD는 과소추정됨 - 한계로 기술"

concurrent_policies:
  - {name: 미세먼지 계절관리제, start: 2019-12-01, scope: 전국, handling: "대조군에도 적용되므로 DiD로 상쇄. 도심 이질효과는 한계로 기술"}
  - {name: 코로나19 사회적 거리두기, start: 2020-02, scope: 전국(도심 업무지구 영향 클 수 있음), handling: "2020년 제외 민감도 분석"}
  - {name: 수도권 5등급 차량 계절제 운행제한, start: 2020-12, scope: "수도권 전역(계절관리제 기간)", handling: "대조군에도 적용. 발효일 확인 필요"}

refutation:
  - {type: placebo_time, spec: "2018-12-01을 가짜 시행일로 둔 추정", pass_if: "p >= 0.10"}
  - {type: placebo_outcome, spec: "O3(교통 감소 시 오히려 증가할 수 있음) - 부호 점검용", pass_if: "NO2와 같은 방향의 감소가 아님"}
  - {type: sample, spec: "2020년 제외 / 도로변 측정소만 / 도시대기만"}

abstain_if:
  conditions:
  - "treated_stations < 1 after data cleaning"
  - "parallel_trends.joint_p < 0.10 AND scm.pre_rmspe_rank > 0.5"
  - "primary outcome missing share > 0.30 in treated stations (pre or post)"
  - "placebo_time effect >= 0.5 * primary effect"
  - "permutation p-value unavailable (control stations < 5)"
  message: "현재 데이터로는 녹색교통지역 효과를 계절관리제·코로나 영향과 분리해 식별할 수 없습니다. 필요한 추가 자료: {missing}"

reporting:
  primary_metric: "NO2 % 변화 (exp(b)-1), 95% CI"
  multiple_comparisons: "2차 결과(PM2.5, CO)에 Holm 보정"
  forbidden_phrases: ["정책 덕분에", "입증되었다", "완전히 해소"]
  must_include: ["사전추세 그림", "동시 정책 목록", "기권 조건 판정 결과", "데이터 출처·라이선스"]

amendments: []
```

## 3. 체크: 에이전트가 plan.yaml로 해야 하는 일
1. `fetch.py`는 `outcome.source`와 `covariates`에 적힌 것만 받는다(데이터 스누핑 방지).
2. `estimate.py`는 `estimator.primary`를 먼저 실행하고, `assumptions`, `refutation`, `abstain_if`를 순서대로 판정한다.
3. 리포트 생성기는 `abstain_if`가 하나라도 참이면 효과 수치를 헤드라인에 올리지 않는다.
4. plan과 실제 실행이 다르면 `amendments`가 없는 한 실패 처리한다(CI).
