# 정책 효과 분석 플랫폼

**그 정책, 정말 효과가 있었을까?**

뉴스와 SNS에서 사람들이 묻는 정책을 공공데이터로 확인하는 오픈소스입니다.
정책을 받은 곳과 안 받은 곳을 비교하고, 데이터로 판단할 수 없으면 판단할 수 없다고 말합니다.

**[사이트 열기](https://causalinferencelab.github.io/policy-effect-analytics-agent/)** · [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html) · [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html) · [구조](https://causalinferencelab.github.io/policy-effect-analytics-agent/architecture.html) · [멘티 참여 가이드](docs/ops/mentee-guide.md)

> 가짜연구소 인과추론팀 × 오픈업 오픈소스 AI 특화형 트랙3 「에이전틱 AI × 데이터」 (2026.9 ~ 11)
>
> **공식 평가가 아닙니다.** 학습·연구용 오픈소스 분석이며, 정부·공공기관의 공식 평가나 통계가 아니고 데이터 제공 기관의 후원·보증을 뜻하지 않습니다.

---

## 사이트에서 할 수 있는 것

| 화면 | 하는 일 |
|---|---|
| **대화창** | "궁금한 정책 이야기를 적어 보세요"에 적으면 주제를 찾고, 받을 수 있는 데이터·조심할 점·분석 계획 초안을 대화로 정리합니다. 키 없이 쓰는 **가이드 모드**가 기본이고, 내 AI 키(Claude 또는 Ollama 같은 OpenAI 호환)를 넣으면 **AI 모드**로 자유롭게 묻습니다. 키는 저장하지 않습니다. |
| **요즘 궁금해하는 주제** | 대화창 아래 순위입니다. 최근 30일 사이트 질문 수 → 네이버 검색 관심도(키가 있을 때) → 최근 시행·발표일 순이고, 어떤 기준을 썼는지 화면에 적습니다. |
| **지금 이슈** | 토지거래허가구역, 6·27 대출 한도, 민생회복 소비쿠폰, 고유가 피해지원금, K-패스 '모두의 카드' 등 6개 정책의 분석 가이드입니다. |
| **데이터 지도** | 공공데이터 35개를 역할(누가 언제 받았나 / 무엇이 변했나 / 다른 요인), 단위, 받는 법, 이용 조건으로 정리했습니다. |
| **주제 8개** | 주제마다 정책 타임라인, 세 가지 확인 상태, **관련 법령·행정규칙**(법제처 자동 수집), 데이터, 분석 예시가 있습니다. |

## 데이터는 어디서 오나

| 무엇 | 어디서 | 어떻게 |
|---|---|---|
| **정책이 언제, 누구에게** (법령·행정규칙·조례) | 법제처 국가법령정보 공동활용 API | 주제마다 근거 법률만 적으면 연혁·하위 규정·조례·지정/해제 공고를 모두 모읍니다. 매주 바뀐 것은 `law-change` 이슈로 알립니다. [자세히](catalog/README.md#법령정책-온톨로지-법제처-자동-수집) |
| **정책 발표** (지자체 공고, 대출 규제 같은 행정지도) | 정부 보도자료(korea.kr) 등 | 법령 DB에 없어 `topics.yaml`의 `events`에 출처와 함께 사람이 적습니다 |
| **무엇이 달라졌나** (결과) · **다른 요인** (통제) | 공공데이터포털, KOSIS, 서울 열린데이터광장 등 35개 | [데이터 지도](catalog/datasets.yaml)에 역할·단위·받는 법·이용 조건을 적고, 각 케이스의 `fetch.py`가 받습니다 |
| **사람들이 궁금해하는 것** | 사이트 질문(GitHub 이슈), 네이버 검색어트렌드(선택) | 주제를 고르는 데만 씁니다 |

## 대화가 오픈소스가 되는 길

```
 질문 ──▶ 정리 ──▶ 제안 ──▶ 반영
 대화창    주제·데이터·    "제안으로 올리기" →   멘토·멘티가 검토해 catalog/(새 주제·데이터),
          계획 초안       GitHub 이슈(from-site)  cases/(분석)에 PR → 사이트·순위 갱신
```

대화는 브라우저 안에서만 쓰이고, **사용자가 버튼을 누를 때만** GitHub 이슈 작성 화면으로 넘어갑니다. 올라온 질문 목록: [label:from-site](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=label%3Afrom-site)

## 어떻게 확인하나 (6단계)

| 단계 | 하는 일 |
|---|---|
| 1. 찾기 | 사람들이 궁금해하는 **주제**를 고릅니다 |
| 2. 모으기 | 그 주제의 정책을 **전부** 모읍니다. 어느 지역이 언제 시작했는지 |
| 3. 거르기 | 세 가지를 확인합니다. 언제 시작했나 · 누가 받았나 · 무엇으로 재나 |
| 4. 계획하기 | 데이터를 보기 전에 분석 계획(`plan.yaml`)을 먼저 커밋합니다 |
| 5. 비교하기 | 정책을 받은 곳과 안 받은 곳의 변화를 비교합니다 |
| 6. 말하기 | **효과 근거 있음 · 조건부 · 판단 불가** 중 하나로 씁니다 |

**왜 정책 하나가 아니라 주제로 보나?** 화제가 된 정책만 골라 분석하면 결과를 보고 사례를 고르는 것과 같아져 효과가 부풀려집니다. 그래서 화제(와 순위)는 "어느 주제를 볼지"까지만 정하고, 그 주제의 정책을 모두 모아 비교합니다.

## 5분 만에 돌려 보기

```bash
git clone https://github.com/CausalInferenceLab/policy-effect-analytics-agent.git
cd policy-effect-analytics-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                               # Python 3.11 이상

make demo      # 토지거래허가구역 예시를 연습용 폴더(_demo/)에서 6단계로 실행. 레포 파일은 바뀌지 않음
make site      # 사이트를 http://localhost:8000 에서 보기
```

API 키 없이 돌아갑니다. 실제 데이터를 받으려면 `.env.example`을 `.env`로 복사해 키를 넣으세요. `.env`는 커밋되지 않습니다.

> 토지거래허가구역 예시는 지금 **시뮬레이션 데이터**입니다. 분석 과정을 보여주기 위한 것이고, 실제 정책 효과가 아닙니다.

## 참여하기 (멘티 한 사람 = 주제 하나)

1. **주제 고르기**: 사이트 대화창·순위·지금 이슈에서 고르고 "케이스 제안" 이슈를 엽니다.
2. **계획 올리기**: `cp -r cases/_template cases/<내ID>-<주제>`로 내 폴더를 만들고 `plan.yaml`을 써서 PR을 올립니다. 대화창의 "분석 계획 초안"을 출발점으로 써도 됩니다. 쓰는 법: [계획 작성 가이드](docs/strategy/plan-guide.md)
3. **실행하고 공개**: `fetch.py`로 `data/panel.csv`를 만들고 `make flow CASE=cases/<내ID>-<주제>`로 돌립니다. 해석은 `discussion.md`에 씁니다. 합쳐지면 사이트에 자동으로 올라옵니다.

`make flow`는 plan.yaml이 커밋되어 있지 않으면 계산하지 않습니다(사전 등록). 사이트 질문과 법령 변경 이슈는 담당자 없이 구성원 모두가 봅니다.

규칙은 세 가지입니다. 브랜치는 `<내ID>/<작업>`, 수정은 내 폴더만, 합치기는 리뷰 1명과 자동 검사 통과 뒤. 자세한 내용: [멘티 참여 가이드](docs/ops/mentee-guide.md) · [CONTRIBUTING](CONTRIBUTING.md) · [GitHub가 처음이라면](docs/ops/github-onboarding.md)

## 폴더 안내

| 폴더 | 하는 일 | 누가 고치나 |
|---|---|---|
| [`cases/`](cases/) | 멘티별 분석 폴더 (`<내ID>-<주제>`, `_template`에서 시작) | 폴더 주인 |
| [`catalog/`](catalog/) | 주제 · 이슈 · 데이터셋 목록 (데이터 지도) | 누구나 (PR) |
| [`site/`](site/) | 공개 사이트와 대화창(`ask.js`) | 메인테이너 |
| [`scripts/`](scripts/) | 법령 · 조례 · 순위 갱신, 법령 변경 감지, 라이선스 · 활동 확인 | 메인테이너 |
| [`core/`](core/) | 주제 찾기(`discovery`) · 수집기(`adapters`, 법령 온톨로지 포함) · 계산(`estimators`) · 6단계 실행(`agent`) | 메인테이너 |
| `app/` | (선택) 개발용 Streamlit 화면. `pip install -e ".[app]"` 후 `make app` | 메인테이너 |
| [`docs/`](docs/) | 국내 사례, 주제 고르기, 계획 작성법, 운영 가이드 | 운영진 |

## 지금 상태와 필요한 것

- **완성**: 대화창(가이드 · 내 AI 키) · 대화 → 이슈 · 주제 순위 · 데이터 지도 · 법령 온톨로지(7개 주제 3,500여 건, 매주 변경 알림) · 6단계 실행 · 계획 커밋 확인 · 이중차분/단절 시계열 · 정책 지역이 적을 때의 무작위화 추론 · 과장 표현 차단 · 사이트 자동 공개(매일)
- **키 대기**: 국토부 실거래가(실제 데이터 전환) · 법제처 매일 갱신(`LAW_OC`) · 순위의 검색 관심도(`NAVER_CLIENT_ID/SECRET`, 선택). 모두 레포 Settings → Secrets에만 넣습니다.
- **결정 필요**: 키 없는 사람의 AI 대화 (권장: 구성원은 이슈에서 `@claude`로 답 받기, 공개 방문자용 중계 서버는 필요할 때만)
- **다음**: 시차 도입 이중차분(4주차) · 합성통제(5주차) · 공공데이터포털 검색을 공식 API로 전환 · 검색량으로 "미리 반응했나" 점검

## 관련 프로젝트

겹치거나 부딪히는 부분이 있는지 확인했습니다. 라이선스 충돌은 없고, 서로 보완하는 관계입니다.

| 프로젝트 | 무엇을 | 우리와의 관계 |
|---|---|---|
| [CAIS (causal-agent)](https://github.com/causalNLP/causal-agent), [Causal-Copilot](https://github.com/Lancelot39/Causal-Copilot) | LLM 인과 분석 에이전트 (MIT) | 범용 도구. 우리는 한국 공공데이터 · 정책 시작일 · 사전 등록에 집중 |
| [korean-law-mcp](https://github.com/chrisryugj/korean-law-mcp) | 법제처 API를 AI 도구(MCP)로 묶은 서버 (MIT) | 법령 조회가 겹침. Claude로 법령을 탐색할 때 함께 쓰면 좋음. 우리는 재현용 스냅샷·변경 감지·효과 추정 연결에 집중 |
| [PublicDataReader](https://github.com/WooilJeong/PublicDataReader), [kpubdata](https://github.com/yeongseon/kpubdata), [data-go-mcp-servers](https://github.com/Koomook/data-go-mcp-servers) | 공공데이터 수집 라이브러리 · MCP 서버 (MIT · Apache-2.0) | 수집 층을 보완. 필요하면 가져다 씀 |
| [PolicyEngine](https://github.com/PolicyEngine/policyengine-core), [OpenFisca](https://github.com/openfisca/openfisca-core) | 세금·복지 제도 사전 시뮬레이션 (AGPL-3.0) | 목적이 다름. AGPL이라 코드를 가져오지 않음 |
| 국회예산정책처 · 기획재정부 재정사업 평가 | 공식 평가 | 우리 결과는 공식 평가가 아니며 그렇게 보이지 않게 표시 |

## 라이선스와 데이터

코드는 [MIT](LICENSE)입니다. GPL·AGPL 패키지는 필수 의존성으로 넣지 않고 CI가 확인합니다(`scripts/check_licenses.py`).
데이터는 출처마다 이용 조건이 다르며 데이터 지도와 각 케이스의 `plan.yaml`에 적습니다. 원자료와 가공 데이터 파일은 레포에 올리지 않고 `fetch.py`로 각자 받습니다.
법령 목록(`catalog/snapshots/legal_*.csv`)은 이름·날짜 같은 메타데이터만 담으며, 출처는 법제처 국가법령정보센터입니다. 법률 자문이 아닙니다.

---

**English.** An open-source platform that checks whether Korean public policies people talk about actually worked. A chat box on the site (rule-based by default, or your own AI key in the browser) turns a question into a topic, candidate datasets, pitfalls and a draft pre-analysis plan; with one click the conversation becomes a GitHub issue that maintainers fold into the catalog and cases, and site questions drive the "topics people are curious about" ranking. Public conversation only picks the *topic*; every policy in that topic is collected and checked on three gates (when / who / what). A pre-analysis plan must be committed before estimation, designs are chosen by rules rather than by an LLM, and results are published as a static site. Not an official government evaluation.
