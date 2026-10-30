"""독립 HTML의 표시 수치·내장 근거·페이지 구조를 공개 검토표와 대조한다."""

import argparse
import csv
import hashlib
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

CASE = Path(__file__).resolve().parent
SOURCES = ("results/deepening/review/key_numbers.csv", "results/overnight/review/key_numbers.csv")


class OverviewParser(HTMLParser):
    """숫자와 내장 자료, 로컬 앵커 및 외부 실행 자원 참조를 수집한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.identifiers = set()
        self.anchors = []
        self.numbers = []
        self.active_number = None
        self.report_data = []
        self.in_report_data = False
        self.h1_count = 0
        self.main_count = 0
        self.lang = None
        self.viewport = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            if attrs["id"] in self.identifiers:
                raise ValueError("중복 HTML ID: " + attrs["id"])
            self.identifiers.add(attrs["id"])
        if tag == "html":
            self.lang = attrs.get("lang")
        if tag == "h1":
            self.h1_count += 1
        if tag == "main":
            self.main_count += 1
        if tag == "meta" and attrs.get("name") == "viewport":
            self.viewport = "width=device-width" in attrs.get("content", "")
        if tag == "a":
            href = attrs.get("href", "")
            if href.startswith("#"):
                self.anchors.append(href[1:])
            elif urlsplit(href).scheme != "https":
                raise ValueError("독립 HTML의 외부 근거는 HTTPS 주소여야 합니다")
            if attrs.get("target") == "_blank" and "noopener" not in attrs.get("rel", "").split():
                raise ValueError("외부 창의 관계 속성 누락")
        if tag in {"script", "img", "iframe", "audio", "video", "source", "embed", "object"}:
            if any(attrs.get(key) for key in ("src", "srcset", "data", "poster")):
                raise ValueError("외부 파일에 의존하는 실행 자원")
        if tag in {"link", "iframe", "object", "embed", "base", "form"}:
            raise ValueError("독립 설명 페이지에서 허용하지 않은 외부 자원·입력 요소")
        if tag == "script" and attrs.get("id") == "report-data":
            if attrs.get("type") != "application/json":
                raise ValueError("내장 근거의 형식이 JSON이 아님")
            self.in_report_data = True
        if "data-claim" in attrs or "data-derived" in attrs:
            if self.active_number is not None:
                raise ValueError("중첩된 수치 표시")
            self.active_number = {"tag": tag, "attrs": attrs, "text": []}

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_report_data = False
        if self.active_number is not None and self.active_number["tag"] == tag:
            self.numbers.append(self.active_number)
            self.active_number = None

    def handle_data(self, content):
        if self.in_report_data:
            self.report_data.append(content)
        if self.active_number is not None:
            self.active_number["text"].append(content)


def check(page=CASE / "project-overview.html", base=CASE):
    """표시값·메타데이터·파생식을 두 공개 검토표와 대조하며 브라우저 검사를 대신하지 않는다."""
    content = page.read_text(encoding="utf-8")
    if "@@" in content or re.search(r"@import|url\s*\(", content, re.IGNORECASE):
        raise ValueError("미완성 토큰 또는 외부 CSS 자원 참조")
    parser = OverviewParser()
    parser.feed(content)
    parser.close()
    if parser.lang != "ko" or parser.h1_count != 1 or parser.main_count != 1 or not parser.viewport:
        raise ValueError("언어·제목·본문·반응형 기본 구조 오류")
    if parser.active_number is not None or any(key not in parser.identifiers for key in parser.anchors):
        raise ValueError("미완성 수치 요소 또는 없는 문서 내 앵커")
    data = json.loads("".join(parser.report_data))
    if data.get("schema_version") != 2 or set(data.get("sources", {})) != set(SOURCES):
        raise ValueError("지원하지 않는 근거 형식·경로")
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("analysis_commit", "")):
        raise ValueError("분석 근거 커밋 형식 오류")
    reference = {}
    for path in SOURCES:
        source = base / path
        if hashlib.sha256(source.read_bytes()).hexdigest() != data["sources"][path]:
            raise ValueError("공개 검토표의 해시가 달라짐: " + path)
        with source.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["id"] in reference:
                    raise ValueError("공개 검토표 수치 ID 중복: " + row["id"])
                reference[row["id"]] = {**row, "value": float(row["value"])}
    claims = data["claims"]
    if not claims or not parser.numbers:
        raise ValueError("표시 수치·근거 누락")
    for key, claim in claims.items():
        if claim != reference.get(key) or not math.isfinite(claim["value"]):
            raise ValueError("내장 수치·출처 불일치: " + key)
    derived = data["derived"]
    for key, record in derived.items():
        if record.get("operation") != "reduction_pct":
            raise ValueError("지원하지 않는 파생식")
        baseline, model = claims[record["baseline"]]["value"], claims[record["model"]]["value"]
        if baseline <= 0 or not math.isclose(record["value"], (1 - model / baseline) * 100, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("오차 감소율 불일치: " + key)
    for number in parser.numbers:
        attrs = number["attrs"]
        digits = int(attrs.get("data-digits", "2"))
        scale = int(attrs.get("data-scale", "1"))
        sign = attrs.get("data-sign", "plain")
        if not 0 <= digits <= 6 or scale not in {1, 100} or sign not in {"plain", "signed"}:
            raise ValueError("표시 자릿수·단위·부호 설정 오류")
        if "data-claim" in attrs:
            value = claims[attrs["data-claim"]]["value"] * scale
        else:
            value = derived[attrs["data-derived"]]["value"] * scale
        expected = f"{value:.{digits}f}"
        if sign == "signed":
            expected = ("−" if value < 0 else "+") + f"{abs(value):.{digits}f}"
        if "".join(number["text"]).strip() != expected:
            raise ValueError("화면 표시 수치 불일치: " + str(attrs))
    chapters = ["problem", "data", "method", "findings", "causes", "forecast", "uses", "references"]
    if not set(chapters + ["opening", "main", "print-button", "report-data"]).issubset(parser.identifiers):
        raise ValueError("필수 장·상호작용 영역 누락")
    if not set(chapters).issubset(parser.anchors):
        raise ValueError("장 목차 링크 누락")
    return {"claims": len(claims), "displayed_numbers": len(parser.numbers), "derived": len(derived),
            "anchors": len(parser.anchors), "bytes": page.stat().st_size}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--check", action="store_true", required=True)
    cli.parse_args()
    result = check()
    print(f"HTML 근거 {result['claims']}개·표시 수치 {result['displayed_numbers']}곳·파생식 {result['derived']}개·앵커 {result['anchors']}개 대조 통과 ({result['bytes']:,}바이트)")
