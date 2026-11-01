# 제출본의 실행 검증 범위

2026-11-01 제출 통합에서 실제 실행한 명령·종료 코드·선택 산출물 SHA256은 [verification.json](verification.json)에 기록했다. 작성자의 실행 검증이며 작성자가 제출본을 독립 승인한 기록은 아니다. 이전 2026-10-27 수집 검증은 JSON의 `historical_collection_record`로 보존했다.

- 최신 main `1655a45117574e366bf9ca726d1a896aa0c0f4fb`를 일반 merge해 다른 참여자와 기존 동작을 보존했다. 같은 merge 후 git 이력 메타데이터로 비교한 기존 인과 사례 9개의 HTML 본문·API 객체·효과 CSV 바이트가 최신 main 기준선과 일치했다.
- Python3.11 제출 환경에서 사례 unittest 131개 통과, `make check PY=.venv/bin/python` 종료 0: Ruff 통과 및 pytest 239개 통과·2개 건너뜀. `make readme PY=.venv/bin/python`은 정해진 README 표 구간만 생성했다.
- 세 describe CLI와 오프라인 runner, `python site/build.py`를 실제 실행해 종료 0을 확인했다. 원자료·집계 CSV·네 PNG 27개 파일은 연구본과 바이트가 같고, 세 current descriptive manifest 및 run manifest의 실제 입력·출력 해시를 대사했다.
- 실제 사례 페이지·API·관측 CSV에서 2014~2019년 여섯 행·정확한 11열·단위·정의·출처·선행 조건을 확인했다. 본 사례는 `results=[]`, `outcomes=[]`, `causal_estimation=not_run`이며 효과 CSV에 행이 없다. 네 PNG는 유효한 이미지이며 사이트 복사본도 같다. 기록된 실행일, 그림을 표보다 먼저 보여 주는 순서와 한 열 배치·원본 크기 링크를 회귀 테스트로 검증했다. 로컬 문서·사례 페이지 링크와 공개 파일의 개인 절대 경로·세션 값 검사를 수행했다.

독립 검토는 원자료 의미·연령 그림, report/runner, synthetic site adapter와 실제 제출 통합을 서로 다른 범위로 나누어 수행한다. 기존 report/runner의 15파일 품질 검토 및 adapter fixture 검토를 실제 제출본 전체 승인으로 확대하지 않는다. 실제 제출본 spec·fresh quality 검토와 desktop/mobile 브라우저 점검의 최종 기록은 별도 조정·검토 단계에 있다.

현재 재현 절차는 [data/README.md](data/README.md)와 현재 세 descriptive manifest를 따른다. `visualization-notes.md` 등 과거 문서에 나오는 `.local/...` 명령·로그는 당시 로컬 수집·검토 기록이고 새 checkout에 포함된 재현 파일을 뜻하지 않는다. 과거 source/review 해시는 당시 근거로 유지했으며 현재 코드 해시로 치환하지 않았다. 원화면 TAAS JPG는 포함하지 않고 공식 원출처와 역사 기록 설명을 남겼다.

원자료 XML/CSV·가공 series는 data ignore로 배포하지 않는다. 새 checkout은 입력을 별도 획득·대사해야 한다. 검증 성공은 반사실·운전 노출·교란을 해결하거나 정책 인과효과·개인 운전 위험·자료 이용조건의 법률상 공개 권한을 승인하지 않는다. 분석·법률상 공개 승인 플래그는 false다.
