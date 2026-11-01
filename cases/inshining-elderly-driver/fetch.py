"""Check historical raw inputs offline, or explicitly acquire fresh public age XML.

Default: no network and no writes. Fresh age acquisition is intentionally separate
from replay of the reviewed historical snapshots; it never grants source review.
TAAS 65+ and MOIS acquisition/cleaning remain in taas.py and population.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import population
import taas
from describe_age import AGE_LABELS, load_age_sources, parse_age_xml

HERE = Path(__file__).resolve().parent
BATCHES = ((2014, 2018), (2019, 2019))
DIMENSIONS = {
    2736: ("가해운전자(1당) 연령대", "ELE_NAME_9"),
    888: ("연도", "STD_YEAR"),
    906: ("시도", "ELE_NAME"),
}
PATTERN_TEMPLATE = (
    ':row_list="906:*907",:col_list="888:2736",:mea_list="334:335:701:*336:*702:*337",'
    ':condition="",:pcondition="",:incondition="",:filter="",:agg_function="SUM",'
    ':orgdata="",:decimalpoint="",:aggDecimalpoint="",:enumerate="",:mode="A",'
    ':chartdatatype="ALL_NOAGG",:pattern_id="7125",'
    ':agg_info="D906;@T;@합계;|D907;@T;@합계;|D888;@T;@합계;|2736;@T;@합계;|",'
    ':meapos="R",:meaonlyagg="F",:agg_form="S",:agg_position="",:pagenum="1",'
    ':pattern_name="시도 시군구별 가해운전자 연령대별 교통사고",'
    ':subject_name="251_분석통계 기본계획(경찰청 사고일반) ",'
    ':SetSchedule="NONE",:subject_id="131",:layout="0"'
)
PUBLIC_TAGS = {"PAGE", "TITLE", "GRID", "GRIDCOMMENT", "ERROR"}
SENSITIVE = re.compile(
    rb"<!DOCTYPE|<!ENTITY|JSESSIONID|clientIP\s*[=:]|wasIP\s*[=:]|"
    rb"clientEmail\s*[=:]|rsaPublicKey|[,:]lic=|[/\\][^<>\s]*\.err\b",
    re.IGNORECASE,
)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def build_age_parameters(pattern, start, end, area):
    """Fail closed if the reviewed public pattern, selectors or filters change."""
    if (
        (start, end) not in BATCHES
        or area not in ("national", "busan")
        or pattern.get("PatternId") != 7125
        or pattern.get("SubjectId") != 131
        or pattern.get("Parameter") != PATTERN_TEMPLATE
    ):
        raise ValueError("Public age pattern changed; source review is required")
    values = {
        "row_list": "2736",
        "col_list": "888",
        "mea_list": "334",
        "condition": "" if area == "national" else "D906@|@P01 S01 #OTE![부산]!#;|;",
        "agg_info": "D2736;@T;@합계;|D888;@T;@합계;|",
        "pagenum": "1",
    }
    result = pattern["Parameter"]
    for key, value in values.items():
        result, count = re.subn(":" + key + r'="[^"]*"', ":" + key + '="' + value + '"', result)
        if count != 1:
            raise ValueError("Public parameter missing or duplicated")
    return result + f',:vcondition="D1443@|@P08 S01 T111 #OTE![{start}01]!# #OTE![{end}12]!#;|;"'


def project_age_xml(raw, years):
    """Persist only validated public table subtrees, never runtime containers."""
    if re.search(rb"<!DOCTYPE|<!ENTITY", raw, re.IGNORECASE):
        raise ValueError("XML declarations outside the public projection")
    try:
        original = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("Invalid public XML") from error
    if original.tag != "OCTAGONDATA":
        raise ValueError("Unexpected public XML root")
    public = ET.Element(original.tag)
    for node in original:
        if node.tag in PUBLIC_TAGS:
            public.append(node)
    projected = ET.tostring(public, encoding="utf-8", xml_declaration=True)
    if SENSITIVE.search(projected):
        raise ValueError("Unsafe value inside public projection")
    parse_age_xml(projected, years)
    return projected


def _metadata(client):
    dimensions = client.metadata("getDimensionItems", subjectId=131)
    selected = []
    for identifier, (label, physical) in DIMENSIONS.items():
        matches = [r for r in dimensions if r.get("DimAttrId") == identifier]
        if (
            len(matches) != 1
            or matches[0].get("LogColName") != label
            or matches[0].get("PhyColName") != physical
        ):
            raise ValueError("Public dimension definitions changed")
        selected.append({"DimAttrId": identifier, "LogColName": label, "PhyColName": physical})
    measures = client.metadata("getMeasureItems", subjectId=131)
    measure = {
        "MeaId": 334,
        "SubjectId": 131,
        "LogColName": "사고[건]",
        "PhyColName": "ACC_CNT",
        "AggFunc": "SUM",
    }
    matches = [r for r in measures if r.get("MeaId") == 334]
    if len(matches) != 1 or any(matches[0].get(k) != v for k, v in measure.items()):
        raise ValueError("Public crash-count measure changed")
    members = {}
    for identifier, expected in (
        (2736, set(AGE_LABELS) - {"합계"}),
        (888, {str(y) for y in range(2014, 2020)}),
    ):
        rows = client.metadata(
            "getTopElements", subjectId=131, dimAttrId=identifier, pageNo=1, rowSize=100
        )
        pages = [r for r in rows if "TotalPage" in r]
        if len(pages) != 1 or pages[0].get("TotalPage") != 1 or pages[0].get("PageNo") != 1:
            raise ValueError("Public metadata pagination changed")
        values = [r for r in rows if "ElementCode" in r]
        codes = [r["ElementCode"] for r in values]
        if (
            len(codes) != len(set(codes))
            or not expected <= set(codes)
            or (identifier == 2736 and set(codes) != expected)
            or any(r.get("ElementName") != r["ElementCode"] for r in values)
        ):
            raise ValueError("Public age boundaries or requested years changed")
        members[str(identifier)] = [
            {"ElementCode": r["ElementCode"], "ElementName": r["ElementName"]}
            for r in values
            if r["ElementCode"] in expected
        ]
    return {
        "dimensions": selected,
        "measure": measure,
        "members": members,
        "endpoint": taas.BASE + "/OBIP25/ajax/procAnalysis.eos",
        "requests": [
            {"pmode": "getDimensionItems", "subjectId": 131},
            {"pmode": "getMeasureItems", "subjectId": 131},
            *[
                {
                    "pmode": "getTopElements",
                    "subjectId": 131,
                    "dimAttrId": identifier,
                    "pageNo": 1,
                    "rowSize": 100,
                }
                for identifier in (2736, 888)
            ],
        ],
    }


def _new_directory(path):
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError("Output must be a NEW directory; existing paths are never replaced")
    if not path.parent.is_dir():
        raise ValueError("Output parent must already exist")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Resolve symlink parents before selecting a new output directory")
    return path


def download_age(output_dir, client=None):
    """Acquire and validate all four responses in memory before creating output."""
    output = _new_directory(output_dir)
    client = taas.PublicClient() if client is None else client
    sources, buffers, metadata_records = [], {}, []
    for start, end in BATCHES:
        _, handshake = client.session(start, end)
        metadata = _metadata(client)
        pattern = client.metadata("loadPattern", patternId=7125)
        metadata_records.append(
            {
                "years": list(range(start, end + 1)),
                **metadata,
                "pattern": {
                    "PatternId": 7125,
                    "SubjectId": 131,
                    "public_parameter_template": PATTERN_TEMPLATE,
                },
            }
        )
        for area in ("national", "busan"):
            params = build_age_parameters(pattern, start, end, area)
            raw = client.query(params, handshake)
            projected = project_age_xml(raw, range(start, end + 1))
            filename = f"source-query-{area}-{start}-{end}.xml"
            buffers[filename] = projected
            sources.append(
                {
                    "file": filename,
                    "area": area,
                    "years": list(range(start, end + 1)),
                    "sha256": sha256(projected),
                    "bytes": len(projected),
                    "original_response_sha256": sha256(raw),
                    "original_response_saved": False,
                    "public_parameters": params,
                    "endpoint": taas.BASE + "/OBIP25/servlet/OctagonProxyServlet",
                    "method": "POST",
                    "retrieved_at_utc": datetime.now(UTC).isoformat(),
                }
            )
    manifest = {
        "schema_version": 1,
        "acquisition_kind": "fresh_age_public_query",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "review_status": "pending",
        "analysis_approved": False,
        "publication_approved": False,
        "historical_byte_identity_promised": False,
        "command": "python3 cases/inshining-elderly-driver/fetch.py --download --age-only --output-dir NEW_DIR",
        "versions": {"python": sys.version.split()[0]},
        "code_sha256": {
            p.name: sha256(p.read_bytes())
            for p in (Path(__file__), HERE / "taas.py", HERE / "describe_age.py")
        },
        "snapshot_scope": "Serialized public PAGE/TITLE/GRID/GRIDCOMMENT/ERROR subtrees only; "
        "MESSAGE, runtime identifiers and other top-level containers excluded.",
        "metadata": metadata_records,
        "sources": sources,
        "limits": [
            "Fresh acquisition is not historical snapshot replay; source values or bytes may change.",
            "All four projected responses passed age partition/year/total validation before persistence.",
            "The normal anonymous public client keeps cookies and handshake values in memory only.",
            "No raw response, session, cookie, authentication or server-path data is saved.",
            "This fresh manifest does not replace the independently reviewed age-source-manifest.json.",
            (
                "describe_age.py accepts the historical hashes only; fresh data needs independent source "
                "review and an explicit provenance update before analysis."
            ),
            "This command acquires age XML only. Existing TAAS65+ and MOIS inputs are separate.",
            "Numerical validation does not establish police-record truth, causality or usage permission.",
        ],
    }
    buffers["fresh-age-manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    # mkdir is exclusive, then each file is exclusive: no existing path is replaced.
    output.mkdir()
    for name, body in buffers.items():
        with (output / name).open("xb") as stream:
            stream.write(body)
    return manifest


def offline_check(case_dir=HERE):
    """Check every historical raw hash and source structure without modifying it."""
    case_dir = Path(case_dir)
    checked = []
    try:
        for name, path_key, expected in (
            (
                "taas-qc.json",
                "file",
                {
                    f"data/raw/taas-{start}-{end}-page-{page}.xml"
                    for start, end in BATCHES
                    for page in (1, 2)
                },
            ),
            (
                "population-qc.json",
                "path",
                {f"data/raw/population-{y}-12.csv" for y in range(2013, 2019)},
            ),
        ):
            document = json.loads((case_dir / name).read_text(encoding="utf-8"))
            sources = document["sources"]
            if len(sources) != len(expected) or {s[path_key] for s in sources} != expected:
                raise ValueError("Historical source inventory changed")
            raw_sources = {}
            for source in sources:
                relative = source[path_key]
                raw = (case_dir / relative).read_bytes()
                if sha256(raw) != source["sha256"]:
                    raise ValueError("Historical raw SHA256 mismatch")
                raw_sources[relative] = raw
                checked.append({"file": relative, "sha256": source["sha256"]})
            if name == "taas-qc.json":
                for start, end in BATCHES:
                    years = range(start, end + 1)
                    pages = [
                        taas.parse_page(
                            raw_sources[f"data/raw/taas-{start}-{end}-page-{page}.xml"], years
                        )
                        for page in (1, 2)
                    ]
                    reconciled = taas.reconcile(pages, years)
                    taas.verify_reference(reconciled["national_totals"])
            else:
                for year in range(2013, 2019):
                    population.inspect_population(
                        raw_sources[f"data/raw/population-{year}-12.csv"], year
                    )
        # This approved loader binds requested area/metric/years to exact historical hashes.
        load_age_sources(case_dir / "data/raw-age")
        age_manifest = json.loads((HERE / "age-source-manifest.json").read_text(encoding="utf-8"))
        checked.extend(
            {"file": "data/raw-age/" + s["file"], "sha256": s["sha256"]}
            for s in age_manifest["sources"]
        )
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "Missing historical 원본/QC inputs. Restore the reviewed ignored data/ snapshot for exact "
            "offline replay. Fresh age only: fetch.py --download --age-only --output-dir NEW_DIR; "
            "see data/README.md for separate TAAS65+/MOIS prerequisites. Fresh bytes require review."
        ) from error
    return {
        "mode": "offline_check",
        "network_requests": 0,
        "writes": 0,
        "historical_raw_inputs_checked": len(checked),
        "sources": checked,
        "analysis_approved": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Explicit fresh public acquisition")
    parser.add_argument(
        "--age-only", action="store_true", help="Acquire age XML only; TAAS65+/MOIS remain separate"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="New directory with an existing resolved parent"
    )
    args = parser.parse_args(argv)
    if args.download and (not args.age_only or args.output_dir is None):
        parser.error("--download requires --age-only and --output-dir NEW_DIR")
    if not args.download and (args.age_only or args.output_dir is not None):
        parser.error("--age-only/--output-dir require --download")
    try:
        result = download_age(args.output_dir) if args.download else offline_check(HERE)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError):
        # Upstream errors may contain runtime paths; never echo a server response.
        print(
            "Source validation/acquisition failed. Use a new directory with a resolved existing "
            "parent; changed public source definitions require independent review. "
            "Existing inputs were not replaced.",
            file=sys.stderr,
        )
        return 1
    if args.download:
        result = {
            "mode": result["acquisition_kind"],
            "files": len(result["sources"]),
            "manifest": "fresh-age-manifest.json",
            "review_status": "pending",
            "historical_byte_identity_promised": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
