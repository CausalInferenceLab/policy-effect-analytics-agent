# 기여 가이드 (CONTRIBUTING)

GitHub 협업이 처음이라면 먼저 [`docs/ops/github-onboarding.md`](docs/ops/github-onboarding.md)를 따라 하세요.

## 1. 작업 방식: 조별 브랜치 (권장)

| 방식 | 언제 | 비고 |
|---|---|---|
| **조직 저장소에서 브랜치** (권장) | 조직 초대를 수락한 멘티 | CI·리뷰·모니터링이 한 곳에서 보임 |
| Fork → PR | 초대 전이거나 외부 기여자 | PR 대상은 `main` |

- `main`은 보호 브랜치입니다. **직접 push 금지, PR로만 병합.**
- 브랜치 이름: `<조>/<작업>` — 예) `group3/plan`, `group3/fetch-kosis`, `group1/fix-report`
- 공통 코드(`core/`)는 `core/<작업>` 브랜치로, 먼저 이슈에서 논의한 뒤 수정합니다.

## 2. 폴더 소유권

| 경로 | 소유 | 규칙 |
|---|---|---|
| `cases/<조>-<주제>/` | 해당 조 | 조 안에서 자유롭게. 다른 조 폴더는 수정하지 않음 |
| `core/` | 멘토·코어 메인테이너 | 이슈 → 합의 → PR. 테스트 필수 |
| `cases/_template/`, `app/`, `.github/`, `docs/` | 운영진 | 개선 제안은 이슈로 |

소유자는 [`.github/CODEOWNERS`](.github/CODEOWNERS)로 자동 리뷰 요청됩니다.

## 3. 커밋 규칙 (Conventional Commits)

```
<type>(<scope>): <요약, 50자 이내>
```

- type: `feat` 기능 · `fix` 버그 · `data` 수집/전처리 · `analysis` 추정/그림 · `docs` 문서 · `plan` plan.yaml · `test` · `chore`
- scope: 조 폴더명 또는 `core`, `app`
- 예) `plan(group3-youth-rent): 처치·대조 지역 정의`, `analysis(group3-youth-rent): DiD 1차 추정`
- 작은 단위로 자주 커밋하세요. 주 1회 이상 커밋이 활동 확인 기준입니다.

## 4. PR 흐름

1. 최신 `main`에서 브랜치 생성 → 작업 → `make check` 통과 확인
2. PR 생성 (템플릿 체크리스트 작성). 작업 중이면 **Draft PR**로 일찍 올리세요.
3. 리뷰: **승인 1명 + CI 통과** 시 병합 (조원 상호 리뷰 가능, `core/`는 코어 메인테이너 승인)
4. 병합 방식: **Squash merge** (PR 제목이 커밋 메시지가 되므로 규칙에 맞게)
5. 병합 후 브랜치 삭제, 로컬 `git switch main && git pull`

## 5. 분석 원칙 (리뷰에서 확인)

- **plan.yaml을 결과보다 먼저 커밋** (사전 등록). 이후 변경은 커밋 메시지에 이유를 적습니다.
- 데이터 출처·라이선스 명시 (공공누리 유형 등). 재배포 불가 원자료, 개인정보, API 키는 커밋 금지.
- 그림·수치는 `estimate.py` 실행으로 재현 가능해야 합니다.
- 가정이 깨지면 `abstention` 규칙에 따라 **결론을 보류**하는 것도 좋은 결과입니다.

## 6. 개발 환경

```bash
make install   # 의존성 설치 (dev 포함)
make check     # ruff + pytest — CI와 동일
make app       # Streamlit 로컬 실행
```

선택: `pre-commit install` 로 커밋 시 ruff 자동 실행.

## 7. 질문·제안

- 버그: 이슈 → `버그 리포트`
- 새 케이스 주제: 이슈 → `케이스 제안`
- 행동 강령: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
