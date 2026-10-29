# 두 번째 탐색에 연결한 연구와 공식 분석자료

2026-10-29에 확인한 원문과 기존에 읽은 자료를 질문별로 연결한다. 앞선 [문헌 기록](literature.md)은 보존했다. 아래는 실제 읽은 부분의 요약이며 논문 전체를 재현했다는 뜻이 아니다. 새 원문의 URL·확인 범위·크기·해시는 [출처 명세](deepening-sources.json)와 [참고 출처](deepening-reference-sources.json)에 있다.

## 먼저 읽을 세 자료

1. **박수진·양재환(2025), 「Soft-DTW 기반 클러스터링을 활용한 중앙버스전용차로 정류장 정체 유형 분석」.** [학회 원문](https://www.jkst.or.kr/articles/article/2XzE/), 본문 765~768쪽. BMS의 정류장 간 출발→출발 시간과 15분 집계를 확인했다. 정류장·시간대를 나누는 근거로 유용하지만 우리 OA-21217 필드와 같은 정의라는 근거는 아니다. 현재 [방향·노선 비교](deepening-cohort-report.md)는 Soft-DTW 군집 실험이 아니다.
2. **전범준·박대근·박순용·마경훈(2024), 「고내구성 포장 도입 통한 중앙버스전용차로 유지관리 개선방안」, 서울연구원 2024-PR-10.** [발행 페이지](https://www.si.re.kr/bbs/view.do?key=2024100039&pstSn=2502190011), [공개 PDF](https://www.si.re.kr/atch/fileDown.do?cnncSn=2502190011&cnncTy=bbs&ordr=2). 126쪽 중 인쇄 26~28쪽과 86~89쪽, 관련 표·도면을 읽었다. 버스 교통량은 2024년 7월 기준 첫차·막차·배차계획을 이용한 산정값이며, 도로점용 결과는 가상 도로망의 VISSIM 시뮬레이션이다. 강남대로의 실제 일별 차량 수나 이번 공사의 관측 효과로 가져오지 않았다. 페이지 발행 표기는 2024-12-31이며 도서관의 2025-02-14 수록일과 구별한다.
3. **Tatbul 등(2018), “Precision and Recall for Time Series.”** [NeurIPS 원문](https://proceedings.neurips.cc/paper_files/paper/2018/file/8f468c873a32bb0619eaeb2050ba45d1-Paper.pdf), 서론·4.1~4.3절과 식 3~9. 개별 시점의 정밀도·재현율과 연속 구간 감지가 다른 평가라는 원칙을 참고했다. 이번 [경보 분석](deepening-episode-report.md)은 시작 전/시작 시점/진행 중 발행과 검열을 별도로 정의한 지표이며 논문의 범위 정밀도 공식을 그대로 구현한 것은 아니다.

## 방법을 선택할 때 참고한 자료

| 질문 | 원문·읽은 범위 | 이번 적용과 한계 |
|---|---|---|
| 시행일에 추세 항을 어떻게 연결하는가 | Bernal·Cummins·Gasparrini의 중단 시계열 튜토리얼 [정정문](https://researchonline.lshtm.ac.uk/4657832/1/2017_lopezbernal_IJE_correction.pdf) 1쪽, DOI `10.1093/ije/dyaa118`; [저자 R 코드](https://raw.githubusercontent.com/gasparrini/2017_lopezbernal_IJE_codedata/master/Rcode.R)의 추세·계절성·자기상관 및 중심화 부분 | 사후 기울기를 `(T−T0)×post`로 중심화하고 요일/추세 가정을 모두 비교했다. 원 논문은 초록만 확인했고 본문 전체를 확보하지 못했다. 현재 회귀는 기술 비교이며 인과 효과·유의확률·자기상관 보정 신뢰구간을 산출하지 않았다. [결과](deepening-transition-report.md) |
| 예측구간 폭과 누락을 함께 평가하는가 | Gneiting·Raftery(2007), [“Strictly Proper Scoring Rules, Prediction, and Estimation”](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf), 6.2절 식 (43) | 명목 80% 구간의 폭과 양쪽 이탈 벌점을 함께 보고했다. 포괄률만 높아지는 넓은 구간과 비교한다. 조건부·시간별 포괄률 보장을 얻었다고 주장하지 않는다. [월별 파일 모형](deepening-archive-report.md) |
| 시계열 평가에서 미래 입력을 어떻게 막는가 | Hyndman·Athanasopoulos, [Forecasting: Principles and Practice 3, 5.10절](https://otexts.com/fpp3/toolbox.html#time-series-cross-validation) | 훈련·튜닝·평가를 시간으로 분리하고 발행 시각에 공개된 입력만 사용했다. 교재의 이동 원점 재학습 평가를 구현한 것은 아니며 이번 모델은 고정 학습 상태다. |
| 분위수 손실과 실제 계산 자원은 무엇인가 | CatBoost [MultiQuantile 공식 명세](https://catboost.ai/docs/en/concepts/loss-functions-regression), [예측 인자 공식 명세](https://catboost.ai/docs/en/concepts/python-reference_catboostregressor_predict) | 분위수 3개를 학습하고 예측 정렬 여부를 별도 확인했다. 예측 호출도 기본 전체 코어 대신 CPU 2스레드로 지정했다. CatBoost 손실 자체가 보정된 예측구간을 보장하지는 않는다. |
| 버스 운행 개선과 승객 편익을 구분하는가 | 하희동·김도경·최영우(2025), [「대기행렬 기반 중앙버스전용차로 정류장 운영전략 개발」](http://www.ijhe.or.kr/journal/article.php?code=95282), HTML 본문과 특히 자료·방법 3장 | BMS·카드·교차로 운영 자료의 역할을 구분한다. 이번 시간당 횟수·승차 기록으로 배차간격 분산, 대기행렬 길이, 추가 보행 편익을 산출하지 않았다. |

서울연구원 보고서의 시뮬레이션은 신호 주기·회전 비율·방향별 버스량·차로 점용 같은 조건을 명시한다. 이 때문에 다음 수집을 “주변 자료를 더 많이”에서 **당시 신호 현시, 회전량, 차로 통제 적용일**로 좁힐 수 있었다. 해당 가정이나 시뮬레이션의 초 단위 결과를 우리 링크에 대입하지 않았다.

## 정책·시설 자료가 해석에 바꾼 점

| 자료 | 실제 확인 범위 | 연결한 판단 |
|---|---|---|
| [서울시 2025-01-06 개통 안내](https://mediahub.seoul.go.kr/archives/2013139) | 1월 11일 개통 예정, 중앙/가로변 정류소별 노선 표, 위치도와 영동1교·시민의숲 조감도 | 기존 13개를 중앙 안내 7·가로변 안내 4·해당 행 미수록 2로 분류했다. 실제 집계의 새 정류소 첫 양수 날짜를 별도 원본으로 확인했다. |
| [2023-06-21 서울시의회 회의록](https://ms.smc.seoul.kr/record/recordView.do?key=279e8a70cc0c39a40f9ac388dfe0ce45f5b310361158db5b6560b68b0a20308b3725cd47d6ab8d6b), [2023-11-02 감사](https://ms.smc.seoul.kr/record/recordView.do?key=4833d0888ff75d435db3fd39dd276a674565cde2a50768454885758e3f741b6adf7c5572346477c5) | 헌릉로 청원 안건의 착공 예정·가로변/유턴 존치 요청, 업무보고 35쪽을 설명하는 공사 진행 문단 | 2023~2025년에 시설 조건이 같았다고 두지 않는다. 2024년 일별 공정이나 실제 차로 통제표를 확보한 것은 아니다. |
| [서울시 시민기자 2023-07-12 현장 기록](https://mediahub.seoul.go.kr/archives/2008470) | 7월 8일 1구간 개통을 설명하는 직접 방문 기사·사진 | 2023년 사후 창에도 별도 사건이 있었다. 시민기자 기록과 행정 준공 문서를 구별한다. |
| [서초 2024년 6월 소식지](https://seocho.newstool.co.kr/pdf/seocho_202406.pdf) 16면, [2024-11-19 서초구의회 회의록](https://sdc.seoul.kr/main/minutes/html/MinutesView.do?MINTS_SN=5089) 도로과 처리 결과 | 영동1교~태봉로 개통 예정 약도, 6월 29일 공사 완료 진술 | 주변 일반도로 속도의 대안 설명 후보를 고정했다. 약도로 정확한 링크 노출이나 공사 효과를 확정하지 않았다. |

공식 안내와 원본 집계가 맞는 부분, 자료에 없는 부분을 함께 읽어야 한다. 상세한 접근 제약과 다음 질문은 [종합의 수집 순서](deepening-summary.md), [시간 명세 확인](deepening-definition-report.md), [경기 자료 감사](deepening-gyeonggi-report.md)에 연결했다. 추가 원문은 로컬 원본으로 보존하고 저장소에는 자체 요약·출처·해시만 공개했다.
