# 전남·광주 보고서의 잣대로 본 마산·창원·진해 통합(2010)

> 트랙 B 케이스. 담당 `buildergarlic`. 작업 제안 [#27](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues/27)의 두 번째 케이스.
> 학습·연구용 오픈소스 분석이며 정부·공공기관의 공식 평가가 아닙니다. 통합이 "실패했다"거나 "성공했다"는 결론을 미리 두지 않습니다.

## 질문

한국은행 광주전남본부·목포본부의 「전남·광주 행정통합에 따른 지역경제 영향 분석」(2026.7)은 통합의 **목표**를 청년 유출·고령화 대응,
행정 효율화와 지방재정 확대, 첨단산업·기업 유치로 두고, **지표**로 청년·고령 인구비율, GRDP·산업구조, 사업체·종사자, 고용률·실업률,
생산·고용유발효과를 쓰며, **성공**을 전국·타지역 평균 및 10년 전과의 상대 비교로 판단했습니다(`framework.md`).

같은 목표·지표·기준을 2010년 마산·창원·진해 통합에 대면, 통합 창원시는 13년 뒤 **통합의 목표 방향으로 비교 시들보다 더 달라졌는가?**

## 두 케이스의 역할 분담

| | [`buildergarlic-changwon-integration`](../buildergarlic-changwon-integration) (PR #35) | 이 케이스 |
|---|---|---|
| 잣대 | 통합 추진 당시 창원이 내건 목표(인구 100만, 재정) | 전남·광주 보고서(2026)가 쓴 목표·지표·기준 |
| 지표 | 주민등록인구·순이동률·재정자립도 | 사업체 종사자·사업체수·제조업 비중(고용부 사업체노동실태현황, 시군구)·재정자립도 (핵심) + 청년/고령 비율·청년 순이동·재정자주도·고용률·실업률·고부가 서비스 비중 (확장; 공무원 1인당 주민수는 자료 없음) |
| 추정 | 이벤트 스터디 + 무작위화 추론, 합성통제 | 같은 추정기 + 보고서식 벤치마크(전국 시·대도시·경남 시) + 산업연관 대응 + 사전 등록한 성공/실패 종합 규칙 |
| 공통 | 통합 전 3개 시 합산 → 같은 경계, 2010 제외, 2011 첫 사후연도, 대조군 62개 시 | |

## 파일

| 파일 | 누가 | 내용 |
|---|---|---|
| `framework.md` | 나 | 보고서에서 뽑은 목표(G1~G6)·지표·성공 기준(B1~B3)·모델(산업연관분석), 창원 대응표, 설문지 부록 |
| `plan.yaml` | 나 | 사전 등록 계획 — 핵심 4지표, 처치·대조, 추정·보류 규칙, 데이터 출처 |
| `indicators.yaml` | 나 | 보고서 지표 전체(12개)의 목표 방향·출처·기간과 **성공/실패 종합 규칙** (결과 전 커밋) |
| `fetch.py` | 나 | KOSIS 수집(`--probe`·`--discover` 로 통계표 확인) → 경계 재구성 → `data/panel.csv`(핵심) + `data/extended.csv`(확장) |
| `scorecard.py` | 나 | 12개 지표에 같은 추정기 → 지표별 ✅/❌/⚪ 와 종합 판정, 벤치마크 표, 그림 → `scorecard.md`·`scorecard.json` |
| `io_counterpart.py` | 나 | 보고서의 산업연관분석 대응: 레온티예프 계산기 + 보고서 승수를 창원 인센티브에 적용한 기대 효과 → `io_counterpart.md` |
| `discussion.md` | 나 | 해석과 한계. `make flow` 가 `report.md` 끝에 붙임 |
| `report.md`, `figures/`, `flow_log.json`, `run_manifest.json`, `scorecard.*`, `io_counterpart.*` | 자동 | 실데이터로 실행한 뒤 커밋 |

## 실행

```bash
cp .env.example .env                        # KOSIS_API_KEY= 에 KOSIS 공유서비스(https://kosis.kr/openapi) 무료 키
cd cases/buildergarlic-changwon-jeonnam-frame
python fetch.py --probe                     # ① 통계표 ID·분류·기간 확인 (후보 ID 가 틀리면 --discover <키워드> 로 찾아 fetch.py TABLES 와 plan.yaml 을 고침)
python fetch.py                             # ② 수집 → data/panel.csv, data/extended.csv (확장 지표는 실패해도 핵심은 진행)
cd ../.. && make flow CASE=cases/buildergarlic-changwon-jeonnam-frame   # ③ 핵심 4지표 → report.md
python cases/buildergarlic-changwon-jeonnam-frame/scorecard.py          # ④ 12개 지표 스코어카드 + 산업연관 대응
```

키 없이 파이프라인만 확인하려면 `python fetch.py --simulate` 로 **합성 패널**을 만듭니다(실데이터 아님, 결과 해석 금지).
Windows 콘솔(cp949)에서는 `$env:PYTHONUTF8=1`(cmd: `set PYTHONUTF8=1`) 뒤에 실행합니다. `make` 가 없으면 `python -m core.agent cases/buildergarlic-changwon-jeonnam-frame`.
자동 검사(`tests/test_changwon_jeonnam_frame.py`)는 합성 입력으로 다차원 KOSIS 표 정리·경계 재구성·판정 규칙·산업연관 계산·6단계 흐름을 네트워크 없이 점검합니다.

## 성공/실패를 가르는 규칙 (결과 전에 정함 — `indicators.yaml`)

- 지표별: 통합 후 평균효과(2009년 기준, 무작위화 추론 95% 구간)가 **0을 제외하고 보고서의 목표 방향**이면 ✅, 반대면 ❌, 그 밖(0 포함, 방향 미지정, 사전추세 기각)은 ⚪.
- 종합: 1차 지표(사업체 종사자수)가 ✅ 이고 ❌ 가 없으며 ✅ 가 절반 이상 → **성공 근거(조건부)**; 1차 지표가 ❌ 이거나 ❌ 가 절반 이상 → **실패 근거(조건부)**; 둘 다 있으면 **혼재**; 그 밖은 **판별 불가**.
- ⚪·판별 불가는 '효과 없음'이 아니라 '처치 단위 1개인 이 설계로는 가를 수 없음'입니다.

## 결과 (실데이터, 2026-10-22 수집)

**종합 판정: 판별 불가** — 11개 지표 모두 ⚪(✅ 0, ❌ 0), 공무원 1인당 주민수는 자료 없음. 1차 지표 사업체 종사자수(로그)의
통합 후 평균효과 −0.147 [−0.349, 0.059] (RI p 0.18), 사업체수 −0.097 [−0.325, 0.136], 재정자립도 −1.4%p [−13.0, 9.8].
사전추세는 실업률만 기각. 점추정치는 대부분 목표와 반대 부호지만 창원 한 곳을 62개 시와 견주는 설계에서 우연과 구별되지 않습니다.
자세한 표는 `scorecard.md`, 해석은 `discussion.md`(= `report.md` 끝).

KOSIS 에 전국사업체조사의 시군구 표가 없어 핵심 3지표(사업체수·종사자수·제조업)는 고용노동부 사업체노동실태현황 시군구 표로
받았습니다(`plan.yaml` 머리글, `discussion.md` '계획에서 바뀐 것').

## 상태

- [x] 보고서 프레임 추출(`framework.md`), 계획·지표 레지스트리·수집·스코어카드·산업연관 대응 코드, 자동 검사.
- [x] KOSIS 키로 `--probe` → 통계표 ID 확정(핵심 3지표는 사업체노동실태현황으로 교체) → 실데이터 실행 → `report.md`·`scorecard.md`·그림 커밋.
- [ ] 전국사업체조사 시군구 자료(SGIS·MDIS)로 핵심 지표 재검증, 경남 지역산업연관표로 `io_counterpart.py` 실행.
