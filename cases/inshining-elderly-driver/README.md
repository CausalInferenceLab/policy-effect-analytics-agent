# 면허 반납 지원은 고령운전자 사고를 줄였는가?

작성자: 김인엽 · GitHub ID: inshining · 갱신일: 2026-11-01

**관측 비교 완료 / 정책 예방효과는 식별하지 못함(`not_identified`).** 부산의 65세 이상 가해운전자 사고는 2017~2019년 건수와 고령 주민인구 대비 빈도 모두 증가했다. 검증된 반사실이 없어 이 증가를 정책 실패·효과 없음·개인 위험 증가로 바꾸지 않는다.

완성 결과는 [사례 보고서](report.md)에 있다. 부산 변화 → 전국 참고선 → 같은 지역의 연령 비교 → 교란과 비교군 불확실성 순서로 네 그림과 여섯 해 숫자를 제시한다. [토론](discussion.md)은 인용 가능한 결론과 계획 변경을, [비교 적격성](comparison-feasibility.md)은 전주·군산을 확정 미처치로 쓸 수 없는 이유를 설명한다. 사고건수는 보도된 사망자 수와 다른 결과다.

| 완료한 일 | 이번에 하지 않은 일 |
| --- | --- |
| 검토된 원자료·코드·집계 CSV·네 그림 SHA256 대사 | 인과효과·신뢰구간·p값 추정 |
| 부산2014~2019 사고·직전12월 주민인구·연령별 관측 비교 | 전주·군산 신규 숫자 집계·확정 미처치 승인 |
| 연령 불명 별도 보존·2016년 인구 정의 경계 표시 | estimator/estimate/refute 실행·사전등록 완료 주장 |
| 오프라인 보고서·실행 로그·manifest 생성 | 원자료 재배포·법률상 포괄 공개 승인 |

## 재현

프로젝트 루트에서 실행한다.

```sh
python3 cases/inshining-elderly-driver/run_descriptive.py
python3 -m unittest discover -s cases/inshining-elderly-driver -p 'test_*.py' -v
```

기본 실행은 네트워크0이며 검증 후 `report.md`, `flow_log.json`, `run_manifest.json`만 갱신한다. 원자료·그림이 없거나 해시·집계가 다르면 쓰기 전에 실패한다. 새 출력 세 경로를 `--report-output`, `--flow-output`, `--manifest-output`으로 지정하면 기존 파일을 덮어쓰지 않는 임시 재현이 가능하다. 그림은 자동 재생성하지 않으며 각 모듈 명령과 입력 확보는 [데이터 안내](data/README.md)를 따른다. 원자료·가공 CSV는 기존 `**/data/` 제외 규칙으로 Git에 없으므로 새 clone이 즉시 같은 스냅샷을 재생한다고 약속하지 않는다.

[출처·이용조건](source-use-notes.md)은 사실 집계·자체 차트와 원표/화면·DB 재배포 및 서버 접근을 구별한다. [실행 로그](flow_log.json)의 `results=[]`, `causal_estimation=not_run`은 효과 추정 미실행을 뜻하며 `status=completed`는 관측 검증·보고의 완료 범위다.

## 계획과 기록

[plan.yaml](plan.yaml)은 기존 상위 스키마에 맞춘 인과 설계 호환 초안이며 시차 도입 ATT 구현·실행 증거가 아니다. 설계 수치와 유의성 기준을 관측 결과에 유리하게 바꾸지 않았다. 계획 작성 전 보도·선행연구를 알고 있었고 원자료를 열람한 뒤 기술 비교를 보완했으므로 이번 결과는 **탐색적 분석**이다.

수집·경계·정의의 상세 기록은 [수집 보고서](collection-report.md), [자료 점검](data-audit.md), [정책 기록](policy-register.yaml), [정책 원문 검토](policy-review.md), [실행·독립 검토 프로토콜](execution-review-protocol.md)에 있다. 기존 정책 JSON/register의 candidate·hold와 `analysis_approved=false`는 유지한다. 로컬 완료와 상위 프로젝트 PR·게시 완료는 별개다.
