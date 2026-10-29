"""공개 API 명세의 표와 과거 샘플을 해시 검증 후 비교한다."""

import csv
import json
import re
from html.parser import HTMLParser

from .common import CASE, read_yaml, sha256, utcnow, write_json

CONFIG = CASE / "deepening_definitions_config.yaml"
OUT = CASE / "results/deepening/definitions"


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is not None:
                raise ValueError("nested tables require explicit handling")
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def normalized(value):
    return value.replace("_", "").lower()


def indexed(fields):
    result = {}
    for field in fields:
        key = normalized(field)
        if key in result:
            raise ValueError(f"ambiguous normalized field: {field}")
        result[key] = field
    return result


def extract(html, locked_year):
    parser = Tables()
    parser.feed(html)
    outputs = [t for t in parser.tables if t and t[0] == ["변수명", "변수 설명", "값 설명", "샘플데이터"]]
    requests = [t for t in parser.tables if t and len(t[0]) == 7 and t[0][0] == "변수명"]
    samples = [r[1] for t in parser.tables for r in t if len(r) == 2 and r[0] == "샘플 미리보기"]
    if len(outputs) != 1 or len(requests) != 1 or len(samples) != 1:
        raise ValueError("expected exactly one request, output and sample table")
    if any(len(r) != 4 for r in outputs[0]) or any(len(r) != 7 for r in requests[0]):
        raise ValueError("API metadata row width changed")
    text = samples[0]
    sample = json.loads(text[text.index("{"):text.rindex("}") + 1])
    date = str(sample.get("stdrDe", ""))
    if not re.fullmatch(r"\d{8}", date) or int(date[:4]) >= locked_year:
        raise ValueError("sample date is absent or falls in locked years")
    indexed(sample)
    indexed(r[0] for r in outputs[0][1:])
    return requests[0][1:], outputs[0][1:], sample


def save_csv(name, rows):
    if not rows:
        raise ValueError(f"empty metadata output: {name}")
    with (OUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run():
    cfg = read_yaml(CONFIG)
    OUT.mkdir(parents=True, exist_ok=True)
    field_rows, request_rows, sample_rows, summaries, inputs = [], [], [], [], []
    for source in cfg["sources"]:
        entries = json.loads((CASE / source["manifest"]).read_text())["files"]
        entry, = [e for e in entries if e["id"] == source["id"]]
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"metadata source hash changed: {source['id']}")
        requests, fields, sample = extract(path.read_text(encoding="utf-8"), cfg["locked_year"])
        sample_index = indexed(sample)
        documented_index = indexed(r[0] for r in fields)
        for name, description, values, example in fields:
            key = sample_index.get(normalized(name))
            field_rows.append(dict(source=source["id"], field=name, description=description,
                                   value_description=values, inline_sample=example,
                                   sample_field=key or "", in_json_sample=key is not None))
        for name, kind, required, size, description, values, example in requests:
            request_rows.append(dict(source=source["id"], field=name, type=kind, required=required,
                                     size=size, description=description, value_description=values,
                                     example=example))
        for key in cfg["sample_value_allowlist"]:
            if key in sample:
                sample_rows.append(dict(source=source["id"], sample_date=sample["stdrDe"],
                                        field=key, json_value=json.dumps(sample[key], ensure_ascii=False),
                                        status="illustration_not_verified_measurement_definition"))
        summaries.append(dict(source=source["id"], documented_fields=len(fields),
                              sample_fields=len(sample), sample_date=sample["stdrDe"],
                              sample_only_fields=[v for k, v in sample_index.items() if k not in documented_index],
                              documentation_only_fields=[v for k, v in documented_index.items() if k not in sample_index],
                              output_fields_with_value_description=sum(bool(r[2]) for r in fields),
                              output_fields_with_inline_sample=sum(bool(r[3]) for r in fields)))
        inputs.append({k: entry[k] for k in ["id", "url", "path", "sha256"]})
    save_csv("fields.csv", field_rows)
    save_csv("request_parameters.csv", request_rows)
    save_csv("selected_sample_values.csv", sample_rows)
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), configuration=cfg,
               inputs=inputs, configuration_sha256=sha256(CONFIG), code_sha256=sha256(__file__),
               sources=summaries, outputs={p.name: sha256(p) for p in sorted(OUT.glob("*.csv"))}))
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
