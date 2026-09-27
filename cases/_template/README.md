# 케이스 템플릿

```bash
git switch -c <내ID>/plan
cp -r cases/_template cases/<내ID>-<주제>     # 예: cases/gildong-local-currency (소문자-하이픈)
```

복사한 뒤 이 README는 내 분석 메모로 바꿔도 됩니다.

## 이 폴더의 파일

| 파일 | 누가 | 할 일 |
|---|---|---|
| `plan.yaml` | 나 | 질문·처치·대조·시점·지표·방법·중단 조건. **데이터를 보기 전에 커밋**합니다 |
| `fetch.py` | 나 | 공공데이터를 받아 `data/panel.csv`를 만듭니다 |
| `discussion.md` | 나 | 해석과 한계. `report.md` 끝에 붙습니다 |
| `report.md`, `figures/`, `flow_log.json`, `run_manifest.json` | 자동 | `make flow`가 만듭니다. 직접 고치지 않습니다 |

## 순서

```bash
# 1) plan.yaml 을 쓰고 먼저 커밋·PR (case_id 는 폴더 이름과 같게)
git add cases/<내ID>-<주제>/plan.yaml && git commit -m "plan(<내ID>-<주제>): 분석 계획"

# 2) fetch.py 를 채우고 실행 → 3) 여섯 단계를 한 번에
make flow CASE=cases/<내ID>-<주제>

# 4) discussion.md 를 쓰고 다시 make flow → report.md 에 합쳐짐
```

`make flow`는 plan.yaml 이 커밋되어 있지 않으면 계산하지 않습니다(사전 등록). 연습만 하려면 `make demo`를 쓰세요.

## 규칙

- `data/` 아래 파일은 git에 올라가지 않습니다. 원자료·가공 데이터는 다시 배포하지 않고 `fetch.py`로 각자 받습니다.
- API 키는 `.env`에만 넣습니다. 코드에 직접 쓰지 않습니다.
- plan.yaml 을 결과 확인 뒤 바꿨다면 커밋 메시지와 `discussion.md`에 이유를 남깁니다.
