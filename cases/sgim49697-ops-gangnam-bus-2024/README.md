# 강남대로 버스 분산 이후의 방향별 변화와 단기 예측

**“강남역 버스는 양방향으로 좋아졌을까?”** 2024년 광역버스 분산 전후의 기록을 방향·구간·시간별로 확인하고 다음 해까지 연결한 학생 프로젝트다. 작성자 `sgim49697-ops`, 트랙 **B. 가설과 분석**. 일반도로 속도 범위·저속 경보 예측은 별도 확장으로 다룬다.

먼저 **[확장 탐색 종합 보고서](overnight-summary.md)**를 읽으면 된다. 남행 강조 구간은 2024년 사전 대비 그해 여름 −48.45%, 북행 강조 구간은 +32.59%였다. 2025년에도 수준 차이가 남았고, 인접 구간 합·같은 노선의 16시간 공동 표본에서도 반대 양상을 확인했다. 버스 기록의 시간 단위·정차 경계는 미확인이므로 실제 분 단위 절감이나 정책의 인과 효과로 해석하지 않는다.

**2026-10-29 추가 확인:** [과거 정류장·노선 이력](deepening-history-report.md)에서 32개 정류장의 ID·ARS와 정책일 양쪽의 좌표 기록을 대조했다. 2024-08-24 폐선된 542번을 제외한 [고정 13개 노선 비교](deepening-cohort-report.md)에서도 2024년 남행 −49.71%·북행 +41.03%가 유지됐다. 폐선 뒤 해당 노선의 시간·횟수 행은 없었고, 경계 네 날짜의 원본 대조 5,376건도 일치했다. [두 번째 탐색 계획](deepening-plan.md)에 따라 기록 정의와 추가 운영 이력을 계속 확인한다.

**[공개 핵심 수치](results/overnight/review/key_numbers.csv)**는 원본 집계의 선택 조건과 연결된다. Python 3.12에서 `python review_overnight.py --check`를 실행하면 원본·모델·외부 패키지 없이 수치와 공개 동결 해시를 대조할 수 있다. [재현 안내](overnight-reproduction.md)는 공개 검토, 기존 로컬 모델 검증, 원자료 계산의 의존성과 한계를 구분한다.

작업 제안 [이슈 #53](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues/53), [계획 PR #54](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/pull/54), [구현·결과 PR #55](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/pull/55). 작업 브랜치는 `sgim49697-ops/gangnam-pipeline`이며 PR은 초안이다. 최초 일반도로·GPU 모델 비교는 아래 이전 분석 문서에 보존했다. 2026년 잠금 시험값은 사용하지 않았다.

## 최신 결과와 근거

| 읽을 내용 | 문서 |
|---|---|
| 추가 탐색: 과거 ID·폐선 구성·시간 명세 | [역사 목록](deepening-history-report.md), [13개 노선 비교](deepening-cohort-report.md), [정의 확인](deepening-definition-report.md), [진행 계획](deepening-plan.md) |
| 추가 탐색: 경기 노선 이용객의 실제 범위 | [대표일·이름 후보·중복 감사](deepening-gyeonggi-report.md): 2023~2025년 330만 행, 월 합계·역사 노선 ID와 구별 |
| 추가 탐색: 같은 강남대로의 다른 변화 | [양재천 주변 14개 링크 비교](deepening-road-report.md), [공개 형상·표준링크 대응](deepening-geometry-report.md): 일반도로 공간 차이와 동시 공사 근거 |
| 추가 탐색: 시행일 전의 변화와 추세 가정 | [전환 주간·고정일 회귀·기상 비교](deepening-transition-report.md): 12,096개 원본 값/상태와 1,674개 계수 대조, 사전 하락과 모형별 부호 차이 |
| 추가 탐색: 경보가 실제로 준비되는 시점 | [저속 구간의 시작·재알림](deepening-episode-report.md), [월별 파일 공개 지연](deepening-availability-report.md): 시간별 정밀도와 시작 감지, 최근 입력의 접근 조건 |
| 추가 탐색: 공개 과거 월만 쓰는 예측 | [별도 8회 학습과 같은 조건의 달력 비교](deepening-archive-report.md): 시드 17 H1 MAE가 여름 29.29%·가을 21.26% 낮음, 가을 구간 포괄률 한계 포함 |
| 추천 프로젝트·주요 결과·채택/보류·추가 수집 순위 | [종합 보고서](overnight-summary.md) |
| 변화 시점과 32개월의 지속성 | [장기 궤적](overnight-timeline-report.md) |
| 강조 구간·단일 노선/구간 제외·공동 변동 범위·운영 기록 | [구간 분석](overnight-segment-report.md) |
| 옆 구간으로 기록이 이동했는지와 순서 키 | [인접 구간 합](overnight-path-report.md) |
| 같은 노선·같은 날짜의 7~22시 모양 | [시간대 공동 표본](overnight-hour-report.md) |
| 방향 전체의 2025년 연장·지역 기상 비교 | [지속성](overnight-persistence-report.md) |
| 노선군·집계·승객 가중의 한계 | [노선군](overnight-route-report.md), [관측·누락](overnight-observation-report.md) |
| 시간·운행횟수·승차 공동 표본과 카드 합계 | [운영·카드](overnight-operations-report.md) |
| 주변 일반도로·교통량·이름/범위 민감도 | [도로 맥락](overnight-road-report.md) |
| 지하철 8역·24개월 수요 맥락 | [지하철](overnight-subway-report.md) |
| 환승·출도착·정류장 이력·2022년 제외·동시 변화 | [보조 자료](overnight-auxiliary-report.md), [정책·연구 맥락](overnight-context-report.md) |
| 최초 고정 시험과 단순 예측 기준 | [예측 결과](overnight-forecast-report.md), [기준 비교](overnight-baseline-report.md) |
| 반복 패턴과 다른 조건부 저속·차이 점수 | [조건부 저속](overnight-conditional-report.md) |
| 구간 보정·비 올 때 오류·실제 발행 예산 | [구간 보정](overnight-interval-report.md), [기상 성능](overnight-weather-performance-report.md), [순차 경보](overnight-alert-report.md) |
| 미열람 2025년 9~12월의 고정 후보 확인 | [가을·겨울 추가 검증](overnight-confirmation-report.md) |
| 자료 정의·접근 조건·외부 AI에 전달할 질문 | [근거](overnight-evidence.md), [확인 요청서](verification-request.md) |
| 단계별 실행·검증·커밋 근거 | [확장 계획·진행 기록](overnight-plan.md), [재현 안내](overnight-reproduction.md) |

각 보고서에서 설정 YAML, 전체 CSV, 출처 JSON, 그림과 입력/출력 해시로 이동할 수 있다. 원본·Parquet·개별 예측·모델은 `data/`와 `runs/`에 보존하고 Git에서 제외한다. 공개 원본의 결측·손상·기간 불일치와 분석 조건 실패를 보고서에서 제외하지 않았다.

## 이전 분석과 최초 계획

| 문서·설정 | 역할 |
|---|---|
| [report.md](report.md), [discussion.md](discussion.md), [model-notes.md](model-notes.md) | 최초 20개월 일반도로·GPU 모델 비교·해석·학습 기록 |
| [followup-report.md](followup-report.md), [followup-plan.md](followup-plan.md), [literature.md](literature.md) | 최초 버스·주변 도로 확장과 관련 논문·공식 분석자료 |
| [directional-report.md](directional-report.md), [directional_config.yaml](directional_config.yaml) | 노선 이동·전년·가을·기상 비교의 출발점 |
| [plan.md](plan.md), [plan.yaml](plan.yaml), [corridors.yaml](corridors.yaml), [ml_config.yaml](ml_config.yaml), [data_contract.yaml](data_contract.yaml) | 최초 범위·프로토콜·고정 규칙과 진행 기록 |
| [evidence.md](evidence.md), [source-manifest.json](source-manifest.json), [discovery-sources.json](discovery-sources.json) | 최초 근거와 원본 다운로드 인자·해시 |
| [research-request.md](research-request.md) | 최초 외부 조사 요청서 |

받은 「강남대로 버스 정책 분석과 교통 예측 모델 단기 실행계획.md」는 원문 그대로 보존했다. 최초 프로토콜 4개를 수정하지 않고 후속 규칙을 별도 설정에 기록했다. 아래 환경·실행 예시는 최초 일반도로 분석의 기록이며, 확장 탐색의 현재 실행은 [재현 안내](overnight-reproduction.md)를 먼저 따른다.

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
