# 강남대로 광역버스 분산과 단기 교통 예측

2024년 버스 운행 조정 전후 일반도로의 퇴근 시간 속도를 비교하고, 같은 자료의 과거 168시간으로 다음 1·3시간 속도를 예측하는 학생 프로젝트다. 작성자는 `sgim49697-ops`, 트랙은 **B. 가설과 분석**이다.

작업 제안: [이슈 #53](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues/53).

**20개월 실자료의 수집·정책 비교·5개 모델의 3개 시드 학습·9개 모델의 세 기간 평가를 완료했다.** [결과 보고서](report.md)와 [해석·한계](discussion.md)를 먼저 읽으면 된다. [계획 PR #54](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/pull/54), [구현·결과 PR #55](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/pull/55)를 분리했으며 작업 브랜치는 `sgim49697-ops/gangnam-pipeline`이다. 사용자 요청에 따라 24시간 대기 대신 명시적 탐색 모드를 사용한다. 시간 표기·0값·측정 일관성·비교 도로 노출·그래프는 검증된 사실과 구별해 가정으로 남긴다.

## 문서와 설정

**후속 분석 완료:** [정류장·방향별 결과](followup-report.md)에서 4~8월 버스·교통량 원본 20개와 주변 도로 88개 링크를 분석했다. 남행 강남역의 특정 구간에서 기록 운행시간 지수가 약 48% 낮아졌지만 북행은 다른 양상을 보였다. 단위·집계 정의가 미확인인 지수를 실제 분 단위나 인과 효과로 해석하지 않는다. [관련 논문 2편과 공식 자료 검토](literature.md), [추가 자료·저속 경보 후속 계획](followup-plan.md)을 함께 제공한다.

| 파일 | 역할 |
|---|---|
| [report.md](report.md) | 정책 비교·9개 모델 성능·그림·학습 자원 |
| [discussion.md](discussion.md) | 결과 해석·한계·계획에서 바뀐 것 |
| [followup-plan.md](followup-plan.md) | 추가 자료의 실제 접근성·품질, 추천 주제 3개·다음 실행·외부 확인 질문 |
| [followup-report.md](followup-report.md) | 정류장·방향·시간대별 버스 지수와 주변 도로·교통량의 실행 결과·그림 |
| [literature.md](literature.md) | 2025년 관련 논문 2편·공식 분석자료의 적용과 한계 |
| [followup_config.yaml](followup_config.yaml) / [followup-policy.yaml](followup-policy.yaml) | 후속 탐색 규칙·당시 노선군·정류장 번호와 현재 ID의 구분 |
| [followup-sources.json](followup-sources.json) / [research-sources.json](research-sources.json) | 후속 원본 20개·문헌 출처와 해시 |
| [followup.py](followup.py) / [results/followup/audit.json](results/followup/audit.json) | 추가 수집·추출·분석·그림의 진입점과 품질 감사 |
| [discovery-sources.json](discovery-sources.json) | 추가 공식 원본 11개의 요청·크기·해시 |
| [discovery_config.yaml](discovery_config.yaml) | 결과를 본 뒤 정한 표본·결합·상대 저속 진단 규칙 |
| [discover.py](discover.py) | 추가 원본 수집·주간 품질 점검·저장된 예측의 저속 진단 |
| [results/discovery/data_audit.json](results/discovery/data_audit.json) | 추가 자료의 결측·중복·결합률 |
| [results/forecast_metrics.csv](results/forecast_metrics.csv) | 3개 시험 기간·3개 평가 집단·1/3시간 오차 집계 |
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
# 70e8ec7에서 결과를 보기 전 가정·제외 링크·계산 예산을 고정했다.
.venv/bin/python validate.py
.venv/bin/python fetch.py --scope ml --workers 4
.venv/bin/python audit.py
.venv/bin/python estimate.py
.venv/bin/python forecast.py train --run exploration_20261028 --models all --graph data/graph/edges.csv
for split in pre_test transition post_test; do
  .venv/bin/python forecast.py evaluate --run exploration_20261028 --models all --split "$split" --graph data/graph/edges.csv
  .venv/bin/python forecast.py compare --run exploration_20261028 --models all --split "$split" --graph data/graph/edges.csv
done
.venv/bin/python summarize.py --run exploration_20261028
```

새 실행에는 새 `--run` 이름을 사용한다. 실행 중 오류가 나면 로그·부분 결과를 보존하고 원인을 해결한 뒤 다른 실행 이름으로 재시작한다. 실제 학습에서는 독립적인 CPU CatBoost와 GPU 모델 작업을 동시에 실행할 수 있다. GPU 모델끼리는 순차 실행한다.

`validate.py`는 현재 `mode: exploratory`와 가정 목록을 출력한다. `assumed`는 공식 확인 완료를 뜻하지 않는다. 탐색 모드와 사용자 요청 근거가 없으면 기존의 검증 완료·커밋 후 24시간 관문이 적용된다. 어떤 모드에서도 미커밋 설정으로 실자료를 실행하지 않는다.

`audit.py`는 원자료의 결측 사유, train 관측률로 고른 링크, 분할별 공통 창, 메타데이터 변경 이력을 기록한다. `data/graph/edges.csv`는 전 기간에 안정적인 동일 도로·방향의 종점명→시점명 연결이다. 동반 근거는 `verified: false`, `status: assumed`이며 역사적 회전 가능성을 검증한 지도가 아니다.

공식 ASOS 108 일별 CSV와 결측 정의를 확보하면 `weather.py 입력.csv --evidence 근거.json` 후 `estimate.py --weather data/weather/daily.csv`로 비우천 민감도를 추가할 수 있다. 아직 빈 표시의 정의를 확인하지 못했으므로 이번 실행에서 기상 결측을 무강수로 바꾸지 않는다. 예측 입력에 미래 실제 날씨를 쓰지 않는다.

`fetch.py` 기본 실행은 기준을 만족할 때 `data/panel.csv`를 만든다. 비교군 부족이면 `data/descriptive.csv`만 만든다. 개인 `estimate.py`는 `runs/policy/`에 기술통계·DiD·주별 격차·민감도·그림·보고서를 생성한다. **공통 `make flow`는 이 개인 실행기를 호출하지 않는다.** 개인 진단은 위 명령으로 재현한다.

## 저장·검증 규칙

원본·Parquet·기상자료는 `data/`, 예측 행·체크포인트·실행 로그는 `runs/`에 두며 Git에서 제외한다. 실행 폴더는 덮어쓰지 않는다. 월별 파일의 개별 이용 조건은 미확정으로 남기고 공개 산출물은 필요한 집계·자체 그림·해석·출처로 제한한다. 체크포인트와 개별 예측은 재배포하지 않는다. 다른 참여자의 사례와 `core/`, `site/`는 수정하지 않는다.

저장소 루트의 기본 검증은 `make check PY=.venv/bin/python`이다. 선택 ML 의존성까지 설치한 환경에서는 아래 명령으로 사례 테스트를 모두 실행한다.

```bash
cases/sgim49697-ops-gangnam-bus-2024/.venv/bin/python -m pytest tests/test_gangnam_bus.py
```
