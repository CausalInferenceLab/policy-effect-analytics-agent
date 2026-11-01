# 원자료 확보와 저장 스냅샷 재현

`data/`의 원시·가공 XML/CSV는 기존 `**/data/` 규칙으로 Git에 포함하지 않는다. 이 안내는 데이터와 함께 보관하는 재현 설명이다. 공개 숫자·자체 차트와 원자료/DB 재배포는 다른 범위이며 [이용조건](../source-use-notes.md)을 따른다.

## 1. 보유 스냅샷 검증: 기본 네트워크0

프로젝트 루트에서 실행한다.

```sh
python3 cases/inshining-elderly-driver/fetch.py
python3 cases/inshining-elderly-driver/run_descriptive.py
```

`fetch.py` 기본값은 저장된14개 원자료(기존65+ 사고XML4, 인구CSV6, 연령별XML4)를 실제 파서와 기록된 해시로 확인하는 오프라인 점검이다. 새 다운로드가 아니다. 보고서 runner는 세 집계 순수 함수로 숫자를 재계산하고 이미 생성된 CSV3개·PNG4개·manifest를 검증한 뒤 보고서 세 파일만 갱신한다. 원자료나 그림이 없는 새 clone은 오류로 중단한다. 임의 CSV나 빈 그림을 만들어 채우지 않는다.

필요한 로컬 파일:

- `raw/taas-2014-2018-page-{1,2}.xml`, `raw/taas-2019-2019-page-{1,2}.xml`와 `../taas-qc.json`.
- `raw/population-{2013,...,2018}-12.csv`와 `../population-qc.json`.
- `raw-age/source-query-{national,busan}-{2014-2018,2019-2019}.xml`와 `../age-source-manifest.json`.
- `taas-national.csv`, `population.csv`, 집계 `descriptive-series.csv`, `population-descriptive-series.csv`, `age-descriptive-series.csv`.
- `../figures/01_busan_counts.png`부터`04_busan_age_comparison.png`까지와 대응하는 세 descriptive manifest.

보유 원본 재가공은 `population.py`(기본 오프라인), 이어 `taas.py`(기본 오프라인) 순서다. TAAS의 지역명 대응이 인구자료를 읽으므로 순서를 바꾸지 않는다. 이 명령은 해당 가공 CSV/QC를 재생성하므로 원자료 점검만 원하면 위 `fetch.py`를 사용한다.

## 2. 새 획득은 역사 스냅샷과 구별

새 다운로드의 응답·집계 바이트가2026-10-27/2026-11-01 보유 스냅샷과 같다고 약속하지 않는다. 서버 수정·조건 변경·자료 정정·부분 실패를 확인하고 기존 해시와 대조한다. 조회조건·정의·완전성이나 값이 달라지면 과거 manifest를 임의 수정해 통과시키지 않는다. 새 provenance와 독립 검토를 거친 후 재생성 경로를 정한다.

기존 인구/65+ 수집기의 명시적 네트워크 옵션은 다음과 같다. **원본 없는 별도 새 checkout/작업 복사본**에서 수행한다. 기존 사고 XML이 있으면`taas.py --fetch`는 거부한다. 인구 수집기는 기존 파일을 해시 검증·재사용하므로 부분 혼합을 피하려면 먼저 원본이 전혀 없는 새 작업공간을 사용한다. 기존 자료를 삭제해 경로를 비우지 않는다.

```sh
python3 cases/inshining-elderly-driver/population.py --download
python3 cases/inshining-elderly-driver/taas.py --fetch
```

연령별 공개 표의 새 획득은 별도 새 디렉터리로 명시한다. 아래 경로의 부모`data/`는 있어야 하고`new-age-snapshot/`은 존재하면 안 된다. 심볼릭 링크를 통하는 경로는 거부되므로 실제 물리 경로에서 실행한다.

```sh
python3 cases/inshining-elderly-driver/fetch.py --download --age-only --output-dir cases/inshining-elderly-driver/data/new-age-snapshot
```

익명 공개 UI와 같은 정상 `PublicClient` 세션/조회 흐름만 쓰며 네 쿼리의 연도·9개 연령행·사고[건]·부산/전국 조건과 완전 합계를 메모리에서 검사한다. 허용된 공개 XML 부분만 보존하고 세션·서버 식별값이 있는 컨테이너는 저장하지 않는다. 새 디렉터리에 안전 투영XML4개와`fresh-age-manifest.json`을 쓴다. 신규 manifest는`review_status=pending`이며 기존`age-source-manifest.json`을 자동 교체하지 않는다. 승인된 역사 해시와 요청 의미가 같은지 확인해야 하며, 단지 파일명을 바꿔`raw-age/`에 넣는 것은 provenance 확보가 아니다. 이번 완료 작업에서는 네트워크로 재다운로드를 반복하지 않고 synthetic client와 보유원본으로 검증했다.

## 3. 공식 UI의 보조 확보 절차

자동 경로가 현재 사이트 변경으로 실패하면 오류를 보존하고 공식 UI에서 조건을 확인한다. UI Excel/CSV 내보내기가 보유XML과 같은 바이트/구조라는 검증은 없으므로 UI 파일을 XML로 확장자만 바꿔 넣지 않는다.

- [TAAS 분석](https://taas.koroad.or.kr/OBIP25/analysis/TypicalAnalysis.jsp)의`시도 시군구별 가해운전자 연령대별 교통사고`(pattern7125): 지표`사고[건]`(334/ACC_CNT), 행`가해운전자(1당) 연령`(2736), 열`연도`(888). 기간은2014-01~2018-12와2019-01~2019-12 두 구간. 지역 조건 없는 전국 합계와`부산`(지역차원906) 합계를 각각 조회한다. 연령행은합계·19세 이하·20-29·30-39·40-49·50-59·60-64·65세 이상·불명. 미상은 두 집단에 배분하지 않는다.
- 기존65+ 사고표는`(노인운전자) 시도 시군구별 월별 교통사고`(pattern7265)의65세 이상 가해운전자(1당사자) 조건, 행시도/시군구906:907, 열연도888, 지표사고[건]334, 동일 두 기간과 모든 페이지를 사용한다. 시군구합=시도합=전국합을 확인한다. 화면의 사망자·부상자 지표와 바꾸지 않는다.
- [행안부 연령별 인구현황](https://jumin.mois.go.kr/ageStatMonth.do):2013~2018년 각각12월, 월간, 등록구분전체, 남녀계, 연령0~100세 이상·1세 단위, 전국전체시군구CSV. 코드포함 행정구역·총인구·각1세 열·100세 이상 열이 있는cp949 CSV를`raw/population-YYYY-12.csv`로 보관한다. 외국인은 제외되며2015년1월부터재외국민포함 정의 변경이 있다. 사고연도에는 직전12월을 연결한다.

표와 필터를 확인해 내려받은 UI 파일은 별도 새 디렉터리에 출처URL·조회조건·시각·SHA256과 함께 두고 기존 파서/manifest와 호환되는지 별도 검토한다. UI 파일 확보만으로 역사 스냅샷 재현이 완료되지는 않는다.

## 4. 그림 생성과 보고서

기존 환경의 matplotlib와 한글 폰트가 있는 경우, 승인된 입력으로 다음 명령을 각각 실행한다. 새 의존성을 자동 설치하지 않는다. 그림 생성 모듈의 폰트·버전·SHA256은 각 manifest에 기록된다.

```sh
python3 cases/inshining-elderly-driver/describe.py
python3 cases/inshining-elderly-driver/describe_population.py
python3 cases/inshining-elderly-driver/describe_age.py
python3 cases/inshining-elderly-driver/run_descriptive.py
```

그림/CSV를 재생성하면 provenance 해시가 달라질 수 있으므로 runner 대사와 독립 검토를 다시 수행한다. 보고서의 실행 시각은 반복 실행마다 달라질 수 있으며 그림·수치와 구별한다. 효과 추정은 이 재현 절차에 포함되지 않는다.
