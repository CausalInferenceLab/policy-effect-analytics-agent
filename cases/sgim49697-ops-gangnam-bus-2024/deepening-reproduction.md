# 두 번째 탐색의 공개 검토와 로컬 재현

추가 분석은 `deepening.py`, `gangnam/deepening_*.py`와 별도 보고서에 있다. [첫 탐색의 재현 안내](overnight-reproduction.md)는 이전 캐시·모델을 만드는 의존 경로를 설명한다. 원본·모델·동결 파일은 로컬에 보존한다.

## 1. 공개 파일만 검토

Python 3.12에서 사례 폴더의 명령을 실행한다. 외부 패키지·원자료·모델·GPU·인증키·네트워크가 필요하지 않다.

```bash
cd cases/sgim49697-ops-gangnam-bus-2024
python review_submission.py --check
```

이 명령은 첫 탐색 수치 78개와 추가 수치 151개, 직접 근거 35개, 공개 보존 산출물 155개를 확인한다. 기존 수치 추출 함수를 사용하여 유일한 선택 행·품질 조건·유한 숫자를 대조하고, 원래 검토표·선택 명세·검토 코드·보존된 동결 파일의 해시를 확인한다. HTML의 근거 52개·표시 수치 87곳·파생식 4개도 같은 검토표와 대조한다. [추가 검토표](results/deepening/review/key_numbers.csv), [공개·보관 목록](submission-manifest.json)

2026-10-30 정리에서 상세 행·중간 결과와 중복 문서를 Git 추적에서 제외했다. 제외된 484개 파일은 이 명령으로 검사하지 않으며 원래 위치에 로컬 보관한다. 기존 감사 명세가 참조하는 제외 파일의 경로·해시는 역사적 기록으로 남겨 두었다. 없는 파일을 건너뛰고 전체 감사가 통과했다고 표시하지 않는다.

이 검사는 공개 집계의 일관성 검사다. 원자료를 다시 파싱하거나 모델을 새로 학습하지 않으며 인과 가정이나 문서의 모든 문장을 자동 판정하지 않는다. 수치·명세를 다시 만드는 `--write`는 정리나 일반 검토에 사용하지 않는다. 공개 파일만 복사한 환경의 검증 결과는 [진행 기록](deepening-plan.md)에 남긴다.

## 2. 상세 산출물과 모델이 있는 로컬 실행 확인

상세 산출물이 남아 있는 현재 작업 폴더에서는 다음 전체 검토기를 그대로 사용한다. 공개 복제본만으로는 제외 파일이 없어서 실패한다. 복구 방법은 [보관 안내](archive.md#restore)를 따른다.

```bash
.venv/bin/python review_overnight.py --check
.venv/bin/python review_deepening.py --check
.venv/bin/python review_record_support.py --check
```

이 경로는 추가 수치 151개·원래 산출물 69개·기존 공개 동결 전체와 기록 비율 재집계를 확인한다. 아래는 그다음의 선택적 모델 동결 확인이다.

원본·캐시·모델이 있는 현재 환경에서 기존 동결을 검사하는 명령이다. 첫 명령은 앞선 실험의 로컬 입력을 확인한다. 두 번째는 **완료된 학습 명세가 존재할 때** 모델 8개·기준선 2개와 입력/코드 해시를 확인하고 종료한다. 명세가 없는 새 복제본에서 검증용으로 두 번째 명령을 실행하면 안 된다.

```bash
.venv/bin/python review_overnight.py --check --local-artifacts
.venv/bin/python deepening.py archive-train
```

환경은 기존 Python 3.12 사례 가상환경과 [CPU 의존성](requirements-overnight.txt)을 사용한다. 새 빈 환경에서 필요한 설치는 다음과 같다. 이미 있는 검증 환경은 다시 만들지 않는다.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-overnight.txt
uv pip check --python .venv/bin/python
uv pip show --python .venv/bin/python numpy pandas catboost scikit-learn
.venv/bin/python -c "import sys; print(sys.executable)"
```

Windows 네이티브는 `.venv\Scripts\python.exe`를 사용하며 활성화 후 `where.exe python`으로 확인한다. 추가 학습은 CPU 2스레드의 8회 순차 실행이며 합계 학습 시간은 807.18초였다. GPU·PyTorch 설치가 필요하지 않았다. PDF 표·도면 확인에만 별도의 Git 제외 환경 `data/deepening/pdf-env`를 사용했고 분석 환경을 바꾸지 않았다.

## 3. 원본 계산 단계의 의존 관계

아래는 명령 간 관계이며 새 복제본에서 바로 붙여 넣어 완주하는 자동 실행 스크립트가 아니다. 원본·Parquet·모델·개별 예측은 Git에 없다. 출처 명세의 공개 URL이 현재도 같은 내용을 주는지 크기·해시로 먼저 확인해야 한다. 일부 단계는 앞선 [첫 탐색의 캐시](overnight-reproduction.md)가 필요하다.

| 분석 | 필요한 입력 | `deepening.py`의 실행 단계 | 산출 위치(일부 로컬 보관) |
|---|---|---|---|
| 역사 정류장·노선 | 공식 목록의 고정 요청, 기존 정류장/노선 선택 | `history-prepare` → 요청 명세 커밋 → `history-collect` → `history-audit` | `history/` |
| 시간 필드 명세 | 보존된 T Data 페이지·예시와 출처 해시 | `definitions-audit` | `definitions/` |
| 폐선 제외 13개 | 기존 14개 기준·양방향 시간/횟수 캐시·역사 폐선 근거 | `cohort-audit` → `cohort-raw-check` → `cohort-plots` | `cohort/` |
| 경기 대표일 자료 | 공식 연도별 게시물·공개 첨부·고정 대상 이름 | `gyeonggi-prepare` → 요청 커밋 → `gyeonggi-collect` → `gyeonggi-parse` → `gyeonggi-audit` → `gyeonggi-plots` | `gyeonggi/` |
| 주변 도로 | 기존 사전 선정 14개 링크와 2023~2025년 원본/캐시 | `road-context` → `road-raw-check` → `road-plots` | `road_context/` |
| 형상·표준링크 | 공개 2022/2025년 형상과 2025년 대응표 | `geometry-prepare` → 요청 커밋 → `geometry-collect` → `geometry-audit` | `geometry/` |
| 전환 주간·회귀 | 같은 14개 링크·기상 원본·별도 고정 날짜/모형 | `transition-prepare` → 입력 명세 커밋 → `transition-audit` → `transition-result-check` → `transition-raw-check` → `transition-plots` | `transition/` |
| 월별 속성 | 기존 36개월 원본 추출 명세, 도로 속도값을 읽지 않음 | `metadata-audit` | `metadata/` |
| 새 정류소·안내군 | 공식 개통 표·역사 목록·고정 13개 노선과 옛 기준값 | `infrastructure-prepare` → 선택표/입력 커밋 → `infrastructure-history` → `infrastructure-groups` → `infrastructure-check` → `infrastructure-plots` | `infrastructure/` |
| 실제 운행횟수 경계 | 기존 2025년 1~2월 운행횟수 ZIP·13노선·10정류소 | `infrastructure-raw` → `infrastructure-raw-check` | 같은 폴더의 `trip_support_*` |
| 저속 시작 감지 | 기존 24개 저장 예측·선택/임계값 동결 | `episode-prepare` → 입력 명세 커밋 → `episode-audit` → `episode-check` | `episodes/` |
| 입력 공개 시각 | 기존 36개월 카탈로그·TOPIS 안내, 속도값 미사용 | `availability-audit` → `forecast-plots` | `availability/`, `episodes/` 그림 |
| 공개 과거 월 예측 | 기존 62개 훈련 링크 캐시·공개 시각·달력, 고정 모형 설정 | `archive-prepare` → 입력 커밋 → `archive-features` → `archive-feature-check` → `archive-train` → **완료 학습 명세 커밋** → `archive-eval-prepare` → `archive-evaluate` → `archive-result-check` → `archive-plots` | `archive_forecast/` |

독립 검사도 완료 시각이 들어간 감사 파일을 쓴다. 앞선 결과·검사 명세를 다시 생성하면 이를 참조한 뒤 단계의 해시가 달라질 수 있다. 검토 목적에는 1절의 읽기 전용 명령을 우선 사용한다. 계산을 새로 반복하려면 기존 결과를 보존한 별도 출력 경로와 새 실행 명세가 필요하다. 자동 실행 ID 분리는 구현하지 않았다.

## 4. 수행한 독립 대조

| 대조 | 범위·결과 | 한계 |
|---|---|---|
| 폐선 경계 원본 CSV | 4개 날짜 5,376개 값/상태 일치 | 전체 32개월 재파싱을 뜻하지 않음 |
| 전환 경계 원본 XML | 6개월 원본 927,745행을 읽어 36일·12,096칸 일치 | 고정 14개 링크와 지정 경계의 대조 |
| 전환 회귀 | 별도 QR 잔차화로 486행·1,674수치 일치, 최대 차이 3.64e-12 이하 | 같은 기술 모형의 계산 확인, 식별 검증 아님 |
| 공식 안내군 | 별도 긴 표·주별 계산으로 4,590수치 일치 | 새 중앙차로의 인과 효과를 추정하지 않음 |
| 새 정류소 운행 경계 | 별도 판독기로 3주 원본 1,451,723행, 6일·780상태·3,900수치 일치 | 공란/중복 경계를 포함한 부분 대조 |
| 연속 저속 구간 | 3,849개 구간 경계, 기존 지표 480수치, 192개 상세 파일 확인 | 관측 결측에서 구간을 끊는 정의를 사용 |
| 새 월별 특징 | 지연값 13,046,784칸과 가용 표시, 경계 프로필 840개·통계 5,880개 일치 | 공개 시각에 대한 가정의 진실성을 증명하지 않음 |
| 새 예측 성능 | 24개 파일, 성능 3,240수치·주별 짝 비교 1,680수치 일치 | 2025년을 이미 본 뒤의 후속 실험 |

주별 재표집 구간은 시계열 의존의 일부를 반영한 기술적 불확실성 표시다. 정책 인과 구간·다중검정 보장·미래 배포 성능 보장으로 사용하지 않는다. 원본 집계의 시간 단위, 실제 시설 노출, 역사적 공개 버전은 별도 근거가 필요하다.

## 5. 저장소 검사와 보존

저장소 루트에서 수행한다. 루트 기본 환경은 선택 데이터/모델 패키지가 없으면 해당 테스트를 건너뛴다. 사례 환경으로 추가 탐색 테스트를 별도 실행해 실제 검사를 확인한다.

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 make check PY=.venv/bin/python
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 cases/sgim49697-ops-gangnam-bus-2024/.venv/bin/python -m pytest -q tests/test_gangnam_deepening*.py
.venv/bin/python scripts/check_licenses.py
.venv/bin/python scripts/check_lineage.py
git diff --check
```

실제 검사 수·결과와 원격 CI는 [진행 기록](deepening-plan.md)에 남긴다. 기존 `plan.yaml`, `corridors.yaml`, `data_contract.yaml`, `ml_config.yaml`, 사용자 제공 실행계획 원문, 첫 탐색 코드·결과·동결 및 2026년 잠금은 보존한다. 상세 결과의 보존 위치는 공개 목록과 로컬 보관 목록으로 구분한다. 변경 위치는 사례 내부의 추가 탐색 파일과 관련 테스트이며, README는 최신 진입점만 갱신한다.
