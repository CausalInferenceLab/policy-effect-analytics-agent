"""실제 원자료를 포함하지 않는 사례별 수집·검사 회귀 테스트."""

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location(
    "characteristics", Path(__file__).with_name("fetch_characteristics.py")
)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def snapshot(tmp_path, source="household", overrides=None, omit=()):
    definition = fetch.SPECS[source]
    folder = tmp_path / source
    folder.mkdir(exist_ok=True)
    regions = {
        "result": [
            {
                "scrKor": gu,
                "itmId": f"001{i:03}",
                "tblId": definition["table"],
                "objVarId": "A",
                "lvl": 2,
            }
            for i, gu in enumerate(fetch.DISTRICTS, 1)
        ]
    }
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([definition["row_label"], *["2022"] * len(definition["columns"])])
    writer.writerow([definition["row_label"], *definition["columns"]])
    for gu in fetch.DISTRICTS:
        if gu not in omit:
            writer.writerow(
                [
                    gu,
                    *(overrides or {}).get(
                        gu, ["100", "30"] if source == "household" else ["10.5"]
                    ),
                ]
            )
    artifacts = {}
    for role, raw, suffix in [
        ("regions", json.dumps(regions).encode(), "json"),
        ("data", stream.getvalue().encode("utf-8-sig"), "csv"),
    ]:
        filename = f"{role}.{suffix}"
        (folder / filename).write_bytes(raw)
        artifacts[role] = {"file": filename, "sha256": fetch.digest(raw), "http_status": 200}
    fetch.dump(
        folder / "source.json",
        {
            "source_id": source,
            "table": definition["table"],
            "period": "2022",
            "license": "KOGL-1",
            "status": "downloaded",
            "artifacts": artifacts,
        },
    )
    return folder


def rows(output):
    with (output / "values.csv").open(encoding="utf-8-sig") as stream:
        return {(r["gu_name"], r["metric"]): r for r in csv.DictReader(stream)}


def test_build_retains_25_gu_and_blocks_density(tmp_path):
    snapshot(tmp_path)
    snapshot(tmp_path, "area")
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 0
    result = rows(output)
    assert len(result) == 25 * len(fetch.METRICS)
    assert result["동대문구", "single_household_pct"]["value"] == "30.0"
    assert result["동대문구", "population_density"]["status"] == "unresolved"
    assert result["동대문구", "population_density"]["value"] == ""
    quality = json.loads((output / "quality.json").read_text())
    assert quality["counts"]["verified"] == 100
    assert quality["status"] == "partial"
    replay = tmp_path / "replay"
    assert fetch.build(tmp_path, replay) == 0
    assert (output / "values.csv").read_bytes() == (replay / "values.csv").read_bytes()


def test_missing_suppressed_and_zero_denominator_remain_distinct(tmp_path):
    snapshot(tmp_path, overrides={"종로구": ["100", "x"], "중구": ["0", "0"]}, omit=["동대문구"])
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 0
    result = rows(output)
    for gu, state in [("종로구", "suppressed"), ("중구", "undefined"), ("동대문구", "unresolved")]:
        assert result[gu, "single_household_pct"]["status"] == state
        assert result[gu, "single_household_pct"]["value"] == ""
    assert result["중구", "households"]["value"] == "0"


@pytest.mark.parametrize("values", [["10", "11"], ["-1", "0"], ["1.5", "0"], ["NaN", "0"]])
def test_invalid_households_fail_without_discarding_other_gu(tmp_path, values):
    snapshot(tmp_path, overrides={"종로구": values})
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 1
    result = rows(output)
    assert result["종로구", "households"]["value"] == ""
    assert result["중구", "households"]["status"] == "verified"


def test_tampered_source_fails_but_independent_source_survives(tmp_path):
    folder = snapshot(tmp_path)
    snapshot(tmp_path, "area")
    with (folder / "data.csv").open("ab") as stream:
        stream.write(b"changed")
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 1
    result = rows(output)
    assert result["동대문구", "households"]["value"] == ""
    assert result["동대문구", "area_km2"]["status"] == "verified"


@pytest.mark.parametrize(
    "raw",
    [
        "<html>error</html>",
        "동별,2023,2023\n동별,일반가구 (가구),1인 가구 (가구)\n중구,100,30",
        "동별,2022,2022\n동별,일반가구 (가구),1인 가구 (가구)\n중구,100,30\n중구,100,30",
    ],
)
def test_wrong_download_is_rejected(raw):
    with pytest.raises(fetch.DataError):
        fetch.parse_csv(raw.encode(), fetch.SPECS["household"])


def test_malformed_region_response():
    with pytest.raises(fetch.DataError):
        fetch.region_map(["error"], fetch.SPECS["household"]["table"])


files = __import__("characteristics_files")


def market_fixture():
    result = [
        {"D": "서울시 자치구별 전통시장 현황(2022년 상반기)"},
        {"E": "자치구", "F": "연번", "G": "시장명", "H": "형태", "I": "신주소\n(구주소)"},
    ]
    for gu in fetch.DISTRICTS:
        result += [
            {"E": gu, "F": "계", "G": "2"},
            {"E": gu, "F": "1", "G": "예시시장", "H": "골목형", "I": f"{gu} 예시로 1"},
            {"E": gu, "F": "2", "G": "예시상점가", "H": "상점가", "I": f"{gu} 예시로 2"},
        ]
    return result


def test_market_excludes_shopping_street_and_keeps_25_gu():
    result, _, definition = files.validate_market(market_fixture(), fetch.DISTRICTS)
    assert len(result) == 25
    assert definition["listed"] == 50
    assert all(r["markets"] == (1, "verified", "") for r in result.values())


def test_market_same_address_holds_count_but_not_presence():
    data = market_fixture()
    data[4].update(H="건물형", I=data[3]["I"])
    result, _, _ = files.validate_market(data, fetch.DISTRICTS)
    assert result["종로구"]["markets"][0:2] == (None, "unresolved")
    assert result["종로구"]["market_present"] == (1, "verified", "")
    assert result["중구"]["markets"][1] == "verified"


@pytest.mark.parametrize("change", ["year", "total", "unknown_type", "duplicate_name"])
def test_market_rejects_wrong_period_scope_or_list(change):
    data = market_fixture()
    if change == "year":
        data[0]["D"] = "서울시 자치구별 전통시장 현황(2023년 상반기)"
    elif change == "total":
        data[2]["G"] = "3"
    elif change == "unknown_type":
        data[3]["H"] = "새로운분류"
    else:
        data[4]["G"] = data[3]["G"]
    with pytest.raises(ValueError):
        files.validate_market(data, fetch.DISTRICTS)


def test_market_alias_requires_address_evidence():
    data = market_fixture()
    for row in data:
        if row.get("E") == "동대문구":
            row["E"] = "동대문"
    result, _, _ = files.validate_market(data, fetch.DISTRICTS)
    assert "동대문구" in result
    next(r for r in data if r.get("E") == "동대문" and r["F"] == "1")["I"] = "다른구 주소"
    with pytest.raises(ValueError, match="주소 근거"):
        files.validate_market(data, fetch.DISTRICTS)


def zip_bytes(name, raw):
    from zipfile import ZipFile

    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr(name, raw)
    return stream.getvalue()


def store_fixture(change=None):
    columns = [
        "기준_년분기_코드",
        "상권_구분_코드",
        "상권_구분_코드_명",
        "상권_코드",
        "서비스_업종_코드",
        "점포_수",
        "유사_업종_점포_수",
        "프랜차이즈_점포_수",
    ]
    data = [
        [period, "A", "골목상권", "3110001", industry, "2", "3", "1"]
        for period in ["20221", "20222", "20223", "20224"]
        for industry in files.INDUSTRIES
    ]
    if change == "duplicate":
        data.append(data[-1])
    elif change == "arithmetic":
        data[-1][-2] = "2"
    elif change == "missing":
        data.append(["20224", "A", "골목상권", "3110002", files.INDUSTRIES[0], "0", "0", "0"])
    elif change == "quarter":
        data = [r for r in data if r[0] != "20224"]
    stream = io.StringIO()
    w = csv.writer(stream)
    w.writerow(columns)
    w.writerows(data)
    return zip_bytes(
        "서울시_상권분석서비스(점포-상권)_2022년.csv", stream.getvalue().encode("cp949")
    )


def test_store_missing_pairs_are_not_filled_with_zero():
    selected, check = files.inspect_stores(store_fixture("missing"))
    assert len(selected) == 5
    assert sum(r["total"] for r in selected) == 12
    assert check["missing_area_industry_pairs"] == 3


@pytest.mark.parametrize("change", ["duplicate", "arithmetic", "quarter"])
def test_store_errors_block_aggregation(change):
    with pytest.raises(ValueError):
        files.inspect_stores(store_fixture(change))


def test_file_selector_requires_exact_historical_filename():
    spec = files.FILE_SPECS["market"]
    form = '<form name="frmFile"><input name="infId" value="OA-1176"><input name="infSeq" value="3"></form>'
    html = form + f'''<span title="{spec["filename"]}" onclick="downloadFile('6')"></span>'''
    assert files.file_query(html, spec)["seq"] == "6"
    with pytest.raises(ValueError):
        files.file_query(html.replace("2022.", "2025."), spec)


def test_build_store_snapshot_stays_unresolved_even_with_valid_numbers(tmp_path):
    snapshot(tmp_path)
    folder = tmp_path / "stores"
    folder.mkdir()
    raw = store_fixture()
    (folder / "data.zip").write_bytes(raw)
    spec = files.FILE_SPECS["stores"]
    fetch.dump(
        folder / "source.json",
        {
            "source_id": "stores",
            "dataset_id": spec["id"],
            "period": spec["period"],
            "license": "KOGL-1",
            "original_filename": spec["filename"],
            "status": "downloaded",
            "artifacts": {
                "data": {"file": "data.zip", "sha256": fetch.digest(raw), "http_status": 200}
            },
        },
    )
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 0
    result = rows(output)
    assert result["동대문구", "food_stores"]["value"] == ""
    assert result["동대문구", "food_stores"]["status"] == "unresolved"
    assert result["동대문구", "households"]["status"] == "verified"


@pytest.mark.parametrize("bad_reference", [False, True])
def test_xlsx_reader_recounts_cached_totals(bad_reference):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = ET.Element("worksheet", xmlns=ns)
    data = ET.SubElement(sheet, "sheetData")
    for i, source in enumerate(market_fixture(), 1):
        row = ET.SubElement(data, "row", r=str(i))
        for col, value in source.items():
            cell = ET.SubElement(row, "c", r=f"{col}{i}", t="inlineStr")
            if col == "G" and source.get("F") == "계":
                cell.attrib.pop("t")
                ET.SubElement(cell, "f").text = "COUNTIF(...)"
                ET.SubElement(cell, "v").text = value
            else:
                ET.SubElement(ET.SubElement(cell, "is"), "t").text = value
    if bad_reference:
        first = data.find("row/c")
        first.attrib["t"] = "s"
        ET.SubElement(first, "v").text = "-1"
    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="시장목록" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}"/>')
        z.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))
    if bad_reference:
        with pytest.raises(ValueError, match="공유 문자열"):
            files.inspect_market(stream.getvalue(), fetch.DISTRICTS)
        return
    result, _, _ = files.inspect_market(stream.getvalue(), fetch.DISTRICTS)
    assert result["동대문구"]["markets"][0] == 1


def territory_fixture(duplicate=False):
    import struct
    from zipfile import ZipFile

    fields = [("TRDAR_SE_C", 1), ("TRDAR_CD", 10), ("SIGNGU_CD", 5), ("SIGNGU_CD_", 40)]
    width = 1 + sum(n for _, n in fields)
    header_size = 33 + 32 * len(fields)
    records = []
    for i, gu in enumerate(fetch.DISTRICTS):
        code = "3110000" if duplicate else str(3110000 + i)
        values = ["A", code, str(11110 + i), gu]
        records.append(
            b" "
            + b"".join(v.encode().ljust(n, b" ") for v, (_, n) in zip(values, fields, strict=True))
        )
    header = bytearray(32)
    header[0] = 3
    struct.pack_into("<IHH", header, 4, len(records), header_size, width)
    for name, size in fields:
        descriptor = bytearray(32)
        descriptor[: len(name)] = name.encode()
        descriptor[11] = ord("C")
        descriptor[16] = size
        header.extend(descriptor)
    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr("areas.dbf", bytes(header) + b"\r" + b"".join(records) + b"\x1a")
        z.writestr("areas.cpg", "UTF-8")
    return stream.getvalue()


def test_territory_code_match_does_not_verify_version():
    mapping, check = files.inspect_territory(territory_fixture(), fetch.DISTRICTS)
    assert len(mapping) == 25
    assert check["version_status"] == "unresolved"


def test_territory_multiple_gu_for_same_area_fails():
    with pytest.raises(ValueError, match="중복/복수 연결"):
        files.inspect_territory(territory_fixture(duplicate=True), fetch.DISTRICTS)


pop = __import__("characteristics_population")


def population_fixture(change=None):
    mapping = {gu: f"{11110 + i}00000" for i, gu in enumerate(fetch.DISTRICTS)}
    ages = [0] * 101
    ages[64], ages[65], ages[99], ages[100] = 7, 3, 2, 1
    district_values = [sum(ages), sum(ages), *ages]
    data = [["서울특별시  (1100000000)", *[n * 25 for n in district_values]]]
    data += [[f"서울특별시 {gu} ({code})", *district_values] for gu, code in mapping.items()]
    header = pop.population_header()
    if change == "year":
        header = [h.replace("2022", "2023") for h in header]
    elif change == "top_age":
        header[-1] = "2022년12월_계_100세"
    elif change == "age_sum":
        data[1][-1] += 1
    elif change == "city_sum":
        data[0][1] += 1
        data[0][2] += 1
        data[0][3] += 1
    elif change == "duplicate":
        data.append(data[1])
    elif change == "missing_gu":
        data.pop()
    elif change == "invalid_number":
        data[1][3] = "x"
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(data)
    return stream.getvalue().encode("cp949"), mapping


def test_population_65_boundary_top_age_and_city_reconciliation():
    raw, mapping = population_fixture()
    result, check = pop.inspect_population(raw, mapping)
    assert result["동대문구"]["population"] == 13
    assert result["동대문구"]["population_65plus"] == 6  # 64세 제외, 100세 이상 포함
    assert result["동대문구"]["older_population_pct"] == pytest.approx(100 * 6 / 13)
    assert check["seoul_population"] == 325


@pytest.mark.parametrize(
    "change",
    ["year", "top_age", "age_sum", "city_sum", "duplicate", "missing_gu", "invalid_number"],
)
def test_population_invalid_input_never_passes(change):
    raw, mapping = population_fixture(change)
    with pytest.raises(ValueError):
        pop.inspect_population(raw, mapping)


def population_form(resident_type=""):
    fields = {
        k: v for k, v in pop.QUERY.items() if k not in {"sum", "searchYearMonth", "tableChart"}
    }
    fields.update(category="month", sltUndefType=resident_type)
    return (
        '<form id="formXlsDown">'
        + "".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in fields.items())
        + "</form><script>downloadCsvAge.do</script>"
    )


def test_population_query_requires_all_resident_types():
    assert pop.download_query(population_form())["sum"] == "sum"
    with pytest.raises(ValueError):
        pop.download_query(population_form("Y"))


def population_snapshot(tmp_path):
    raw, mapping = population_fixture()
    folder = tmp_path / "population"
    folder.mkdir()
    regions = json.dumps(
        {
            "locations": [
                dict(sidonm="서울특별시", levels="2", sikunkunm=gu, hangkikcd=code)
                for gu, code in mapping.items()
            ]
        }
    ).encode()
    form = population_form()
    artifacts = {}
    for role, blob, suffix in [
        ("regions", regions, "json"),
        ("page", form.encode(), "html"),
        ("data", raw, "csv"),
    ]:
        filename = f"{role}.{suffix}"
        (folder / filename).write_bytes(blob)
        artifacts[role] = dict(file=filename, sha256=fetch.digest(blob), http_status=200)
    artifacts["data"]["query"] = pop.download_query(form)
    fetch.dump(
        folder / "source.json",
        dict(
            source_id="population",
            period="2022-12",
            url=pop.PAGE,
            license="other",
            license_notes="이용허락범위 제한 없음",
            status="downloaded",
            artifacts=artifacts,
        ),
    )
    return folder


def test_population_only_build_keeps_density_on_hold(tmp_path):
    population_snapshot(tmp_path)
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 0
    result = rows(output)
    assert result["동대문구", "population"]["status"] == "verified"
    assert (
        result["동대문구", "population"]["source_gu_code_system"]
        == "행안부 주민등록 행정기관 코드 10자리"
    )
    assert result["동대문구", "population_density"]["status"] == "unresolved"
    assert result["동대문구", "population_density"]["value"] == ""


def test_population_tampering_preserves_independent_households(tmp_path):
    folder = population_snapshot(tmp_path)
    snapshot(tmp_path)
    (folder / "data.csv").write_bytes(b"changed")
    output = tmp_path / "out"
    assert fetch.build(tmp_path, output) == 1
    result = rows(output)
    assert result["동대문구", "population"]["value"] == ""
    assert result["동대문구", "households"]["status"] == "verified"


def test_malformed_thousands_separator_rejected():
    with pytest.raises(fetch.DataError):
        fetch.numeric("1,2")


def test_dbf_header_outside_file_rejected():
    import struct
    from zipfile import ZipFile

    with ZipFile(io.BytesIO(territory_fixture())) as z:
        raw = bytearray(z.read("areas.dbf"))
    struct.pack_into("<IHH", raw, 4, 0, 65025, 56)
    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr("areas.dbf", raw)
        z.writestr("areas.cpg", "UTF-8")
    with pytest.raises(ValueError, match="헤더 불일치"):
        files.inspect_territory(stream.getvalue(), fetch.DISTRICTS)
