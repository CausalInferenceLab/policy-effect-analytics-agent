"""기상청 서울 관측 달력을 수집하며 강수 미표기와 숫자 0을 구별한다."""

from __future__ import annotations

import calendar
import json
import re
from html.parser import HTMLParser

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional_data import OUT, RAW
from .topis import session

MANIFEST = CASE / "directional-weather-sources.json"


class CalendarTable(HTMLParser):
    """기상청 달력 표의 날짜 행과 관측 행만 읽어 화면의 다른 표를 제외한다."""

    def __init__(self):
        super().__init__()
        self.inside = False
        self.in_cell = False
        self.rows = []
        self.row = []
        self.cell = []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and "table-cal" in dict(attrs).get("class", "").split():
            if self.rows:
                raise ValueError("달력 표가 두 개입니다")
            self.inside = True
        if self.inside and tag == "tr":
            self.row = []
        if self.inside and tag == "td":
            self.cell = []
            self.in_cell = True

    def handle_data(self, data):
        if self.inside and self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.inside and tag == "td":
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.in_cell = False
        if self.inside and tag == "tr" and self.row:
            self.rows.append(self.row)
        if self.inside and tag == "table":
            self.inside = False


def parse_calendar(html, month, obs=1):
    year, mon = map(int, month.split("-"))
    heading = re.search(r'cmp-table-topinfo[^>]*>(.*?)</p>', html, re.S)
    heading = re.sub("<[^>]+>", " ", heading[1]) if heading else ""
    if "서울" not in heading or not re.search(fr"{year}년\s*{mon}월", heading):
        raise ValueError("요청 관측소·연월과 날씨달력 제목이 다릅니다")
    parser = CalendarTable()
    parser.feed(html)
    if not parser.rows or len(parser.rows) % 2:
        raise ValueError("날씨달력 날짜/관측 행 구성 변경")
    records = []
    fields = {"평균기온": "temperature_mean_c", "최고기온": "temperature_max_c",
              "최저기온": "temperature_min_c", "일강수량": "precipitation_mm"}
    for i in range(0, len(parser.rows), 2):
        dates, values = parser.rows[i:i + 2]
        if len(dates) != 7 or len(values) != 7:
            raise ValueError("날씨달력 요일 열 변경")
        for weekday, (label, value) in enumerate(zip(dates, values, strict=True)):
            if not label:
                continue
            if not re.fullmatch(r"\d{1,2}일", label):
                raise ValueError(f"날짜 표기 변경: {label}")
            date = pd.Timestamp(year=year, month=mon, day=int(label[:-1]))
            if (date.dayofweek + 1) % 7 != weekday:
                raise ValueError("날짜와 요일 열 불일치")
            row = {"date": str(date.date()), "station": 108}
            if obs == 9:
                row["phenomena_record"] = value
            else:
                for name, key in fields.items():
                    match = re.search(re.escape(name) + r"\s*:\s*(-?\d+(?:\.\d+)?|-)(℃|mm)?", value)
                    if not match:
                        raise ValueError(f"관측 필드 누락: {date.date()} {name}")
                    row[key] = np.nan if match[1] == "-" else float(match[1])
                    if key == "precipitation_mm":
                        row["precipitation_raw"] = match[1]
                p = row["precipitation_mm"]
                if pd.notna(p) and p < 0:
                    raise ValueError("음수 일강수량")
                t = row["temperature_mean_c"]
                if pd.notna(t) and not -70 <= t <= 60:
                    raise ValueError("예상 범위 밖의 기온")
            records.append(row)
    frame = pd.DataFrame(records)
    if len(frame) != calendar.monthrange(year, mon)[1] or frame.date.duplicated().any():
        raise ValueError("달력의 날짜 누락·중복")
    return frame


def collect_weather():
    cfg = read_yaml("directional_config.yaml")
    folder = RAW / "weather"
    folder.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    existing = json.loads(MANIFEST.read_text())["files"] if MANIFEST.exists() else []
    lookup = {(x["month"], x["obs"]): x for x in existing}
    frames = []
    with session() as client:
        for month in cfg["months"]:
            pieces = []
            for obs in (1, 9):
                path = folder / f"seoul108_{month}_obs{obs}.html"
                if (month, obs) in lookup:
                    entry = lookup[(month, obs)]
                    if not path.exists() or sha256(path) != entry["sha256"]:
                        raise ValueError("기상 원본 해시 변경")
                    html = path.read_text(encoding="utf-8")
                else:
                    if path.exists():
                        raise ValueError("출처 없는 기존 기상 파일을 덮어쓰지 않습니다")
                    params = {"stn": 108, "yy": int(month[:4]), "mm": int(month[-2:]), "obs": obs}
                    response = client.get(cfg["weather"]["source"], params=params, timeout=(15, 60))
                    response.raise_for_status()
                    html = response.text
                    parse_calendar(html, month, obs)
                    path.write_text(html, encoding="utf-8")
                    entry = {"month": month, "obs": obs, "source": cfg["weather"]["source"], "url": response.url,
                             "path": str(path.relative_to(CASE)), "sha256": sha256(path), "bytes": path.stat().st_size,
                             "retrieved_at": utcnow()}
                    lookup[(month, obs)] = entry
                    write_json(MANIFEST, {"description": "기상청 서울108 일별 숫자·일기현상 달력 원본. '-'는 결측으로 보존.",
                                          "files": sorted(lookup.values(), key=lambda x: (x["month"], x["obs"]))})
                pieces.append(parse_calendar(html, month, obs))
            frames.append(pieces[0].merge(pieces[1], on=["date", "station"], validate="one_to_one"))
            print(f"기상: {month} {len(pieces[0])}일", flush=True)
    result = pd.concat(frames, ignore_index=True)
    result["rain_group"] = np.select([result.precipitation_mm.isna(), result.precipitation_mm.ge(cfg["weather"]["rain_threshold_mm"])],
                                     ["dash_unknown", "recorded_ge1mm"], default="recorded_lt1mm")
    result["rain_phenomenon_recorded"] = result.phenomena_record.str.contains(r"비|소나기|눈|우박", regex=True, na=False)
    result["weekday"] = pd.to_datetime(result.date).dt.dayofweek
    result["temperature_bin"] = pd.cut(result.temperature_mean_c, [-np.inf, *cfg["weather"]["temperature_bins_c"], np.inf],
                                       right=False, labels=["lt20", "20to25", "25to30", "ge30"]).astype(str)
    result.to_csv(OUT / "weather_daily.csv", index=False)
    write_json(OUT / "weather_quality.json", {"days": len(result), "numeric_precipitation_days": int(result.precipitation_mm.notna().sum()),
                                             "dash_unknown_days": int(result.precipitation_mm.isna().sum()),
                                             "temperature_missing_days": int(result.temperature_mean_c.isna().sum()),
                                             "source_manifest_sha256": sha256(MANIFEST), "parser_sha256": sha256(__file__),
                                             "note": "서울108 일자료. '-'를 무강수로 확정하지 않고 별도 층으로 보존. 일기현상은 보조 기록이며 강남 저녁의 비를 직접 측정하지 않음."})
