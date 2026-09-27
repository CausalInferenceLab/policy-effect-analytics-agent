# 정책 효과 분석 플랫폼

**그 정책, 정말 효과가 있었을까?**

뉴스와 SNS에서 사람들이 묻는 정책을 공공데이터로 확인하는 오픈소스입니다.
정책을 받은 곳과 안 받은 곳을 비교하고, 데이터로 판단할 수 없으면 판단할 수 없다고 말합니다.

**[사이트 열기](https://causalinferencelab.github.io/policy-effect-analytics-agent/)** · [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html) · [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html) · [구조](https://causalinferencelab.github.io/policy-effect-analytics-agent/architecture.html) · [조별 운영 가이드](docs/ops/group-guide.md)

> 가짜연구소 인과추론팀 × 오픈업 오픈소스 AI 특화형 트랙3 「에이전틱 AI × 데이터」 (2026.9 ~ 11)

---

## 무엇을 하나

| 단계 | 하는 일 |
|---|---|
| 1. 찾기 | 뉴스·SNS에서 사람들이 궁금해하는 **주제**를 찾습니다 |
| 2. 모으기 | 그 주제의 정책을 **전부** 모읍니다. 어느 지역이 언제 시작했는지 |
| 3. 거르기 | 세 가지를 확인합니다. 언제 시작했나 · 누가 받았나 · 무엇으로 재나 |
| 4. 계획하기 | 데이터를 보기 전에 분석 계획(`plan.yaml`)을 먼저 커밋합니다 |
| 5. 비교하기 | 정책을 받은 곳과 안 받은 곳의 변화를 비교합니다 |
| 6. 말하기 | **효과 근거 있음 · 조건부 · 판단 불가** 중 하나로 씁니다 |

**왜 정책 하나가 아니라 주제로 보나?** 화제가 된 정책만 골라 분석하면, 결과를 보고 사례를 고르는 것과 같아져 효과가 부풀려집니다. 그래서 화제는 "어느 주제를 볼지"까지만 정하고, 그 주제의 정책을 모두 모아 비교합니다.

## 사이트에서 볼 수 있는 것

- **지금 이슈**: 10·15 토지거래허가구역, 6·27 대출 한도, 민생회복 소비쿠폰, 고유가 피해지원금, K-패스 '모두의 카드' 등 6개 정책의 분석 가이드입니다. 누구와 비교할지, 어떤 방법을 쓸지, 어떤 데이터를 받을 수 있는지 정리했습니다.
- **데이터 지도**: 공공데이터 35개를 역할(누가 언제 받았나 / 무엇이 변했나 / 다른 요인), 단위, 받는 법으로 정리했습니다. 검색과 필터를 쓸 수 있습니다.
- **주제 8개**: 주제마다 정책 타임라인, 세 가지 확인 상태, 받을 수 있는 데이터, 분석 예시를 보여줍니다.

## 5분 만에 돌려 보기

```bash
git clone https://github.com/CausalInferenceLab/policy-effect-analytics-agent.git
cd policy-effect-analytics-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

make flow CASE=cases/t3-land-permit-2025            # 토지거래허가구역 예시를 6단계로 실행
python site/build.py && python -m http.server -d _site   # 사이트를 http://localhost:8000 에서 보기
```

API 키 없이 돌아갑니다. 실제 데이터를 받으려면 `.env.example`을 `.env`로 복사해 키를 넣으세요. `.env`는 커밋되지 않습니다.

> 토지거래허가구역 예시는 지금 **시뮬레이션 데이터**입니다. 분석 과정을 보여주기 위한 것이고, 실제 정책 효과가 아닙니다.

## 폴더 안내

| 폴더 | 하는 일 | 맡는 역할 |
|---|---|---|
| [`catalog/`](catalog/) | 주제 · 이슈 · 데이터셋 목록 (데이터 지도) | 문제 정의 |
| [`core/discovery/`](core/discovery/) | 소셜 반응 → 주제 → 정책 · 데이터 | 문제 정의 |
| [`core/adapters/`](core/adapters/) | 공공데이터 · 법제처 수집기 | 데이터 수집 |
| [`core/estimators/`](core/estimators/) | 효과 계산 · 점검 · 판정 | 추정 |
| [`core/agent/`](core/agent/) | 6단계 실행, 계획 커밋 확인, 과장 표현 차단 | 리포트 · 에이전트 |
| [`cases/`](cases/) | 조별 분석 폴더 (`_template`에서 시작) | 조 전체 |
| [`site/`](site/) | 공개 사이트 (GitHub Pages) | 리포트 · 에이전트 |
| [`docs/`](docs/) | 국내 사례, 주제 고르기, 계획 작성법, 운영 가이드 | — |

## 조별로 참여하기

1. **주제 고르기**: 사이트의 [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html)나 주제 목록에서 고릅니다.
2. **계획 올리기**: `cp -r cases/_template cases/group1-<주제>`로 폴더를 만들고 `plan.yaml`을 써서 PR을 올립니다. 쓰는 법은 [계획 작성 가이드](docs/strategy/plan-guide.md)에 있습니다.
3. **실행하고 공개**: `make flow CASE=cases/group1-<주제>`로 돌리고 결과를 PR로 올립니다. 합쳐지면 사이트에 자동으로 올라옵니다.

규칙은 세 가지입니다. 브랜치는 `group<번호>/<설명>`, 수정은 자기 조 폴더만, 합치기는 리뷰 1명과 자동 검사 통과 뒤입니다. 자세한 내용은 [CONTRIBUTING](CONTRIBUTING.md)과 [GitHub가 처음이라면](docs/ops/github-onboarding.md)을 보세요.

## 지금 상태

- **완성**: 주제 찾기 · 데이터 지도 · 6단계 실행 · 계획 커밋 확인 · 이중차분/단절 시계열 · 정책 지역이 적을 때의 무작위화 추론 · 과장 표현 차단 · 사이트 자동 공개(매주 월요일 갱신)
- **데이터 키 대기**: 국토부 실거래가(실제 데이터 전환) · 법제처 조례 자동 수집
- **다음**: 시차 도입 이중차분(4주차) · 합성통제(5주차) · 검색량으로 "미리 반응했나" 점검

## 라이선스

코드는 [MIT](LICENSE)입니다. 데이터는 출처마다 이용 조건이 다르며, 데이터 지도와 각 케이스의 `plan.yaml`에 적어 둡니다.

---

**English.** An open-source platform that checks whether Korean public policies people talk about actually worked. Public conversation only picks the *topic* (never a single trending policy, which would mean choosing cases by their outcomes); every policy in that topic is collected and checked on three gates (when / who / what). A pre-analysis plan must be committed before estimation, designs are chosen by rules rather than by an LLM, and results are published as a static site with a searchable data map and an analysis guide for currently debated policies.
