# GitHub 온보딩 (처음 쓰는 분용)

명령어는 그대로 복사해서 실행하세요. `gildong`은 자기 GitHub ID로, `local-currency`는 자기 주제로 바꾸면 됩니다.

## 0. 준비 (1회)

1. GitHub 계정 생성, 프로필에 실명 또는 닉네임 설정
2. Git 설치 확인: `git --version` (없으면 https://git-scm.com)
3. GitHub CLI 설치 (권장): https://cli.github.com → `gh auth login` (GitHub.com → HTTPS → 브라우저 로그인)
4. 커밋 작성자 설정:
   ```bash
   git config --global user.name "홍길동"
   git config --global user.email "GitHub에 등록한 이메일"
   ```

## 1. 초대 수락

- 이메일 또는 https://github.com/orgs/CausalInferenceLab/invitation 에서 **Join** 클릭
- 확인: https://github.com/CausalInferenceLab/policy-effect-analytics-agent 에 `Code` 버튼과 브랜치 생성 권한이 보이면 성공
- 초대 메일이 없으면 GitHub ID를 운영진에게 알려주세요.

## 2. 내려받기 (clone) 와 환경 설치

```bash
gh repo clone CausalInferenceLab/policy-effect-analytics-agent
cd policy-effect-analytics-agent
python -m venv .venv && source .venv/bin/activate   # Python 3.11 이상. Windows: .venv\Scripts\activate
pip install -e ".[dev]"                               # uv를 쓴다면: uv venv -p 3.11 && uv pip install -e ".[dev]"
cp .env.example .env                             # API 키 입력 (커밋되지 않음)
make check                                       # 통과하면 준비 끝
```

## 3. 브랜치 만들기

`main`에서 직접 작업하지 않습니다. 항상 최신 `main`에서 새 브랜치를 만드세요.

```bash
git switch main
git pull
git switch -c gildong/plan
```

## 4. 작업하고 커밋하기

```bash
cp -r cases/_template cases/gildong-local-currency    # 첫 작업일 때만
# ... plan.yaml 수정 ...
git status                                       # 무엇이 바뀌었는지 확인
git add cases/gildong-local-currency
git commit -m "plan(gildong-local-currency): 질문과 처치·대조 정의"
git push -u origin gildong/plan                   # 두 번째부터는 git push
```

- `git add .` 대신 **자기 폴더만** add 하는 습관을 들이세요 (`.env`, 원자료 실수 방지).

## 5. PR 올리기

```bash
gh pr create --fill --base main          # 또는 GitHub 웹에서 "Compare & pull request"
gh pr create --draft --fill              # 아직 작업 중이면 Draft
```

1. PR 본문 체크리스트를 채웁니다.
2. CI(초록 체크)를 기다립니다. 빨간 X면 `Details`를 눌러 로그를 확인하고, 고쳐서 다시 push 하면 PR이 자동 갱신됩니다.
3. 멘토 또는 다른 멘티 1명 **Approve** 후 **Squash and merge**.

## 6. 병합 후 정리

```bash
git switch main
git pull
git branch -d gildong/plan
```

## 자주 막히는 곳

| 증상 | 해결 |
|---|---|
| `Permission denied` / 403 on push | 초대 수락 확인, `gh auth login` 다시 |
| `rejected ... fetch first` | `git pull --rebase` 후 다시 push |
| 충돌(conflict) | 충돌 파일에서 `<<<<<<<` 구간 정리 → `git add 파일` → `git rebase --continue` |
| `.env`를 실수로 커밋 | push 전이면 `git reset HEAD~1`. **push 했다면 즉시 키를 재발급**하고 운영진에게 알림 |
| main에 커밋해버림 | `git switch -c gildong/fix` 로 브랜치를 만든 뒤 push (main은 보호되어 push 안 됨) |
| CI의 ruff 에러 | 로컬에서 `make format` 후 다시 커밋 |
