# 강남대로 광역버스 분산과 단기 교통 예측

2024년 버스 운행 조정 전후 일반도로의 퇴근 시간 속도를 비교하고, 같은 자료의 과거 168시간으로 다음 1·3시간 속도를 예측하는 학생 프로젝트다. 작성자는 `sgim49697-ops`, 트랙은 **B. 가설과 분석**이다.

작업 제안: [이슈 #53](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues/53).

**실행 코드와 합성자료 검증을 완료했고, 실자료 분석은 근거 확인을 기다리는 단계다.** 월별 원본 20개를 확보했다. [계획 PR #54](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/pull/54)와 구현 브랜치 `sgim49697-ops/gangnam-pipeline`을 분리했다. 실제 정책 효과와 모델 성능은 아직 계산하지 않았다. 시간 표기·결측·이용 조건·2023년 속성 변경·비교 도로 노출에 미해결 사항이 있다.

## 문서와 설정

| 파일 | 역할 |
|---|---|
| [plan.md](plan.md) | 범위·고정 규칙·단계별 완료 조건·진행 기록 |
| [plan.yaml](plan.yaml) | 저장소 공통 엔진 스키마의 정책 분석 계획 |
| [corridors.yaml](corridors.yaml) | 링크·방향·가중치·기간·품질 기준 |
| [ml_config.yaml](ml_config.yaml) | 시간 분할·모델 후보·학습·평가 규약 |
| [data_contract.yaml](data_contract.yaml) | 자료 정의·이용 조건·공휴일·그래프의 근거 상태 |
| [evidence.md](evidence.md) | 직접 확인한 근거와 새로 발견한 자료 차이 |
| [source-manifest.json](source-manifest.json) | 원본 20개의 다운로드 인자·크기·해시. 속도값 없음 |
| [verification-request.md](verification-request.md) | 외부 AI·기관 확인을 위한 후속 질문. 미발송 |
| [model-notes.md](model-notes.md) | 모델 출처·구현 범위·GPU 검증 설명 |
| [research-request.md](research-request.md) | 최초 외부 조사 요청서 |

받은 「강남대로 버스 정책 분석과 교통 예측 모델 단기 실행계획.md」는 원문 그대로 보존했다. 최신 실행 규칙은 그 원문에 덮어쓰지 않고 위 설정과 계획에 반영한다.

## 실행 환경

아래 명령은 현재 구현 브랜치에서 실행할 수 있다. 저장소 루트에서 개인 폴더로 이동한다.

```bash
cd cases/sgim49697-ops-gangnam-bus-2024
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip check --python .venv/bin/python
.venv/bin/python -c "import sys; print(sys.executable)"
```

GPU는 장비·드라이버와 [공식 PyTorch 안내](https://pytorch.org/blog/pytorch-2-13-release-blog/) 및 [NVIDIA 호환성](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)을 확인한 뒤 설치한다. 이 장비의 검증 환경은 RTX 5070 Ti, 드라이버 610.88, Python 3.12.12, PyTorch 2.13.0/cu130이다.

```bash
nvidia-smi
uv pip install --python .venv/bin/python -r requirements-gpu.lock
uv pip show --python .venv/bin/python torch torchvision torchaudio
uv pip check --python .venv/bin/python
.venv/bin/python smoke.py
```

`smoke.py`는 합성자료만 사용한다. DLinear·PatchTST 각 100 step, 그래프 모델 각 2 step, CatBoost와 단순 기준선, 고정 revision Chronos2 추론을 검증한다. 실제 연구 성능이 아니다. CPU 환경에서는 `smoke.py --device cpu --models last_value weekly_naive weekday_hour_mean catboost`를 사용한다.

## 수집·분석 순서

```bash
# 현재도 가능: 원본·메타데이터만 수집. 속도 수치를 해석하지 않는다.
.venv/bin/python fetch.py --metadata-only
.venv/bin/python fetch.py --scope ml --metadata-only
.venv/bin/python validate.py --structural-only

# 공식 정의·역사적 노출을 확인하고 설정을 커밋한 지 24시간 이상 지난 뒤 실행.
.venv/bin/python validate.py
.venv/bin/python fetch.py
.venv/bin/python estimate.py
.venv/bin/python fetch.py --scope ml
.venv/bin/python forecast.py train --run main_v1 --models all
.venv/bin/python forecast.py evaluate --run main_v1 --models all --split pre_test
.venv/bin/python forecast.py evaluate --run main_v1 --models all --split transition
.venv/bin/python forecast.py evaluate --run main_v1 --models all --split post_test
.venv/bin/python forecast.py compare --run main_v1 --models all --split post_test
```

현재 `validate.py`는 미해결 근거를 출력하고 종료 코드 2를 반환하는 것이 정상이다. `--structural-only`는 설정 문법·구조 점검용이며 분석 허가가 아니다. `pending`은 출처를 확인한 뒤에만 `verified`로 바꾼다. 24시간 경과만으로 자료 관문이 해제되지 않는다.

검증된 그래프가 없으면 `all`의 DCRNN·STGCN은 보류 기록을 남긴다. 그래프를 확보한 경우 `--graph data/graph/edges.csv`를 학습·평가 양쪽에 전달한다. CSV는 `source_link,target_link,weight`, 같은 경로의 `edges.source.json`은 `verified,source,sha256,node_ids,valid_from,valid_to`를 갖춰야 한다. 전체 학습·평가 기간의 유효성을 요구한다.

비우천 민감도는 공식 ASOS 108 일별 CSV를 `weather.py 입력.csv --evidence 근거.json`으로 정규화하고 `estimate.py --weather data/weather/daily.csv`로 실행한다. 근거에는 `verified,source,raw_sha256,unit,blank_precipitation`이 필요하며 빈칸을 0으로 바꾸려면 공식 정의가 있어야 한다. 예측 입력에는 미래 실제 날씨를 쓰지 않는다.

`fetch.py` 기본 실행은 기준을 만족할 때 `data/panel.csv`를 만든다. 비교군 부족이면 `data/descriptive.csv`만 만든다. 개인 `estimate.py`는 `runs/policy/`에 기술통계·DiD·주별 격차·민감도·그림·보고서를 생성한다. **공통 `make flow`는 이 개인 실행기를 호출하지 않는다.** 개인 진단은 위 명령으로 재현한다.

## 저장·검증 규칙

원본·Parquet·기상자료는 `data/`, 예측 행·체크포인트·실행 로그는 `runs/`에 두며 Git에서 제외한다. 실행 폴더는 덮어쓰지 않는다. 실자료 결과 공개 전 이용 조건을 확인하고 필요한 집계·그림·해석만 후속 결과 PR에 넣는다. 다른 참여자의 사례와 `core/`, `site/`는 수정하지 않는다.

저장소 루트의 기본 검증은 `make check PY=.venv/bin/python`이다. 선택 ML 의존성까지 설치한 환경에서는 아래 명령으로 사례 테스트를 모두 실행한다.

```bash
cases/sgim49697-ops-gangnam-bus-2024/.venv/bin/python -m pytest tests/test_gangnam_bus.py
```
