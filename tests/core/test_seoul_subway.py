"""서울 지하철 역별 승하차 수집기 — 네트워크 없이 파일 목록·CSV 파싱 확인."""

from core.adapters.seoul_subway import SeoulSubwayDailyAdapter, months, parse_file_list, read_month

HTML = (
    '<span title="CARD_SUBWAY_MONTH_202508.csv" onclick="javascript:downloadFile(\'145\');">x</span>'
    '<span title="CARD_SUBWAY_MONTH_202509.csv" onclick="javascript:downloadFile(\'146\');">x</span>'
)
CSV = '﻿"사용일자","노선명","역명","승차총승객수","하차총승객수","등록일자"\n"20250801","경부선","화서","11616","11332","20250804",""\n'


class FakeResp:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.posts = []

    def get(self, url, timeout):
        return FakeResp(text=HTML)

    def post(self, url, data, timeout):
        self.posts.append(data["seq"])
        return FakeResp(content=CSV.encode("utf-8"))


def test_parse_and_read():
    assert parse_file_list(HTML) == {"202508": "145", "202509": "146"}
    d = read_month(CSV.encode("utf-8"))
    assert list(d.columns) == ["date", "line", "station", "on", "off"] and d.on.iloc[0] == 11616
    d2 = read_month(CSV.replace("﻿", "").encode("cp949"))
    assert d2.station.iloc[0] == "화서"
    assert months("2025-11", "2026-02") == ["202511", "202512", "202601", "202602"]


def test_fetch_uses_cache_and_skips_missing(tmp_path):
    s = FakeSession()
    ad = SeoulSubwayDailyAdapter(session=s, pause=0)
    df = ad.fetch("2025-08", "2025-10", cache_dir=tmp_path)
    assert s.posts == ["145", "146"] and len(df) == 2  # 2025-10 은 목록에 없어 건너뜀
    ad.fetch("2025-08", "2025-09", cache_dir=tmp_path)
    assert s.posts == ["145", "146"]  # 두 번째는 캐시 사용
