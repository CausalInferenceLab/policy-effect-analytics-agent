# 케이스 템플릿

```bash
git switch -c <내ID>/plan
cp -r cases/_template cases/<내ID>-<주제>   # 예: cases/gildong-local-currency (소문자-하이픈)
```

복사한 뒤 이 README는 내 분석 메모로 바꿔도 됩니다.

## 4단계

| 단계 | 파일 | 할 일 | 완료 기준 |
|---|---|---|---|
| 1. 질문 정의 | `plan.yaml` | 질문·처치·대조·시점·지표·추정법·가정·반증·중단조건·데이터 라이선스 | **결과를 보기 전에** PR 병합 |
| 2. 수집 | `fetch.py` | 공공데이터 API/파일 → `data/raw/` → 정제 패널 `data/processed/panel.csv` | 키만 있으면 누구나 재실행 가능 |
| 3. 추정 | `estimate.py` | `core.estimators`로 효과 추정 + `refutations` 실행 → `figures/*.png` | 그림·수치 재현 가능, `abstention` 판정 |
| 4. 리포트 | `report.md` | 결과·한계·시사점 | `make app`에서 카드로 보임 |

```bash
python cases/<내ID>-<주제>/fetch.py
python cases/<내ID>-<주제>/estimate.py
make app
```

## 규칙

- `data/raw/`는 git에 올라가지 않습니다 (`.gitignore`). 재배포 가능한 **작은 정제 데이터만** `data/processed/`에 커밋하세요 (라이선스 확인, 수 MB 이하).
- API 키는 `.env`에만. 코드에 직접 쓰지 마세요.
- `plan.yaml`을 결과 확인 후 바꿨다면 커밋 메시지와 `report.md`에 이유를 남기세요.
