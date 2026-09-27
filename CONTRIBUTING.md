# 기여 가이드

GitHub가 처음이라면 [GitHub 따라 하기](docs/ops/github-onboarding.md)부터 보세요. 전체 흐름은 [멘티 참여 가이드](docs/ops/mentee-guide.md)에 있습니다.

## 1. 한 사람, 한 폴더, 한 브랜치

- 분석은 한 사람이 주제 하나를 맡아 `cases/<내 GitHub ID>-<주제>/` 폴더에서 합니다. 예: `cases/gildong-local-currency/`
- 브랜치 이름은 `<내 GitHub ID>/<작업>`입니다. 예: `gildong/plan`, `gildong/fetch`
- `main`에는 직접 올릴 수 없습니다. 모든 변경은 PR로 합칩니다.
- 조직 초대를 받기 전이거나 외부 기여자라면 fork 후 PR을 올려도 됩니다.

## 2. 어디를 고치나

| 경로 | 누가 | 규칙 |
|---|---|---|
| `cases/<내ID>-<주제>/` | 폴더 주인 | 자유롭게. 남의 폴더는 고치지 않습니다 |
| `catalog/` | 누구나 | 새 데이터셋·이슈·주제 제안. 원본 페이지에서 확인한 값만 적습니다 |
| `core/`, `site/` | 멘토·메인테이너 | 먼저 이슈로 논의한 뒤 PR. 테스트 필수 |
| `.github/`, `docs/` | 운영진 | 개선 제안은 이슈로 |

## 3. 커밋 메시지

```
<종류>(<범위>): <요약, 50자 이내>
```

- 종류: `plan` 분석 계획 · `data` 수집 · `analysis` 추정·그림 · `docs` 문서 · `feat` 기능 · `fix` 버그 · `test` · `chore`
- 범위: 내 케이스 폴더 이름, 또는 `core`, `catalog`, `site`
- 예: `plan(gildong-local-currency): 처치·대조 지역 정의`

## 4. PR 흐름

1. 최신 `main`에서 브랜치를 만들고 작업한 뒤 `make check`로 검사합니다.
2. PR을 올리고 템플릿 체크리스트를 채웁니다. 작업 중이면 Draft PR로 일찍 올리세요.
3. 멘토 또는 다른 멘티 1명 승인 + 자동 검사 통과 뒤 **Squash merge**로 합칩니다.
4. 합친 뒤에는 브랜치를 지우고 `git switch main && git pull`.

## 5. 분석 원칙 (리뷰에서 확인합니다)

- **`plan.yaml`을 결과보다 먼저 커밋합니다.** 나중에 바꾸면 커밋 메시지에 이유를 적습니다.
- 데이터 출처와 이용 조건(공공누리 유형 등)을 `plan.yaml`의 `data_sources`에 적습니다.
- 그림과 숫자는 `fetch.py` → `make flow` 실행으로 다시 만들 수 있어야 합니다. `make flow`는 plan.yaml이 커밋되어 있지 않으면 계산하지 않습니다(연습은 `make demo`).
- `report.md`·`figures/`는 자동으로 만들어집니다. 해석과 한계는 `discussion.md`에 쓰면 리포트 끝에 붙습니다.
- 가정이 깨지면 판정을 "판단 불가"로 두는 것도 좋은 결과입니다.

## 6. 올리면 안 되는 것

- API 키·인증값(`.env`, 법제처 OC 등). 레포 비밀값(Settings → Secrets)으로만 관리합니다.
- **원자료와 가공한 데이터 파일.** 데이터는 `fetch.py`로 각자 받게 합니다. 특히 공공누리 3·4유형(변경금지, 예: 에어코리아)과 KOSIS 자료의 가공본은 다시 배포하지 않습니다. 예외는 시뮬레이션 데이터와 법제처 조례 목록(조례는 저작권 보호 대상이 아님)입니다.
- 개인정보가 담긴 자료.
- GPL·AGPL 라이선스 패키지를 필수 의존성으로 추가하지 않습니다(예: `rdrobust`, `differences`, PolicyEngine, OpenFisca). 필요하면 선택 설치로 분리합니다. CI가 확인합니다.

## 7. 공식 결과가 아닙니다

이 프로젝트의 분석은 학습·연구용 오픈소스 결과물이며 정부·공공기관의 공식 평가나 통계가 아닙니다. 리포트와 PR 설명에 "정부 발표", "공식 결과"처럼 오해할 표현을 쓰지 않습니다.

## 8. 개발 환경

```bash
make install   # 의존성 설치
make check     # 코드 검사 + 테스트 (CI와 같음)
make flow CASE=cases/<내ID>-<주제>
python site/build.py && python -m http.server -d _site   # 사이트 미리보기
```

## 9. 질문과 제안 (구성원 모두가 봅니다)

담당자를 따로 두지 않습니다. 모임 전에 각자 아래 두 목록을 훑고, 할 수 있는 것에 댓글을 달거나 PR로 반영합니다.

- [사이트 질문 (`from-site`)](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=is%3Aopen+label%3Afrom-site): 새 주제·데이터면 `catalog/`에 PR, 내 주제와 관련 있으면 내 분석에 반영
- [법령 변경 (`law-change`)](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=is%3Aopen+label%3Alaw-change): 매주 월요일 자동으로 열립니다. 시작일·대상이 바뀐 정책이면 `topics.yaml`의 `events`에 출처와 함께 추가
- 처리한 사람이 이슈를 닫습니다.


- 사이트 대화창에서 정리한 질문은 "이 대화를 제안으로 올리기" 버튼으로 이슈가 됩니다.
- 버그는 "버그 리포트", 새 분석 주제는 "케이스 제안" 이슈로 올립니다.
- 행동 강령: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
