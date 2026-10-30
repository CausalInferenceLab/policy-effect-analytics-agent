# 강남대로 버스 분산 이후의 방향별 변화와 단기 예측

**2024년 광역버스 분산 이후, 같은 강남대로의 버스 기록은 왜 남행과 북행에서 반대로 변했을까?** 공공데이터의 대상·정의·관측 가능성을 확인하고, 다른 원인 후보와 다음 해 기록을 대조한 학생 프로젝트다. 작성자 `sgim49697-ops`, 트랙 B. 가설과 분석.

## 처음 읽는 순서

1. **[프로젝트 설명 HTML](project-overview.html)** — 정책 배경 → 데이터와 비교 집단 → 방법 → 발견 → 원인 후보 → 학습·예측 → 활용. 파일을 내려받아 브라우저로 열면 인터넷 없이 본문과 도표를 읽고 인쇄할 수 있다.
2. **[결과 요약](report.md) · [해석과 활용](discussion.md)** — 확인한 사실과 아직 판단할 수 없는 내용을 짧게 읽는다.
3. **[상세 종합](deepening-summary.md) · [공개 검토와 재현](deepening-reproduction.md)** — 집계표, 데이터 정의, 학습 조건, 계산 의존성을 확인한다.

관측 가능한 서울버스 고정 13개에서 2024년 여름의 정규화 시간 기록 지수는 남행 −49.71%, 북행 +41.03% 변했다. 이 13개는 정책 대상 광역버스 20개와 다른 집단이다. 시간 값의 단위·정차 경계가 미확정이므로 실제 분 단위 절감이나 정책의 인과효과로 읽지 않는다. 일반도로 속도 예측은 별도 실험이다.

## 다운로드한 공개 파일 검증

Python 3.12에서 사례 폴더로 이동해 실행한다. 외부 패키지·원자료·모델·GPU·인증키·네트워크가 필요하지 않다.

```bash
cd cases/sgim49697-ops-gangnam-bus-2024
python review_submission.py --check
```

이 명령은 핵심 수치 229개, 직접 근거 35개, 공개 산출물 155개와 HTML의 표시 수치를 대조한다. [추가 수치 151개](results/deepening/review/key_numbers.csv)와 [이전 수치 78개](results/overnight/review/key_numbers.csv)에서 원래 집계표의 행·열·선택 조건으로 돌아갈 수 있다. 전체 로컬 감사와 재학습은 수행하지 않는다.

## 질문별 근거

| 확인할 내용 | 안내 |
|---|---|
| 데이터 정의·당시 노선·폐선 영향 | [시간 필드](deepening-definition-report.md), [역사 목록](deepening-history-report.md), [고정 13개 비교](deepening-cohort-report.md) |
| 새 정류소 운영·주변 도로·시행일 이전 변화 | [운영 이력](deepening-infrastructure-report.md), [도로 공간 차이](deepening-road-report.md), [전환 주간](deepening-transition-report.md) |
| 월별 자료 공개 지연과 예측 | [공개 시각](deepening-availability-report.md), [학습·성능 비교](deepening-archive-report.md) |
| 자료 수집·문헌·초기 설계 | [데이터 보관 안내](data/README.md), [문헌](deepening-literature.md), [최초 계획](plan.md) |
| 전체 계산 경로·과거 실험 | [재현 안내](deepening-reproduction.md), [과거 기록 보관 안내](archive.md) |

## 저장 범위

코드·설정·출처 명세·테스트와 설명에 필요한 집계·그림을 공개한다. [공개·보관 목록](submission-manifest.json)에 파일별 경로·해시·사유를 기록했다. 상세 관측표·개별 예측·중간 결과·과거 보고서는 원래 경로에 로컬 보관하고 Git 추적에서 제외한다. 원자료·가중치·실행 캐시도 Git에 넣지 않는다.

최초 실행계획 원문과 동결 설정은 보존했다. 2026년 잠금 시험값은 사용하지 않았다. 원자료의 정의·정책 노선의 당시 ID 대응·역사적 공개 시각에는 미확인 사항이 남아 있다.

저장소 기본 검사는 루트에서 `make check PY=.venv/bin/python`으로 실행한다. 선택 ML 패키지가 없는 환경에서는 일부 검사가 건너뛰어진다. 이번 정리의 검증과 변경 범위는 [진행 기록](deepening-plan.md)에 남긴다.
