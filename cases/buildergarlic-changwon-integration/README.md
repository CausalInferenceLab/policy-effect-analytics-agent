# 마산·창원·진해 통합(2010)의 효과 — 인구·인구이동·재정자립도

> 트랙 B 케이스. 담당 `buildergarlic`. 작업 제안 [#27](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues/27).
> 학습·연구용 오픈소스 분석이며 정부·공공기관의 공식 평가가 아닙니다. 통합이 "실패했다"거나 "성공했다"는 결론을 미리 두지 않습니다.

## 질문

2010년 7월 1일 마산시·창원시·진해시가 통합 창원시로 합쳐진 뒤, 같은 기간 행정구역이 바뀌지 않은 전국의
다른 기초 시 62곳과 비교해 창원의 **주민등록인구(주 지표)·순이동률·재정자립도**가 달라졌는가?
통합 추진 당시 내세운 목표(인구 100만 광역도시로 성장, 행정 효율·재정 건전성)를 공공데이터로 되짚는 것이 목적입니다.

## 왜 이 설계인가 — 통폐합 평가의 세 가지 함정

| 함정 | 이 케이스의 처리 |
|---|---|
| **경계가 바뀐다**: 통합 전 창원시(옛)와 통합 후 창원시는 다른 지역이다 | 통합 전은 마산·창원·진해 값을 합산해 통합 후와 같은 경계로 맞춘다(`fetch.py reconstruct`). 비율 지표(재정자립도)는 인구 가중 평균. 2010년은 반년만 통합된 전환연도라 모든 시에서 뺀다 |
| **처치가 하나뿐이다**: 통합 창원시 한 곳이라 보통의 표준오차·p값을 믿을 수 없다 | core 의 무작위화 추론(비교 시 하나를 차례로 '가짜 창원'으로 두는 placebo-in-space)이 자동으로 켜지고, 같은 패널로 합성통제(`synth.py`)를 보조로 돌린다 |
| **비교 대상이 오염된다**: 같은 기간 통합·분리·승격한 시, 창원과 접한 시 | 청주(2014 청원 통합)·공주·논산·계룡·제주·서귀포·화성·광주·양주·포천·당진·여주·울산·세종과 인접한 김해·밀양을 대조군에서 뺀다 |

데이터는 모두 KOSIS OpenAPI(무료 키)로 받습니다. 1998년부터 시군구 단위로 이어지는 표만 골랐습니다.

| 지표 | KOSIS 통계표 | 통합 전 3개 시 처리 |
|---|---|---|
| 주민등록 총인구 | `DT_1B040A3` 행정구역(시군구)별 성별 인구수 (행정안전부) | 합계 |
| 총전입·총전출 → 순이동률 | `DT_1B26001_A01` 시군구별 이동자수 (통계청) | 각각 합계 (3개 시 사이 이동은 상쇄) |
| 재정자립도 | `DT_1YL20921` e-지방지표 (행정안전부) — **ID 확인 필요**, 틀리면 `python fetch.py --list-fiscal` | 인구 가중 평균(근사) |

## 실행

```bash
cp .env.example .env            # KOSIS_API_KEY= 에 KOSIS 공유서비스(https://kosis.kr/openapi) 무료 키 입력
make flow CASE=cases/buildergarlic-changwon-integration     # ① 계획 확인 → ② fetch.py → … → ⑥ report.md
python cases/buildergarlic-changwon-integration/synth.py    # 보조: 합성통제 → synth_report.md, figures/synth_*.png
```

키 없이 파이프라인만 확인하려면 `python fetch.py --simulate` 로 **합성 패널**을 만들 수 있습니다(실데이터 아님, 결과 해석 금지).
자동 검사(`tests/test_changwon_integration.py`)는 이 합성 패널로 경계 재구성·합성통제·6단계 흐름을 네트워크 없이 점검합니다.

## 파일

| 파일 | 누가 | 내용 |
|---|---|---|
| `plan.yaml` | 나 | 사전 등록 계획. 초안(PR #28)에서 바뀐 점은 파일 머리글에 |
| `fetch.py` | 나 | KOSIS 수집 → 경계 재구성 → `data/panel.csv` (원자료는 `data/raw/`, 커밋 안 됨) |
| `synth.py` | 나 | 합성통제 + placebo-in-space + leave-one-out (core 에 합성통제가 생기면 옮길 후보) |
| `discussion.md` | 나 | 해석과 한계. `make flow` 가 `report.md` 끝에 붙임 |
| `report.md`, `figures/`, `flow_log.json`, `run_manifest.json`, `synth_results.json`, `synth_report.md` | 자동 | 실데이터로 실행한 뒤 커밋 |

## 상태

- [x] 계획 사전 등록(이 PR). 초안 PR #28 의 '1인당 행정운영경비' 설계를 KOSIS 로 재현 가능한 지표로 바꾼 이유는 `plan.yaml` 머리글과 `discussion.md`.
- [x] 수집·추정·보조 추정 코드와 자동 검사.
- [ ] KOSIS 키로 실데이터 실행 → `report.md`·`synth_report.md`·그림 커밋 (`analysis(buildergarlic-changwon-integration): …`).
- [ ] 같은 틀로 다른 통폐합 사례(청주·청원 2014, 제주 2006, KTX·SRT 분리 2016)를 돌릴 수 있는지 검토.
