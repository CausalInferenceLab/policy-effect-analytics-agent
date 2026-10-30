# 강남대로 버스 운행 변화와 월별 도로 속도 예측

2024년 6월 29일 버스 운행 조정 뒤 강남대로의 이동 기록이 어떻게 달라졌는지 살펴본 학생 프로젝트다. **남행·북행의 변화가 달랐다는 관찰**과 **공개가 늦은 월별 파일로 어디까지 예측할 수 있는가**를 다룬다. 정책의 인과 효과나 실시간 예측 서비스가 완성됐다는 주장은 하지 않는다.

먼저 [프로젝트 설명 HTML](project-overview.html)을 브라우저에서 열면 배경 → 데이터 → 분석 → 결과 → 활용 순서로 읽을 수 있다. 간결한 결과는 [report.md](report.md), 해석·활용의 한계는 [discussion.md](discussion.md), 실행 범위와 진행 기록은 [plan.md](plan.md)에 있다.

| 공개 구성 | 내용 |
|---|---|
| 설명·설계 | 이 문서, HTML, 계획·결과·토론, 데이터 안내, 설정 2개 |
| 실행 코드 6개 | 수집, 버스 비교, CPU 예측, 공통 함수, 제출 검사, HTML 검사 |
| 출처·기록 | 원본 68개 파일 계약, 결과·코드 해시를 담은 실행 명세 |
| 결과 6개 | 비교표 2개, HTML 근거 수치표 2개, 그림 2개 |

사례 파일은 총 24개다. 저장소 루트의 테스트 3개와 기존 카탈로그 변경 2개를 합쳐 PR 변경 파일은 29개다. 원본·모델·새 실행 결과는 Git에 넣지 않는다.

## 설치와 빠른 확인

아래 명령은 **이 사례 폴더에서** 실행한다. HTML과 기본 수치 검사는 Python 3.11 이상 표준 라이브러리만으로 가능하다.

```bash
python review_submission.py
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Windows에서는 `.venv/bin/python`을 `.venv/Scripts/python.exe`로 바꾼다. PyTorch·CUDA는 필요 없다. 기본 검사는 저장된 결과의 무결성을 확인하며, 학습을 다시 돌렸다는 의미는 아니다.

## 원본부터 실행

원본 내려받기 주소·요청 인자·크기·SHA-256은 [source-manifest.json](source-manifest.json)에 고정되어 있다. 기존 탐색 보고서·감사 JSON·모델 없이 아래 순서로 실행할 수 있다. 공급자가 원본을 교체하면 해시 불일치로 중단한다.

```bash
.venv/bin/python fetch.py --run-id collect-01
.venv/bin/python estimate.py --inputs runs/collect-01/inputs.json --run-id bus-01
.venv/bin/python forecast.py features --inputs runs/collect-01/inputs.json --run-id features-01
.venv/bin/python forecast.py train --features runs/features-01/features.json --run-id train-01
.venv/bin/python forecast.py evaluate --features runs/features-01/features.json --training runs/train-01/training.json --run-id evaluation-01
.venv/bin/python review_submission.py --bus-results runs/bus-01/comparisons.csv --forecast-results runs/evaluation-01/metrics.csv
```

각 실행 ID는 새 이름이어야 한다. 기존 데이터·모델을 덮어쓰지 않고 `runs/<ID>/` 아래에 입력·설정·코드 해시와 결과를 기록한다. 다운로드와 전체 정규화는 자료량에 따라 오래 걸린다. 최소 25 GiB 여유 공간을 권장하며 학습은 CPU 스레드 2개로 순차 실행한다. 재학습은 라이브러리·플랫폼 차이에 따라 작은 수치 차이가 날 수 있다.

기존 로컬 자료가 있으면 `fetch.py --run-id collect-02 --reuse-cache`로 명세에 해시가 등록된 정규화 파일을 재사용할 수 있다. 다른 폴더에 있으면 `--local-source-root /자료가_있는_사례폴더`를 함께 지정한다. 버스만 확인하려면 `--kind bus_time`, 도로만 수집하려면 `--kind road_speed`를 쓴다.

## 무엇이 재현되는가

- 버스: 원래 14개와 공식 폐선 542번 제외 13개를 동일 날짜/원래 관측률 두 조건으로 비교한 30행 전체.
- 예측: 달력만/공개된 과거 월 자료를 사용하는 CatBoost 8회와 3개월 경험 프로필 기준선. 두 기간·두 예측 간격·전체/저녁/링크별/월별 조건을 모두 포함한다.
- 과거의 경보·승객 가중·GPU·지하철 등 보조 분석은 HTML의 **역사적 수치 스냅샷**으로 남는다. 229개 수치 전체의 해시는 검증하지만, 축약 코드로 그 실험 전부를 다시 수행하지는 않는다. 핵심 비교표와 직접 대조되는 수치의 목록은 [run_manifest.json](run_manifest.json)에 있다.

초기 [plan.yaml](plan.yaml)은 공통 엔진용 DiD 설계 기록이다. 최종 분석의 실행 규칙은 [analysis-plan.yaml](analysis-plan.yaml)이며, 이 사례를 `core.agent`로 실행하는 경로는 최종 재현 절차가 아니다.

확장 탐색 코드·중간 보고서·개별 테스트는 저장소 밖의 보관본으로 옮겼다. 이력 기준점은 `89156f6b9ac4fc8d0990e1297ba3f3e367197fa4`이며, 보관본에는 원래 경로와 SHA-256이 있다. 공개 실행은 보관본에 의존하지 않는다.
