# 실행·독립 검토 프로토콜

각 실질 단계의 작성·실행 담당과 독립 read-only 점검 담당을 분리한다. 작성 담당의 완료 보고는 승인 근거가 아니다. 조정 담당은 소유 파일·성공 기준을 지정하고, 점검 결과와 실제 증거를 확인한 후 다음 단계로 진행한다. 점검 문제는 작성자가 수정한 뒤 재검토한다. 이 문서와 검사기는 작성 산출물이며 독립 검토 전 자체 최종 승인하지 않는다.

| 단계 | 작성·실행 담당 | 독립 점검 담당의 증거 |
| --- | --- | --- |
| 정책 근거 수집 | 원문·검색 색인·미확인을 구분하고 인용문·날짜·관할·해시 기록 | 원문을 직접 대조해 인용 맥락과 지원 개시·조례·자격·최초 시행 구별 |
| 검증 코드 | 실패 테스트 확인 후 구현, 실행 명령·출력·해시 기록 | 코드와 테스트를 읽고 경계 사례를 재실행 |
| 지역 분류 | 미확인은 hold, 후보는 candidate로 기록 | 같은 관할 근거·시간 순서·후보 적격성 확인, 광역→기초 자동 추론 거부 |
| 분석·해석·문서 | 근거와 미확인·한계 구분 | 코드 일치와 의미 해석을 각각 검토, 인과성 주장 근거 별도 확인 |

## 자동 검사 범위

`policy-evidence.json`(schema_version=1)이 단일 입력이다. `audit_policy.py`는 필수 키·자료형·열거형·달력·정밀도·중복·참조·같은 관할, 스냅샷 SHA256·정확한 인용문 포함, case 밖 경로 탈출 및 시행 연도별 잠정 분류를 확인한다. 지원 개시는 같은 날짜·정밀도의 `offer_start` 또는 `first_implementation` 근거가 필요하다. 조례·소급 자격만으로 대체하지 않는다. 날짜가 알려져 있어도 예고·소급 자격 등으로 분류가 불확실하면 명시적인 `reason`과 비어 있지 않은 `unresolved_checks`를 둔 `hold`를 허용한다. 이 경우 경고와 분류 적격성 미확인을 따로 기록하며 날짜를 지우거나 candidate로 자동 변경하지 않는다. hold도 알려진 개시일의 근거 검사는 통과해야 한다.

오류는 비정상 종료로 보고하며 입력 분류는 고치지 않는다. 보고서의 `warnings`(예: 검색 색인의 원문 미확인)와 `unknowns`(예: 시행일 미확인)는 별개다. `structural_checks_passed`는 구조·일치 검사 통과만 뜻한다. `analysis_approved`는 항상 false이고 모든 정책 근거·분류는 `semantic_review_required`에 남는다.

URL 검사는 HTTPS, 사용자 정보 부재, 기본 또는 443 포트와 `.go.kr`·`korea.kr` 도메인 경계만 확인한다. 공식 도메인 밖의 HTTPS URL은 이 제한된 허용 범위 때문에 거부되며, 비공식성·거짓 내용으로 판정한 것이 아니다. 이 검사는 네트워크로 사이트 소유권·실제 게시 주체·리디렉션을 검증하지 않으며 원문 사실성의 증명이 아니다. 스냅샷에 `SEARCH INDEX EXCERPT`가 명시되어 있는데 `direct`로 기록하면 대소문자 구분 없이 모순 오류로 거부한다. 이는 명시적 표지의 일치 검사이며 표지가 없다고 직접 수집을 입증하지 않는다. 스냅샷과 인용문이 일치해도 의미가 맞는지는 독립 검토가 필요하다. candidate는 확정 미처치가 아니며 hold/unknown은 0 또는 미처치가 아니다. 한계 기재는 교란 제거·분석 승인·인과효과 입증을 대신하지 않는다.

공개 정책 원문 스냅샷은 `evidence/policy-sources/`에 보관한다. 개인정보·자격증명·세션 값은 넣지 않는다. 원시·가공 데이터의 기존 `**/data/` 제외 규칙은 유지한다.

## 재현 명령

프로젝트 루트에서 실행한다. Python 표준 라이브러리만 사용하며 입력 JSON을 수정하지 않는다.

```sh
python3 -m unittest discover -s cases/inshining-elderly-driver -p test_audit_policy.py -v
python3 cases/inshining-elderly-driver/audit_policy.py
```

두 번째 명령은 기본 입력 `policy-evidence.json`을 검사해 같은 폴더에 `policy-checks.json`을 저장한다. `--input`과 `--output`으로 경로를 지정할 수 있다. 오류가 있으면 종료 코드 1이다. 보고서에는 실제 입력 SHA256, 확인한 스냅샷의 SHA256, 재현 명령, 생성 시각과 한계를 기록한다.

## 작성 담당의 TDD 증거 (2026-10-27)

검사기 작성 전 synthetic fixture를 대상으로 위 테스트 명령을 실행했다.

```text
RED: Ran 20 tests in 0.649s; FAILED (failures=41)
원인: audit_policy.py 부재로 검사 보고서를 생성하지 못함.
추가 RED: Ran 21 tests in 2.158s; FAILED (failures=1)
원인: 순환 심볼릭 링크 경로에서 RuntimeError가 발생해 보고서가 누락됨.
GREEN: Ran 21 tests in 2.210s; OK
```

하위 사례(subTest)가 있어 최초 실패 수는 테스트 메서드 수보다 많다. 전체 출력은 로컬 `/tmp/public-data-policy-audit-red.log`, `/tmp/public-data-policy-audit-path-red.log`, `/tmp/public-data-policy-audit-green.log`에 남겼다. 이 임시 파일은 영구 보관을 보장하지 않으므로 독립 검토자는 위 명령으로 재실행해야 한다. 실제 정책 JSON의 구조·의미 검토 결과는 이 synthetic 테스트의 통과와 별도로 기록한다.

독립 검토자가 발견한 수집 방식 모순을 반영해 추가 회귀 검증을 했다.

```text
MARKER RED: Ran 22 tests in 2.237s; FAILED (failures=2)
원인: SEARCH INDEX EXCERPT 및 소문자 표지를 가진 스냅샷이 direct로 통과함.
```

수정 후 GREEN: 정책 검사기 22개 테스트 통과(2.299초), 기존 테스트 포함 전체 51개 통과(2.307초), `py_compile` 통과. 실패 출력은 `/tmp/public-data-policy-audit-marker-red.log`, 통과 출력은 `/tmp/public-data-policy-audit-marker-green.log`와 `/tmp/public-data-policy-all-tests.log`에 기록했다. 독립 재검토 결과는 조정 담당이 별도로 기록한다. 표지가 없는 direct 근거의 의미 검토 의무는 유지한다.

실제 부안군 기록의 2020년 개시일과 2019년 예고·소급 자격 불확실성이 공존하는 경우를 반영했다.

```text
KNOWN-HOLD RED: Ran 24 tests in 2.537s; FAILED (failures=2)
원인: 근거가 있는 개시일에도 candidate를 강제하고, 미해결 확인 사항이 없는 hold를 구별하지 못함.
```

회귀 테스트는 날짜 근거·보류 사유·미해결 확인 사항을 요구하며 hold를 자동 변경하지 않는지 확인한다. 실패 로그는 `/tmp/public-data-policy-audit-known-hold-red.log`에 기록했다. 변경은 작성 담당의 수정이며 최종 승인은 독립 재검토를 거친다.

수정 후 GREEN: 정책 검사기 24개 테스트 통과(2.481초), 기존 테스트 포함 전체 53개 통과(2.487초), `py_compile` 통과. 통과 로그는 `/tmp/public-data-policy-audit-known-hold-green.log`와 `/tmp/public-data-policy-all-tests.log`에 기록했다. 실제 입력을 다음 명령으로 검사한 결과 오류 0·경고 1·미확인 2, `analysis_approved=false`였다.

```sh
python3 cases/inshining-elderly-driver/audit_policy.py --output /tmp/public-data-policy-known-hold-real-checks.json
```

해당 실행의 입력 SHA256은 `2bc5cc4f7972615de40951d48a1cf809dffdc1d3c1261476ae201eca27955ba7`이다. 부안군은 2020년 개시일과 hold를 유지하며 알려진 날짜와 분류 적격성 미확인을 별도 보고했다. 이는 구조 검사 결과이며 독립 원문 해석·비교군 확정·분석 승인은 아니다.
