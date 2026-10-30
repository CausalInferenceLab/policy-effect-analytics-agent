<!-- archive.md - 공개 목록 밖의 과거 문서·상세 산출물과 안전한 복구 방법을 안내한다. -->
# 과거 문서와 상세 산출물 보관 안내

최신 설명은 [HTML](project-overview.html)과 [결과 요약](report.md)에서 시작한다. 전체 코드·설정·테스트를 유지하면서 공개 결과를 줄였으며, 파일 정리는 분석을 다시 수행한 것이 아니다.

정리 기준은 커밋 `a40dd51beb277aadc05faba26879eaa3fec4e1d7`이다. 기존 928개 파일 중 444개를 공개 보존 대상으로 골랐고, 484개는 원래 경로에 로컬 보관하며 Git 추적에서 제외했다. 이후 추가한 정리 명세·검증기·이 안내는 그 수에 포함하지 않는다. 제외 파일의 정확한 경로·바이트·SHA-256·사유는 [정리 명세](submission-manifest.json)의 `archived_files`에 있다.

<a id="reports"></a>
## 과거 보고서와 초기 실행 안내

초기 일반도로·GPU 분석과 이전 탐색 문서는 당시의 질문·실행 조건·결과를 기록한 것이다. 최신 결과와 함께 읽을 때 분석 대상과 시기를 구분한다. 현재 결과 진입점으로 바뀐 파일의 이전 버전은 다음과 같다.

- [초기 실행 명령을 포함한 README](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/README.md)
- [초기 일반도로·GPU 결과](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/report.md)
- [초기 해석·한계](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/discussion.md)

추적에서 제외한 문서 28개는 아래 표에서 기준 커밋의 원문을 열거나, 로컬의 같은 파일명을 찾아 읽는다.

| 문서 | 기준 커밋 원문 |
|---|---|
| `deepening-geometry-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/deepening-geometry-report.md) |
| `evidence.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/evidence.md) |
| `followup-plan.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/followup-plan.md) |
| `followup-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/followup-report.md) |
| `literature.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/literature.md) |
| `overnight-alert-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-alert-report.md) |
| `overnight-auxiliary-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-auxiliary-report.md) |
| `overnight-baseline-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-baseline-report.md) |
| `overnight-conditional-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-conditional-report.md) |
| `overnight-confirmation-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-confirmation-report.md) |
| `overnight-context-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-context-report.md) |
| `overnight-evidence.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-evidence.md) |
| `overnight-forecast-plan.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-forecast-plan.md) |
| `overnight-forecast-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-forecast-report.md) |
| `overnight-hour-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-hour-report.md) |
| `overnight-interval-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-interval-report.md) |
| `overnight-operations-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-operations-report.md) |
| `overnight-path-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-path-report.md) |
| `overnight-plan.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-plan.md) |
| `overnight-road-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-road-report.md) |
| `overnight-route-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-route-report.md) |
| `overnight-segment-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-segment-report.md) |
| `overnight-subway-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-subway-report.md) |
| `overnight-summary.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-summary.md) |
| `overnight-timeline-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-timeline-report.md) |
| `overnight-weather-performance-report.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/overnight-weather-performance-report.md) |
| `research-request.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/research-request.md) |
| `verification-request.md` | [보기](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/blob/a40dd51beb277aadc05faba26879eaa3fec4e1d7/cases/sgim49697-ops-gangnam-bus-2024/verification-request.md) |

<a id="results"></a>
## 상세 산출물

공개 결과 155개에는 핵심 수치의 직접 근거, 보조 비교·품질 집계, 사용한 그림, 선택·학습·감사 명세가 들어 있다. 표는 특정한 유리한 행만 잘라 보존하지 않았다.

나머지 456개 결과 파일은 상세 일별·시간별 표, 개별 적합·잔차, 보조 추출 기록, 본편에서 사용하지 않는 과거 결과·그림 등이다. 로컬의 `results/`에서 원래 경로를 유지한다. 공개 보고서의 보관 안내 옆에는 필요한 파일명을 적었다. 공개 검증은 이 파일들을 읽지 않으며 전체 로컬 감사가 통과했다고 주장하지 않는다.

기존 감사 JSON 안의 제외 파일 경로와 해시는 과거 계산의 증거로 남겼다. 새 공개 파일만으로 전체 산출물을 다시 만든다는 뜻이 아니다.

<a id="restore"></a>
## 복구와 전체 로컬 감사

현재 작업 폴더에서는 추적만 해제했으므로 파일을 다시 받을 필요가 없다. 원자료 `data/`, 실행·모델 `runs/`, 가상환경과 캐시도 삭제하지 않았다.

새 복제본에서 과거 추적 파일이 필요하면 기존 작업 폴더를 덮어쓰지 않고 별도 임시 폴더로 기준 커밋을 내보낸다. 저장소 루트에서 실행한다.

```bash
archive_dir="$(mktemp -d)"
git archive a40dd51beb277aadc05faba26879eaa3fec4e1d7 cases/sgim49697-ops-gangnam-bus-2024 | tar -x -C "$archive_dir"
printf '%s\n' "$archive_dir"
```

얕은 복제 등으로 기준 커밋이 없다면 먼저 해당 이력을 확보해야 한다. 위 명령은 과거 Git 추적 파일만 복구하며, Git에 없던 원자료·모델은 복구하지 않는다. 현재 폴더에 `git restore`나 `git reset`으로 일괄 덮어쓰지 않는다.

[재현 안내](deepening-reproduction.md)의 전체 검토기는 상세 산출물이 있는 환경에서 실행한다. 기록 비율 재집계에는 PyYAML이 필요하고, 모델 동결 확인에는 기존 실행 파일과 해당 환경이 필요하다. 원자료부터 새로 계산할 때의 입력 순서와 한계도 같은 안내를 따른다.

Git 과거 이력을 삭제하지 않았으므로 이번 정리는 현재 파일 구성과 변경 목록을 줄이는 작업이다. 저장소 전체 다운로드 용량을 줄이기 위한 이력 재작성은 하지 않았다.
