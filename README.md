# policy-effect-analytics-agent

> **에이전틱 AI × 데이터 — 문제 정의부터 효과 분석 자동화까지**
> NIPA OpenUp 오픈소스 AI 특화형 2차 · Track 3 · 멘토 신진수 (가짜연구소 인과추론팀)

**English summary.** An open-source toolkit and case library for estimating the effects of Korean public policies with open data. Each group writes a pre-registered `plan.yaml`, fetches public data, runs a causal estimator (DiD / event study / synthetic control …), and publishes a reproducible report. LLM agents (LangGraph + open LLMs) automate collect → metrics → estimate → report. Results are browsable in a Streamlit app.

---

**대시보드**: https://causalinferencelab.github.io/policy-effect-analytics-agent/ (GitHub Pages, `main` 반영 시 자동 배포)

## 왜 하나요?

1. 공공·사회 문제를 **데이터로 정의**하고, 그 해법(정책)이 **실제로 어떤 효과를 냈는지 추정**합니다.
2. 수집 → 지표 구조화 → 효과 추정 → 리포팅 전 과정을 **LLM 에이전트로 자동화**합니다.
3. 같은 문제를 다루는 누구나 바로 쓸 수 있도록 **GitHub + 분석 플랫폼(Streamlit)** 으로 공개합니다.

핵심 원칙: **결과를 보기 전에 `plan.yaml`을 먼저 커밋한다.** (사전 등록 → 사후 끼워맞추기 방지)

## 저장소 구조

```
core/                 공통 엔진 (Data 담당) — 어댑터, schema/plan.py, estimators, report, agent
cases/
  _template/          새 케이스 시작용 템플릿 (복사해서 사용)
  _example_*/         참고용 예시 케이스
  <조-주제>/          조별 케이스 (plan.yaml, fetch.py, estimate.py, report.md, figures/)
app/streamlit_app.py  케이스 브라우저 (API 키 없이 실행)
docs/ops/             조별 운영 가이드, GitHub 온보딩, 모니터링
catalog/              정책 × 데이터셋 카탈로그 (이슈 → 데이터 연결)
docs/strategy/        문제 정의·전략 문서
scripts/              운영 스크립트 (weekly_activity.py 등)
tests/                테스트
.github/              CI, PR/이슈 템플릿, CODEOWNERS
```

## 빠른 시작

```bash
git clone https://github.com/CausalInferenceLab/policy-effect-analytics-agent.git
cd policy-effect-analytics-agent

# uv 권장 (pip도 가능: python -m venv .venv && pip install -e ".[dev]")
uv venv -p 3.11 && source .venv/bin/activate
make install          # = uv pip install -e ".[dev]"
cp .env.example .env  # API 키 입력 (공공데이터포털, KOSIS, LLM)

make check            # ruff + pytest
make app              # Streamlit 케이스 브라우저 (http://localhost:8501)
```

에이전트/인과 추가 기능: `uv pip install -e ".[agent,causal]"`

## 케이스 추가하기 (4단계)

```bash
git switch -c group3/plan
cp -r cases/_template cases/group3-youth-rent   # 폴더명: <조>-<주제>, 소문자-하이픈
```

1. **질문 정의** — `plan.yaml` 작성 (질문·처치·대조·시점·지표·추정법·가정·중단조건·데이터 라이선스) → **먼저 PR**
2. **수집** — `fetch.py`: 공공데이터 → `data/raw/`(커밋 금지) → 정제 결과만 `data/processed/`
3. **추정** — `estimate.py`: `core.estimators`로 효과 추정 + 반증(placebo 등) → `figures/*.png`
4. **리포트** — `report.md`: 결과·한계·정책 시사점. `make app`에서 바로 보입니다.

자세한 절차: [`cases/_template/README.md`](cases/_template/README.md), 협업 규칙: [`CONTRIBUTING.md`](CONTRIBUTING.md), GitHub가 처음이라면: [`docs/ops/github-onboarding.md`](docs/ops/github-onboarding.md), 조별 운영: [`docs/ops/group-guide.md`](docs/ops/group-guide.md)

## 7주 로드맵

| 주차 | 목표 | 산출물 (커밋 기준) |
|---|---|---|
| 1 | 온보딩·조 편성·주제 후보 | 이슈 `케이스 제안` 등록, 첫 PR(자기소개/브랜치) |
| 2 | 문제 정의·데이터 탐색 | `cases/<조>/plan.yaml` 초안 PR (결과 보기 전) |
| 3 | 수집 자동화 | `fetch.py`, 데이터 출처·라이선스 명시 |
| 4 | 지표 구조화·1차 추정 | `estimate.py`, 기본 그림 |
| 5 | 강건성·반증 + 에이전트화 | placebo/민감도, LangGraph 노드 연결 |
| 6 | 리포트·플랫폼 | `report.md`, Streamlit 반영 |
| 7 | 발표·회고·공개 정리 | 최종 PR 머지, 릴리스 태그 |

## 이슈 → 주제 → 정책 전체 → 효과

소셜 반응(뉴스 제목·SNS 글)은 **어느 주제를 볼지까지만** 정합니다. 화제가 된 정책 하나만 골라 분석하면
결과를 보고 사례를 고르는 셈이 되기 때문입니다(출발 키트 05). 주제가 정해지면 그 주제의 정책을
전부 모으고(법제처 조례·고시), 세 관문(언제·누가·무엇을)을 통과한 것만 분석합니다.
주제 목록: `catalog/topics.yaml` · 정적 대시보드: `python site/build.py` → `_site/`

1. **정책 식별**: `catalog/policies.yaml`(정책 × 데이터셋 카탈로그)에서 키워드로 찾습니다. LLM은 후보 중에서 고르는 보조 역할만 합니다.
2. **데이터셋 추천**: 카탈로그에 검증해 둔 데이터셋과 공공데이터포털 실시간 검색 결과를 보여줍니다.
3. **분석 설계**: 카탈로그의 설계(이중차분·합성통제·단절 시계열)로 정합니다. LLM이 고르지 않습니다.
4. **효과 분석**: 사전 등록된 `plan.yaml`로 아래 Flow를 실행합니다.

```bash
make app        # 사이드바 '이슈 → 데이터 → 효과'
python -c "from core.discovery import discover; r=discover('토허제 확대하고 집값 잡혔나'); print(r.top.name, r.next_step)"
```

샘플: [`cases/t3-land-permit-2025`](cases/t3-land-permit-2025/) (현재 시뮬레이션 데이터, API 키 발급 후 실데이터로 전환)

## Flow — 6단계 에이전트 흐름

`core.agent`가 케이스 하나를 아래 6단계로 실행하고 `cases/<케이스>/flow_log.json`에 단계별 결과를 남깁니다. 앱의 **Flow** 페이지(`make app` → 사이드바 Flow)에서 실행하거나 저장된 로그를 볼 수 있습니다.

| 단계 | 하는 일 | 주차 |
|---|---|---|
| ① 문제 정의 | `plan.yaml` 검증 + 사전 등록(커밋) 확인 — 추정 전에 확정 | W3 |
| ② 데이터 수집 | 공공데이터 수집·출처/라이선스 기록 | W2 |
| ③ 지표 구조화 | 패널 구성·품질 점검 | W3 |
| ④ 효과 추정 | DiD/이벤트 스터디/ITS + 반증 → 식별됨·조건부·식별 불가 | W4–5 |
| ⑤ 과잉해석 가드 | 결론 보류 규칙 + 인과 단정 표현 검사 | W6 |
| ⑥ 리포트 | `report.md`·그림·재현 기록 | W7 |

```bash
make flow CASE=cases/_example_night_clinic   # = python -m core.agent <케이스> --allow-uncommitted
```

`--allow-uncommitted`는 데모용입니다. 실제 분석은 `plan.yaml`을 먼저 커밋한 뒤 플래그 없이 실행하세요. LLM 서술은 `.env`에 키를 넣고 `--llm`으로 켭니다(`uv pip install -e ".[agent]"`).

## 라이선스

- **코드**: MIT ([LICENSE](LICENSE)) — © 가짜연구소 Causal Inference Team
- **데이터**: 각 출처의 이용 조건을 따릅니다 (공공누리 제1~4유형, KOSIS 이용약관 등). 각 케이스의 `plan.yaml > data_sources[].license`에 반드시 명시하고, 재배포가 제한된 원자료는 커밋하지 않습니다.
- 개인정보가 포함된 원자료는 어떤 경우에도 커밋하지 않습니다.

## 기여

[CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
