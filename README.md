# policy-effect-analytics-agent

> **에이전틱 AI × 데이터 — 문제 정의부터 효과 분석 자동화까지**
> NIPA OpenUp 오픈소스 AI 특화형 2차 · Track 3 · 멘토 신진수 (가짜연구소 인과추론팀)

**English summary.** An open-source toolkit and case library for estimating the effects of Korean public policies with open data. Each group writes a pre-registered `plan.yaml`, fetches public data, runs a causal estimator (DiD / event study / synthetic control …), and publishes a reproducible report. LLM agents (LangGraph + open LLMs) automate collect → metrics → estimate → report. Results are browsable in a Streamlit app.

---

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
docs/ops/             GitHub 온보딩, 모니터링 가이드
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

자세한 절차: [`cases/_template/README.md`](cases/_template/README.md), 협업 규칙: [`CONTRIBUTING.md`](CONTRIBUTING.md), GitHub가 처음이라면: [`docs/ops/github-onboarding.md`](docs/ops/github-onboarding.md)

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

## 라이선스

- **코드**: MIT ([LICENSE](LICENSE)) — © 가짜연구소 Causal Inference Team
- **데이터**: 각 출처의 이용 조건을 따릅니다 (공공누리 제1~4유형, KOSIS 이용약관 등). 각 케이스의 `plan.yaml > data_sources[].license`에 반드시 명시하고, 재배포가 제한된 원자료는 커밋하지 않습니다.
- 개인정보가 포함된 원자료는 어떤 경우에도 커밋하지 않습니다.

## 기여

[CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
