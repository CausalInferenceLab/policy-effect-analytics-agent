# 확장 탐색을 읽고 검증하는 순서

공개 결과 검증과 원본·상세 산출물·모델을 가진 로컬 실행을 구별한다. 첫 탐색의 코드와 설정은 원래 경로에 보존했다. 결과 폴더에는 [공개·보관 목록](submission-manifest.json)에 지정한 파일만 Git으로 배포한다.

## 1. 원본·모델 없이 공개 결과 확인

Python 3.12에서 사례 폴더의 검증기를 실행한다. 외부 패키지·네트워크·GPU·인증키가 필요하지 않다.

```bash
cd cases/sgim49697-ops-gangnam-bus-2024
python review_submission.py --check
```

이 명령이 확인하는 229개 중 첫 탐색의 수치는 78개다. [수치 선택 명세](overnight_review_spec.json)의 고유 조건으로 근거 CSV 17개를 읽어 [핵심 수치](results/overnight/review/key_numbers.csv)와 대조한다. 중복 선택·품질 실패·비유한 숫자·해시 불일치를 거절하며 최초 원문과 프로토콜도 확인한다. 최신 HTML의 표시값과 추가 탐색 수치도 함께 확인한다.

상세 셀·과거 그림·중복 보고서는 원래 경로에 로컬 보관한다. 전체 산출물과 모델 동결 확인은 2절의 로컬 감사다. 원자료를 재파싱하거나 문서의 모든 문장을 검증하는 도구는 아니다. 정리 과정에서 원래 수치·감사 명세를 다시 만들지 않았다.

현재 결과는 [최신 종합](deepening-summary.md)을 먼저 읽고, 첫 탐색의 상세 보고서가 필요하면 [과거 기록 안내](archive.md#reports)를 따른다. `overnight.py matched-directions` 단계는 기존 `hour-shape` 선택표·감사 명세와 `multiyear`/`forecast_bus_test` 캐시가 있어야 실행할 수 있다.

## 2. 기존 로컬 실행의 무결성 확인

상세 결과·원본·캐시·모델이 보존된 현재 환경에서는 아래 명령으로 동결된 입력까지 확인한다. 공개 복제본만 가진 경우에는 [보관 파일 복구 안내](archive.md#restore)를 먼저 확인한다. 모델 파일을 새로 학습하거나 시험 기간을 추가로 열지 않는다.

```bash
.venv/bin/python review_overnight.py --check --local-artifacts
```

기본 환경은 Python 3.12이고 CPU 확장 의존성은 다음과 같다. 이미 검증된 가상환경이 있으면 다시 만들거나 패키지를 재설치하지 않는다.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-overnight.txt
uv pip check --python .venv/bin/python
uv pip show --python .venv/bin/python numpy pandas catboost scikit-learn
.venv/bin/python -c "import sys; print(sys.executable)"
```

Windows 네이티브 환경은 `.venv\Scripts\python.exe` 경로를 사용하고 활성화 후 `where.exe python`으로 인터프리터를 확인한다. 확장 실험은 CPU로 실행했으며 PyTorch가 필요하지 않다. 이전 GPU 모델 비교는 [초기 실행 안내의 보관본](archive.md#reports)·[모델 기록](model-notes.md)과 별개다.

## 3. 원본부터 계산할 때의 의존 관계

**아래는 단계 간 관계를 설명하는 실행 지도이며, 공개 복제본에서 순서대로 붙여 넣으면 끝나는 설치 스크립트가 아니다.** 원본·Parquet·개별 예측·체크포인트는 Git에 없다. 출처 명세의 URL·요청·크기·해시로 원본을 다시 받을 수 있는지 먼저 확인해야 한다. 원격 기관이 파일을 바꾸면 기존 파일을 덮어쓰지 않고 재현 불가 사유를 기록한다.

| 분석 묶음 | 앞서 필요한 입력 | 진입 단계 (`overnight.py <stage>`) | 산출 위치(일부 로컬 보관) |
|---|---|---|---|
| 버스 기초 | `followup.py collect/prepare/analyze`, `directional.py collect/prepare/analyze`로 만들어진 당시 정류장·16시간 캐시 | `bus-prepare` → `bus-sensitivity` → `routes`, `route-plots` | `bus/`의 상태·선택·노선군·시간대 |
| 지역 기상 | 공식 AWS 공개 응답과 버스 기초 | `weather-collect` → `weather-prepare` → `weather-analysis`, `route-weather` | `weather/`·기상 출처 |
| 다년 버스 | 기존 정류장 레지스트리·고정 수집 설정 | `multiyear-collect` → `multiyear-prepare`, `schema2022`, `archives-audit` | `multiyear/`·형식 감사 |
| 승객 가중 | 사전 버스 선택 셀 | `passenger-collect` → `passenger-prepare` → `passenger-analysis`, `passenger-covered` | `passengers/`의 통과·실패 |
| 카드·환승·출도착 | 공식 공개 원본·역사적 ID 대응 | `auxiliary-collect`, `auxiliary-probe`, `auxiliary-quality`, `cards-prepare`, `cards-analysis` | `auxiliary/`, `cards/` |
| 일별 카드·운영 | 위 카드와 원래 시간·운행·승차 원본 | `daily-card-full-collect`, `daily-card-full-analysis`, `card-records`, `mechanism`, `fare-trim` | `card_records/`, `mechanism/` |
| 일반도로·교통량 | 기존 고정 도로 속도 캐시 | `road-context-collect` → `road-context`, `road-names`; `road-persistence-collect` → `road-persistence` | 도로 맥락·이름·연장 결과 |
| 원래 예측 | 다년 도로·버스, 2023~2025-04 개발 자료 | `forecast-collect`, `forecast-prepare`, `forecast-bus-features`, `forecast-features`, `forecast-train`, `forecast-freeze` | 개발 선택·동결 명세 |
| 최초 시험 | 위 선택을 먼저 커밋한 43개 동결 파일 | `forecast-test-collect/prepare`, `forecast-test-bus-collect/prepare`, `forecast-test-features/evaluate/diagnostics`, `forecast-plots` | `forecast/` |
| 기준·정보 집합·조건부 저속 | 기존 모델·개발/시험 특징·순차 동결 명세 | `baseline-*`, `relative-ablation-*`, `conditional-low-*`, `conditional-margin-*` | 각 모델 묶음의 별도 결과 |
| 구간·날씨·경보 | 고정 분위수/분류 모델과 개발/시험 예측 | `interval-calibration-*`, `weather-performance`, `alert-replay`, 관련 그림 단계 | 보정·날씨·순차 경보 |
| 버스 2025 연장 | 원래 사전 셀과 동결 후 확보한 `forecast_bus_test` 캐시 | `persistence`, `persistence-weather-*`, `persistence-segments`, `segment-uncertainty` | 지속성·기상·구간 |
| 운영·카드 2025 | 기존 공동 셀과 일/월 카드 | `operations-persistence-*`, `card-persistence-*`, `segment-operations` | 운영·카드·구간 운영 |
| 지하철 맥락 | 2023~2025년 1~8월 고정 역·기간 | `subway-probe` → `subway-collect` → `subway-analysis` → `subway-plots` | `subway/` |
| 장기·인접 합·시간 모양 | 원래 사전 셀·32개월 버스 캐시 | `timeline`, `path-sums`, `hour-shape`와 각 `-plots` | 세 진단의 전체 표·그림 |
| 미열람 가을·겨울 | 기존 모델·보정·임계값과 8월 준비 캐시 | `confirmation-freeze` → **커밋** → `confirmation-collect` → `confirmation-prepare` → `confirmation-evaluate`, `confirmation-plots` | `confirmation/` |
| 가을·겨울 사후 진단 | 위 저장 예측·별도 사후 규칙 | `confirmation-review` | `confirmation_review/`의 주 제외·달력 집단 |

`*`는 명령 이름의 묶음을 뜻하며 실제 셸에 별표를 입력하는 방식이 아니다. 정확한 명령은 `.venv/bin/python overnight.py --help`에 있다. 원본 다운로드·큰 파싱은 2개 작업자, 추가 학습·평가 CPU 스레드는 2개로 제한했다. 같은 결과를 쓰는 단계는 동시에 실행하지 않는다.

## 4. 동결과 재학습의 한계

현재 체크아웃은 완료된 실행의 증거를 보존한다. `forecast-train` 등 개발 단계를 다시 실행해 기존 모델·선택 명세를 덮어쓰면 안 된다. 이후 실험이 앞선 평가 감사의 해시도 참조하므로 **앞 단계 결과를 다시 쓰는 것만으로도 뒤 동결 검사가 실패할 수 있다.** 검토 목적에는 먼저 읽기 전용 검증기를 사용한다.

완전히 새로 학습한 모델 파일이 기존 직렬화 바이너리와 비트 단위로 같다고 보장하지 않는다. 새 반복 실험에는 기존 결과를 보존한 별도 출력 경로·실행 명세와 새로운 해시가 필요하다. 이 확장 실행기의 자동 실행 ID 분리는 아직 구현하지 않았다. 현재 문서는 기존 실행의 검증과 계산 의존성을 제공하며, 원본·모델 없는 복제본에서 새 학습을 자동으로 완료한다고 주장하지 않는다.

기존 `overnight_forecast_config.yaml`의 시험 범위는 계속 2025-05~08이다. 가을·겨울 확인은 별도 설정·수집기·폴더이며 이를 위해 원래 시험 범위나 2026년 잠금을 변경하지 않았다. 자료 접근 제한이나 해시 실패를 없애려고 잠금·원본 명세를 지우지 않는다.

## 5. 저장소 검사

저장소 루트에서 다음을 실행한다. 루트 환경에는 선택 ML 의존성이 없을 수 있어 일부 GPU/선택 패키지 테스트가 건너뛰어진다. 실제 모델·보정 계산과 로컬 동결 검증은 사례 환경에서 수행했다.

```bash
make check PY=.venv/bin/python
.venv/bin/python scripts/check_licenses.py
.venv/bin/python scripts/check_lineage.py
git diff --check
```

기존 `core/schema/timeindex.py`의 NumPy 시간 단위 경고 82건은 이번 변경과 별개로 남는다. CI 통과만으로 자료의 단위·정책 식별·공개 지연을 확인했다고 해석하지 않는다.
