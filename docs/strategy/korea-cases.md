# 국내 정책효과 분석 사례 + 재현용 해외 교과서 사례

> 목적: 멘티가 "누가 이미 이 질문을 어떤 방법·데이터로 풀었나"를 5분 안에 파악하고, **오픈데이터만으로 4주 안에 재현·확장 가능한지** 판단하도록 돕는다.
> 작성: Strategy, 2026-09-24. 링크는 모두 직접 확인한 것. "초록 미확인"은 제목/서지만 확인하고 본문을 열지 못한 경우(KCI·DBpia는 자동 접근 차단).

## 0. 한눈에 보기

| # | 정책 | 식별전략 | 결과 요약 | 오픈데이터 재현성 |
|---|---|---|---|---|
| K1 | 안전속도5030 vs 민식이법 | DiD | 5030 효과 유의, 민식이법 유의하지 않음 | ◎ (TAAS·KOSIS) |
| K2 | 안전속도5030 (서울 구간) | 비교그룹 사전·사후 (Hauer) | 전체사고 약 10%↓ | ◎ (TAAS) |
| K3 | 윤창호법 (음주운전 처벌 강화) | 사전·사후 + 전년 동기 비교 | 3개월 단기효과만 유의 | ◎ (KOSIS/TAAS) |
| K4 | 대형마트 의무휴업 평일 전환 | 지역 간 비교 회귀 (DiD형) | 마트↑, 온라인↓, 전통시장 부정효과 없음 | △ (카드데이터 비공개 → 서울 상권 추정매출로 대체) |
| K5 | 지역화폐 도입 | 삼중차분(DDD) | 소매업 전체 매출 효과 없음 | ✕ (SBDC 마이크로데이터) |
| K6 | 1차 긴급재난지원금 | 카드매출 전후·업종 비교 | 투입액의 26.2~36.1% 매출 증가 | ✕ (카드사 데이터) |
| K7 | 토지거래허가구역 지정(잠실 등) | DiD / 사례비교 | (초록 미확인) | ◎ (국토부 실거래가 API) |
| K8 | 연세로 대중교통전용지구 | 합성통제(SCM) | (초록 미확인) | △ (서울 상권 매출은 2021년 이후만 제공) |
| K9 | 청주·청원 통합 | 합성통제(SCM) | (초록 미확인) | ○ (KOSIS·지방재정365) |
| K10 | 지자체 출산지원금 | MGWR (횡단면 상관) | 지역별로 부호가 다름 | ◎ (KOSIS) — **인과 설계가 아님** |
| K11 | 지자체 혼인장려금 | (초록 미확인) | (초록 미확인) | ◎ (KOSIS) |
| K12 | 서울 녹색교통지역 5등급 차량 운행제한 | (초록 미확인) | 서울시 발표: 5등급 통행량 감소 | ◎ (에어코리아) |

기호: ◎ 결과·처치 모두 오픈데이터, ○ 일부 수작업 수집 필요, △ 대체 지표 필요, ✕ 승인 필요 마이크로데이터/민간데이터.

---

## 1. 국내 사례 상세

### K1. 도로 제한속도 규제 효과: 민식이법 vs 안전속도5030 — ★재현 1순위
- 출처: 김기만·배관표 (2024), 「도로속도제한의 규제효과 분석: 민식이법과 안전속도5030의 비교」, 『규제연구』 33(2). [PDF](https://journal.kci.go.kr/ksrs2002/archive/articlePdf?artiId=ART003165741) · [KCI](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003165741)
- 식별: 이중차분(DiD). 분석기간 2017–2019 vs 2021–2023 (2020년 제외).
- 데이터: 경찰청, 한국도로교통공단, 국토부 교통통계.
- 결과: 5030은 사고 10,851건, 사망 164명, 부상 18,830명 감소로 추정. 민식이법은 통계적으로 유의한 효과를 찾지 못함.
- 쓸모: **같은 데이터로 "효과 있음"과 "식별·검정력 부족"이 함께 나오는 사례**라서, 에이전트의 기권(abstention) 로직을 시연하기 좋다. 2020년(코로나)을 뺀 선택 자체가 가정이므로 민감도 분석으로 확장할 수 있다.
- 관련: 「어린이보호구역 내 과속단속카메라 설치법(민식이법)의 효과」 [KCI](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003297075) (초록 미확인)

### K2. 안전속도5030 정책의 교통사고 영향 사전·사후 분석
- 출처: 한상진 (2022), 서울대 석사학위논문. [S-Space](https://s-space.snu.ac.kr/handle/10371/188539)
- 식별: 비교그룹 사전·사후(Hauer 1997 방식)와 카이제곱 검정.
- 데이터: TAAS 도로구간별 사고(전체, 차대차, 차대사람).
- 결과: 전체·차대차 사고 약 10% 감소. 차대사람 사고 약 38% 감소는 표본이 적어 신뢰성이 낮음. 더 엄격한 검정에서는 종로 구간만 유의.
- 쓸모: 구간(도로) 단위 분석, **희소 사건(사망·보행자 사고)의 검정력 문제**를 보여 준다.

### K3. 윤창호법의 음주운전 억제효과 — 입문용
- 출처: 박철현 (2022), 「윤창호법의 음주운전 억제효과」, 『사회통합연구』 3(2). [e-sir](https://www.e-sir.org/archive/view_article?pid=sir-3-2-97)
- 식별: 시행 전후 3개월·6개월을 **전년 같은 기간**과 비교(준실험). 제1·제2 윤창호법 두 시점.
- 데이터: 경찰청 교통사고 통계(KOSIS).
- 결과: 3개월 단기 감소(제1법 52%, 제2법 61%)는 유의. 6개월 효과는 유의하지 않음 → 억제효과가 일시적.
- 확장: 월별 단절시계열(ITS) + 비음주 사고를 대조 시계열로 쓰는 comparative ITS, 시군구 패널.

### K4. 대형마트 의무휴업 평일 전환 효과 (KDI FOCUS, 2026.5)
- 출처: KDI FOCUS 「의무휴업일 평일 전환이 시사하는 유통정책의 전환 방향」 [KDI](https://www.kdi.re.kr/research/focusView?pub_no=19187) · 요약 기사 [다음/조선](https://v.daum.net/v/20260521123417873)
- 식별: 평일 전환 지자체(대구·청주·서울 일부 등 약 30곳)와 주말 휴업 유지 지역의 매출 추이 비교(DiD 형태의 회귀).
- 결과: 대형마트 매출 2.8~7.9%↑, 온라인 매출 감소(대구 −2.89%), 전통시장은 유의한 부정효과 없음(일부 최대 +15.4%).
- 재현성: 카드 매출 원자료는 비공개. **서울 자치구 전환(서초 2024.1~, 동대문, 중구 2024.11~)은 서울 상권분석서비스 추정매출(2021~, 분기)로 다시 풀 수 있다** → topic-guide T2.
- 참고(원 규제의 효과): 「대형마트 의무휴업이 중소서비스업체에 미치는 효과: 신용카드매출 데이터를 활용한 분석」 [KCI](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002505193) (초록 미확인)

### K5. 지역화폐 도입이 지역경제에 미친 영향 (한국조세재정연구원, 2020)
- 출처: 송경호·이환웅, KIPF 수시연구과제. [PDF](https://www.kipf.re.kr/uloads/kiPublish/202012/FILE_202102020125031083.pdf) · [발간 페이지](https://www.kipf.re.kr/kor/Publication/All/kiPublish/ALL/view.do?serialNo=526520)
- 식별: 삼중차분(지역화폐 도입 여부 × 시기 × 지역 내 수혜업종), 미도입 지자체를 통제군으로 사용.
- 데이터: 통계청 SBDC 기업등록부DB(2011–2018) 전수 + 지자체 발행액.
- 결과: 소매업 전체 매출 증가 효과는 확인되지 않음. 슈퍼마켓·식료품점에서만 유의.
- 재현성: ✕ (SBDC 원격접근 승인 필요). **"같은 정책에 상반된 보고서가 나온 사례"**로 가정·데이터 선택의 중요성을 보여 줄 때 쓴다([머니투데이 논쟁 정리](https://www.mt.co.kr/economy/2020/09/24/2020092117520680414)).

### K6. 1차 긴급재난지원금 효과 (KDI, 2020)
- 출처: KDI FOCUS 「1차 긴급재난지원금 정책의 효과와 시사점」 [KDI](https://www.kdi.re.kr/research/focusView?pub_no=16851) · [정책브리핑 요약](https://www.korea.kr/news/policyFocusView.do?newsId=148881598&pkgId=49500742)
- 식별: 지급 전후, 사용 가능 업종과 불가 업종의 카드매출 비교(업종 간 DiD 구조) + 가구 설문.
- 결과: 카드매출 약 4조 원 증가(투입액의 26.2~36.1%). 사용 가능 업종 매출 증가율이 −4.0%에서 +7.1%로 올라 11.1%p 차이.
- 재현성: ✕ (카드사 데이터). 업종 간 대조 설계 아이디어만 가져올 것.

### K7. 토지거래허가구역 지정 효과 (서울 잠실·삼성·대치·청담)
- 출처(초록 미확인): 「토지거래허가구역 지정이 매매가와 전세가에 미치는 영향: 잠실동 아파트 사례분석」 [교보스콜라](https://scholar.kyobobook.co.kr/article/detail/4010071233597) · 「토지거래허가구역 지정의 풍선효과 분석: 잠실·삼성·대치·청담동 사례」 [DBpia](https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE12208115) · 「토지거래허가제가 인근지역에 미치는 풍선효과」 [KIPF](https://www.kipf.re.kr/cmm/fms/FileDown.do;jsessionid=BF32ED215F10DBBE31C068DC7D1F2238?atchFileId=FILE_000000024724Mq7&fileSn=0) · 「서울시 토지거래허가제의 지가 안정화 효과」 [부동산연구](https://www.ejrea.org/archive/view_article?pid=jrea-11-2-1)
- 재현성: ◎ 국토부 아파트 매매 실거래가 API가 무료·자동승인([data.go.kr 15126468](https://www.data.go.kr/data/15126468/openapi.do)). 2025년 2월 해제 후 3월 재지정·확대([KB 정리](https://kbthink.com/main/asset-management/wealth-manage-tip/kbthink-original/202504/land-transaction-permission-areas.html))로 **켜짐·꺼짐·확대가 모두 있는 자연실험**이 생겼다 → topic-guide T3.

### K8. 연세로 대중교통전용지구의 상권 효과 (SCM)
- 출처: 「서울시 연세로 대중교통전용지구 정책의 상권 활성화 효과 분석: 통제집단합성법을 활용하여」, 『국토계획』. [KPAJ](https://kpaj.or.kr/_PR/view/?aidx=40522&bidx=3654) (초록 미확인). 정책 배경 [서울정책아카이브](https://seoulsolution.kr/node/3015), 2024년 해제 결정 [서울시](https://news.seoul.go.kr/traffic/archives/513420)
- 관련: 「통제집단합성법을 활용한 차 없는 거리 정책의 도시 활력 증진 효과 분석」 [한양대 repository](https://repository.hanyang.ac.kr/handle/20.500.11754/177190) (초록 미확인)
- 재현성: △ 서울 상권분석서비스 추정매출은 **2026.7.3부터 2021년 이후 자료만 제공**([OA-15572](https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do)). 따라서 2014년 지정 효과는 재현할 수 없고, **해제(2024년 결정) 효과**만 볼 수 있다.

### K9. 청주·청원 통합 효과 (SCM)
- 출처: 「기초지자체 통합 효과 분석: 청주-청원 통합 사례를 중심으로」 [KCI](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002794493) (초록 미확인)
- 쓸모: **처치 단위 1개 + 행정경계 변경**이 함께 있는 SCM의 전형이다. 통합 전 시계열을 새 경계로 합산해야 하는 문제(행정경계 변경 함정)를 연습할 수 있다.

### K10. 출산지원금이 지역 출산력에 미치는 영향의 공간적 변이 (보건사회연구, 2022) — "인과 아님" 반면교사
- 출처: 장인수·정찬우 (2022), 『보건사회연구』 42(4). [PDF](https://www.kihasa.re.kr/hswr/assets/pdf/1379/journal-42-4-305.pdf)
- 방법: 228개 시군구, 2019년 지원금 × 2020년 출산율의 MGWR(횡단면).
- 결과: 대체로 양(+)의 상관이지만 지역에 따라 부호가 다름.
- 쓸모: **횡단면 상관은 정책효과가 아니다.** 같은 KOSIS 데이터를 시군구×연도 패널과 지원금 인상 시점 기반 staggered DiD로 다시 설계하는 것이 좋은 확장 과제다 → topic-guide T7. 선행 패널 연구: [KDI EIEC 요약](https://eiec.kdi.re.kr/policy/domesticView.do?ac=0000185938), [KCI](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002407474) (초록 미확인)

### K11. 지방자치단체 혼인장려금 정책이 혼인 건수에 미치는 영향
- 출처: 『지방행정연구』 계열 논문 [PDF](http://www.kala.kr/data/file/articlesearch/3754092228_xFluc9Mm_01_EC8690ED98B8EC84B1_EAB980EC8898EC9881.pdf) (리다이렉트 오류로 본문 미확인)
- 재현성: 결과(시군구 혼인건수)는 KOSIS. 처치(도입 시점·금액)는 조례에서 직접 수집해야 한다.

### K12. 서울 녹색교통지역 5등급 차량 운행제한
- 정책: 사대문 안 16.7㎢, 5등급 차량 06~21시 운행제한, 2019.7 시범 운영 후 **2019.12 과태료 부과 시작**, 저감장치 개발이 안 된 차종은 2020.12.31까지 유예([서울시](https://news.seoul.go.kr/traffic/greentraffic)).
- 선행: 「서울특별시 자동차 운행제한 정책에 따른 대기질 개선 효과 분석」 [ResearchGate](https://www.researchgate.net/publication/389635332_seoulteugbyeolsi_jadongcha_unhaengjehan_jeongchaeg-e_ttaleun_daegijil_gaeseon_hyogwa_bunseog) (초록 미확인, 429 오류). 서울시 발표: 2년 만에 5등급 통행 58.6% 감소([서울신문](https://www.seoul.co.kr/news/society/2022/01/25/20220125500110)). 이는 준수율(1단계 결과)이고, 대기질(최종 결과) 효과는 아니다.
- 재현성: ◎ 에어코리아 최종확정 측정자료 2001–2026 연도별 다운로드([에어코리아](https://www.airkorea.or.kr/web/last_amb_hour_data?pMENU_NO=123)) → topic-guide T1.

### 참고: 기관별 평가 체계 (사례 탐색용)
- KDI 공공투자관리센터 재정사업 심층평가 보고서 목록: [PIMAC](https://pimac.kdi.re.kr/study/study_list.jsp?classcd=F5) / 심층평가 지침 [KDI](https://kdi.re.kr/research/subjects_view.jsp?pub_no=10067)
- KIPF 재정사업 심층평가(예: 2021 창업지원 사업군): [KIPF repository](https://repository.kipf.re.kr/handle/201201/8740)
- 대부분 부처 행정 DB(고용보험 등)를 쓰므로 ✕이다. 다만 **평가 질문을 어떻게 정의했는지**와 성과지표 체계는 plan.yaml의 `question`/`outcome`을 작성할 때 참고할 만하다.

---

## 2. 해외 재현용 교과서 사례 (벤치마크 맵에 없는 것만)

이미 정리된 벤치마크 맵은 거버넌스·도구 중심이다. 아래는 **에이전트 회귀 테스트(golden case)**로 쓸 수 있는, 정답이 알려진 공개 데이터·코드 사례다.

| 사례 | 방법 | 공개 데이터/코드 | 추가 가치 |
|---|---|---|---|
| Card & Krueger (1994) NJ/PA 최저임금 | 2×2 DiD | [David Card data sets](https://davidcard.berkeley.edu/data_sets.html) | 가장 단순한 DiD 정답 케이스. estimator 단위 테스트용 |
| Abadie·Diamond·Hainmueller (2010) 캘리포니아 Prop 99 | SCM + placebo-in-space | [Hainmueller Synth](https://web.stanford.edu/~jhain/synthpage.html) | 처치 단위 1개(K9·K12와 같은 구조). 순열추론 기준값 |
| Callaway & Sant'Anna (2021) `mpdta` 카운티 최저임금 | staggered DiD | [`did` 패키지](https://bcallaway11.github.io/did/) | **시차 도입 시 TWFE 편향** 시연. T2·T4·T7이 모두 시차 도입이다 |
| Cheng & Hoekstra (2013) Castle doctrine | staggered DiD, 이벤트스터디 | [Mixtape 9장](https://mixtape.scunning.com/09-difference_in_differences) | 주(state) 패널 + 사전추세 그림. 한국어 멘티용 교재로도 적합 |

권장: `tests/golden/`에 Card-Krueger와 Prop 99를 넣고, 에이전트가 알려진 추정치를 허용 오차 안에서 재현하는지 CI로 확인한다(Develop 팀과 협의).
