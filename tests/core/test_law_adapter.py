import pandas as pd

from core.adapters.law import parse_ordinance_xml, tidy

# 법제처 자치법규 검색 응답 형식 (필드 구조만 재현한 최소 예시)
XML = """<?xml version="1.0" encoding="UTF-8"?><OrdinSearch><target>ordin</target><totalCnt>2</totalCnt>
<law id="1"><자치법규ID>1</자치법규ID><자치법규명>가 지역화폐 조례</자치법규명><지자체기관명>경기도 가군</지자체기관명>
<제개정구분명>제정</제개정구분명><공포일자>20190101</공포일자><시행일자>20190101</시행일자></law>
<law id="2"><자치법규ID>2</자치법규ID><자치법규명>나 지역사랑상품권 조례</자치법규명><지자체기관명>강원도 나군</지자체기관명>
<제개정구분명>일부개정</제개정구분명><공포일자>20210301</공포일자><시행일자>20210301</시행일자></law></OrdinSearch>"""


def test_parse_and_tidy():
    rows, total = parse_ordinance_xml(XML)
    assert total == 2 and rows[0]["지자체기관명"] == "경기도 가군"
    df = tidy(pd.DataFrame(rows + rows))  # 중복 제거
    assert len(df) == 2 and df["year"].tolist() == [2019, 2021]
