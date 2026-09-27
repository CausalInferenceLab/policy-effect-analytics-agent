# 정책 효과 분석 플랫폼 · policy-effect-analytics-agent

**사람들이 묻는 정책, 정말 효과가 있었을까?**
소셜 반응에서 출발해, 그 주제의 정책을 전부 모으고, 공공데이터로 효과를 추정하는 오픈소스입니다.
결론을 낼 수 없으면 "식별 불가"라고 말하는 것까지가 이 프로젝트의 일입니다.

[대시보드 보기](https://causalinferencelab.github.io/policy-effect-analytics-agent/) · [어떻게 동작하나](https://causalinferencelab.github.io/policy-effect-analytics-agent/architecture.html) · [조별 운영 가이드](docs/ops/group-guide.md) · [GitHub 처음이라면](docs/ops/github-onboarding.md)

> 가짜연구소 인과추론팀 × NIPA 오픈업 오픈소스 AI 특화형 2차 트랙3 「에이전틱 AI × 데이터」

---

## 한눈에 보기

```
소셜 신호 ─▶ 주제 ─▶ 정책 전부 모으기 ─▶ 세 관문 ─▶ 계획 먼저 ─▶ 효과 추정·판정
(뉴스·SNS)   (신호는 여기까지만)  (법제처 조례·고시)   (언제·누가·무엇을)  (plan.yaml 커밋)   (식별됨·조건부·식별 불가)
```

| 원칙 | 왜 |
|---|---|
| 소셜 신호는 **주제까지만** 정한다 | 화제가 된 정책 하나만 고르면 결과를 보고 사례를 고르는 셈이 된다 |
| 계획을 **먼저 커밋**해야 추정이 실행된다 | 결과를 본 뒤 설계를 바꾸는 것을 막는다 |
| 방법은 **규칙이** 고르고, 수치는 **라이브러리가** 계산한다 | LLM은 주제 매칭과 서술만 돕는다 |
| 처치 지역이 적으면 **무작위화 추론** | 기존 표준오차는 처치 4/25곳에서 크게 과신한다 |
| 한계는 **배지로 공개** | 시뮬레이션·키 대기·확인 필요 상태를 숨기지 않는다 |

## 5분 만에 돌려 보기

```bash
git clone https://github.com/CausalInferenceLab/policy-effect-analytics-agent.git
cd policy-effect-analytics-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

make flow CASE=cases/t3-land-permit-2025   # 토허구역 예시를 6단계로 실행
python site/build.py && python -m http.server -d _site   # 대시보드를 http://localhost:8000 에서
```

API 키 없이 돌아갑니다. 키가 필요한 데이터는 `.env.example`을 복사해 채우세요(`.env`는 커밋되지 않습니다).

## 무엇이 들어 있나

| 폴더 | 하는 일 | 조원 역할 |
|---|---|---|
| [`catalog/`](catalog/) | 주제 6개 · 정책 8개 · 추천 데이터셋 | 문제 정의 |
| [`core/discovery/`](core/discovery/) | 소셜 신호 → 주제 → 정책 목록 | 문제 정의 |
| [`core/adapters/`](core/adapters/) | 국토부 실거래가 · KOSIS · 법제처 · 파일 수집 | 데이터 수집 |
| [`core/estimators/`](core/estimators/) | DiD · 이벤트 스터디 · ITS · 무작위화 추론 · 판정 | 추정 |
| [`core/agent/`](core/agent/) | 6단계 Flow, 사전 등록 게이트, 과잉해석 가드 | 리포트·에이전트 |
| [`cases/`](cases/) | 조별 분석 케이스 (`_template`에서 시작) | 조 전체 |
| [`site/`](site/) | 공개 대시보드 (GitHub Pages) | 리포트·에이전트 |
| [`app/`](app/) | Streamlit 개발용 화면 | — |
| [`docs/`](docs/) | 전략(국내 사례·주제 가이드·계획 작성법), 운영 가이드 | — |

## 조별로 참여하기

1. **주제 고르기**: [대시보드](https://causalinferencelab.github.io/policy-effect-analytics-agent/#topics)에서 주제를 고르거나 `catalog/topics.yaml`에 제안합니다.
2. **계획 PR**: `cp -r cases/_template cases/group1-<주제>` → `plan.yaml` 작성 → PR로 사전 등록합니다. 작성법은 [plan-guide](docs/strategy/plan-guide.md)를 보세요.
3. **실행·공개**: `make flow CASE=cases/group1-<주제>`를 돌리고 결과를 PR로 올리면, `main`에 반영될 때 대시보드에 자동으로 올라갑니다.

브랜치는 `group<N>/<설명>`, 수정은 자기 조 폴더만, 병합은 리뷰 1명 + CI 통과 후입니다. 자세한 규칙은 [CONTRIBUTING](CONTRIBUTING.md)에 있습니다.

## 지금 상태

- **구현됨**: 주제 매칭 · 6단계 Flow · 사전 등록 게이트 · DiD/이벤트 스터디/ITS · 무작위화 추론 · 과장 표현 가드 · 대시보드 자동 배포(매주 월요일 갱신)
- **키 대기**: 국토부 실거래가(토허구역 예시는 지금 **시뮬레이션 데이터**) · 법제처 조례 자동 수집
- **다음 단계**: 시차 도입 추정(Callaway–Sant'Anna) · 합성통제 · 검색량으로 선반영 점검

## 라이선스

코드는 [MIT](LICENSE)입니다. 데이터는 각 출처의 이용 조건(공공누리 유형 등)을 따르며, 케이스마다 `plan.yaml`의 `data_sources`에 적습니다.

---

**English.** An open-source platform that starts from public conversation, picks a *topic* (never a single trending policy, to avoid selecting cases on outcomes), collects every policy in that topic from Korean public sources, checks three gates (when / who / what), requires a committed pre-analysis plan, and estimates effects with rule-selected designs (DiD, event study, ITS; randomization inference when few units are treated). Results are published as a static dashboard on GitHub Pages.
