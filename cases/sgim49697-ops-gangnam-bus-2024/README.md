# 강남대로 버스 운행 변화와 월별 도로 속도 예측

2024년 6월 29일 버스 운행 조정 뒤 강남대로의 이동 기록이 어떻게 달라졌는지 살펴본 학생 프로젝트다. **남행·북행의 변화가 달랐다는 관찰**과 **공개가 늦은 월별 파일로 어디까지 예측할 수 있는가**를 다룬다. 정책의 인과 효과나 실시간 예측 서비스가 완성됐다는 주장은 하지 않는다.

먼저 [프로젝트 설명 HTML](project-overview.html)을 브라우저에서 열면 배경 → 데이터 → 분석 → 결과 → 활용 순서로 읽을 수 있다. 간결한 결과는 [report.md](report.md), 해석·활용의 한계는 [discussion.md](discussion.md), 실행 범위와 진행 기록은 [plan.md](plan.md)에 있다.

| 공개 구성 | 내용 |
|---|---|
| 설명·설계 | 이 문서, HTML, 계획·결과·토론, 데이터 안내, 설정 2개 |
| 실행 코드 6개 | 수집, 버스 비교, CPU 예측, 공통 함수, 제출 검사, HTML 검사 |
| 출처·기록 | 원본 68개 파일 계약, 결과·코드 해시를 담은 실행 명세 |
| 결과 6개 | 비교표 2개, HTML 근거 수치표 2개, 그림 2개 |

사례 파일은 총 24개다. 저장소 루트의 테스트 3개와 기존 카탈로그 변경 2개를 합쳐 `main` 대비 제출 구성은 29개다. 계획 브랜치를 대상으로 하는 PR #55의 변경 파일 수와는 기준이 다르다. 원본·모델·새 실행 결과는 Git에 넣지 않는다.

## 설치와 빠른 확인

아래 명령은 **이 사례 폴더에서** Python 3.11 이상으로 실행한다. 빠른 검사는 표준 라이브러리만 사용하며 데이터 다운로드·학습을 시작하지 않는다.

```bash
python review_submission.py && python review_overview.py --check
```

이 검사는 공개 파일의 무결성, 수치표 229개 항목 중 핵심 비교표와 연결되는 62개, HTML 표시값을 대조한다. 원본부터 재계산하거나 모델을 새로 학습한 검사와는 구분한다.

재계산할 새 환경에만 아래 의존성을 설치한다. 기존 `.venv`가 있으면 재생성하지 않고 그 환경을 사용한다.

```bash
uv venv --python 3.12 .venv &&
uv pip install --python .venv/bin/python -r requirements.txt
```

Windows의 Python 실행파일 경로는 `.venv/Scripts/python.exe`다. 아래 연속 실행 예시는 Bash/WSL 기준이다. PyTorch·CUDA는 필요 없다.

## 원본부터 실행

원본 내려받기 주소·요청 인자·크기·SHA-256은 [source-manifest.json](source-manifest.json)에 고정되어 있다. 기존 탐색 보고서·감사 JSON·모델 없이 아래 순서로 실행할 수 있다. 공급자가 원본을 교체하면 해시 불일치로 중단한다. `&&`로 연결해 앞 단계가 실패하면 다음 분석을 실행하지 않는다.

```bash
gangnam_run="reproduce-$(date -u +%Y%m%dT%H%M%SZ)" &&
.venv/bin/python fetch.py --run-id "${gangnam_run}-collect" &&
.venv/bin/python estimate.py --inputs "runs/${gangnam_run}-collect/inputs.json" --run-id "${gangnam_run}-bus" &&
.venv/bin/python forecast.py features --inputs "runs/${gangnam_run}-collect/inputs.json" --run-id "${gangnam_run}-features" &&
.venv/bin/python forecast.py train --features "runs/${gangnam_run}-features/features.json" --run-id "${gangnam_run}-train" &&
.venv/bin/python forecast.py evaluate --features "runs/${gangnam_run}-features/features.json" --training "runs/${gangnam_run}-train/training.json" --run-id "${gangnam_run}-evaluation" &&
.venv/bin/python forecast.py explain --models "runs/${gangnam_run}-train" --predictions "runs/${gangnam_run}-evaluation" --run-id "${gangnam_run}-explain" &&
.venv/bin/python review_submission.py --bus-results "runs/${gangnam_run}-bus/comparisons.csv" --forecast-results "runs/${gangnam_run}-evaluation/metrics.csv"
```

각 실행 ID는 새 이름이어야 한다. 기존 데이터·모델을 덮어쓰지 않고 `runs/<ID>/` 아래에 입력·설정·코드 해시와 결과를 기록한다. 다운로드와 전체 정규화는 자료량에 따라 오래 걸린다. 최소 25 GiB 여유 공간을 권장하며 학습은 CPU 스레드 2개로 순차 실행한다. 재학습은 라이브러리·플랫폼 차이에 따라 작은 수치 차이가 날 수 있다.

기존 로컬 자료가 있으면 위 `fetch.py` 명령에 `--reuse-cache`를 붙여 명세에 해시가 등록된 정규화 파일을 재사용할 수 있다. 다른 폴더에 있으면 `--local-source-root /자료가_있는_사례폴더`를 함께 지정한다. 버스만 확인하려면 `--kind bus_time`으로 수집한 뒤 `estimate.py`까지만 실행한다. 도로만 확인하려면 `--kind road_speed`로 수집한 뒤 `forecast.py`의 세 단계를 실행한다.

## 무엇이 재현되는가

- 버스: 원래 14개와 공식 폐선 542번 제외 13개를 동일 날짜/원래 관측률 두 조건으로 비교한 30행 전체.
- 예측: 달력만/공개된 과거 월 자료를 사용하는 CatBoost 8회와 3개월 경험 프로필 기준선. 두 기간·두 예측 간격·전체/저녁/링크별/월별 조건을 모두 포함한다.
- HTML 그림 자료: `estimate.py`는 비교표와 함께 일별(`daily.csv`)·시간대별(`hourly.csv`)·주별(`weekly.csv`) 표를 쓴다. `forecast.py explain`은 학습·평가를 다시 하지 않고 저장된 모형과 예측에서 모형별 반복 수(`models.csv`), 입력 중요도(`importance.csv`), 가을 평가 첫 주 예시(`example_week.csv`)를 만든다. `review_overview.py --check`는 일별·월별·발행 시점·표본 규칙 그림을 공개 비교표·예측 지표표와 대조하고, 시간대·주별·모형·예시 주·중요도 그림은 로컬 실행 결과의 생성 명령과 SHA-256 기록만 확인한다.
- 과거의 경보·승객 가중·GPU·지하철 등 보조 분석은 HTML의 **역사적 수치 스냅샷**으로 남는다. 229개 수치를 담은 두 표의 해시를 검증하고 핵심 62개를 최종 비교표와 대조한다. 나머지 167개를 포함한 보조 실험 전체를 축약 코드로 다시 수행하지는 않는다. 목록과 원래 출처의 해시는 [run_manifest.json](run_manifest.json)에 있다.

초기 [plan.yaml](plan.yaml)은 공통 엔진용 DiD 설계 기록이다. 최종 분석의 실행 규칙은 [analysis-plan.yaml](analysis-plan.yaml)이며, 이 사례를 `core.agent`로 실행하는 경로는 최종 재현 절차가 아니다.

확장 탐색 코드·중간 보고서·개별 테스트는 저장소 밖의 보관본으로 옮겼다. 이력 기준점은 `89156f6b9ac4fc8d0990e1297ba3f3e367197fa4`이며, 보관본에는 원래 경로와 SHA-256이 있다. 공개 실행은 보관본에 의존하지 않는다.

## 역사 자료와 공식 사이트 표시

보조 탐색은 HTML의 근거 부록에 연결된 **과거 고정 커밋**에서 읽을 수 있다. 이 링크는 당시 결과를 확인하기 위한 것이며 현재 실행 파일 안내가 아니다. 현재 재현에는 위 명령과 이 폴더의 최종 설정을 사용한다. 원본별 이용 조건의 확인 상태는 [데이터 안내](data/README.md)에 정리했다.

공식 사이트의 분석 결과 목록은 `flow_log.json`을 읽는다. 이 사례는 별도 탐색 파이프라인을 사용해 해당 파일을 생성하지 않으므로, 이 PR만으로 공식 결과 목록에 자동 노출되지는 않는다. 프로젝트 등록과 분석 결과 노출은 별개다. 사이트 연동은 후속 논의로 남기며, 실제로 실행하지 않은 공통 엔진의 완료 로그를 만들지 않는다.
