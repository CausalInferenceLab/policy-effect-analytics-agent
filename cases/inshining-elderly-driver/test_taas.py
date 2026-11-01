"""공개 TAAS 응답의 필터, 페이지, 합계와 모호한 지역 연결을 검증한다."""

import tempfile
import unittest
from pathlib import Path

from taas import (
    PublicClient,
    build_parameters,
    canonical_name,
    parse_page,
    reconcile,
    require_new_raw_directory,
    verify_reference,
)

PATTERN = dict(
    Parameter=':row_list="906:*907",:col_list="888:922",:mea_list="334:335",:condition="D903@|OCT_USER.ACC_CLS_15_YN.ELE_NAME = 예;|",:agg_info="",:pagenum="1"',
    MenuComment="노인운전자 교통사고 : 가해운전자(1당사자)의 연령이 65세 이상인 교통사고",
)


def xml(rows, data, years=(2017,), page=1, total=1):
    labels = "".join(
        "<TR>" + "".join('<TD code="' + s + '">' + s + "</TD>" for s in row) + "</TR>"
        for row in rows
    )
    vals = "".join(
        "<TR>" + "".join("<TD>" + str(v) + "</TD>" for v in row) + "</TR>" for row in data
    )
    cols = (
        "<TR>" + "".join('<TD code="' + str(y) + '">' + str(y) + "</TD>" for y in years) + "</TR>"
    )
    return (
        "<OCTAGONDATA><PAGE><TOTALPAGE>"
        + str(total)
        + "</TOTALPAGE><CURRENTPAGE>"
        + str(page)
        + "</CURRENTPAGE></PAGE>"
        "<GRID><COLSESSION><![CDATA[<TABLE>"
        + cols
        + "</TABLE>]]></COLSESSION><ROWSESSION><![CDATA[<TABLE>"
        + labels
        + "</TABLE>]]></ROWSESSION>"
        "<DATASESSION><![CDATA[<TABLE>"
        + vals
        + "</TABLE>]]></DATASESSION></GRID><GRIDCOMMENT><PATTERNCOMMENT>"
        + PATTERN["MenuComment"]
        + "</PATTERNCOMMENT></GRIDCOMMENT><ERROR/></OCTAGONDATA>"
    ).encode()


class TaasTests(unittest.TestCase):
    def test_busanjin_alias_is_limited_to_verified_province_period_and_target(self):
        allowed = {"부산광역시 부산진구"}
        for year in range(2014, 2020):
            with self.subTest(year=year):
                self.assertEqual(
                    canonical_name("부산", "진구", allowed, year=year), "부산광역시 부산진구"
                )
        for year in [2013, 2020, None]:
            with self.subTest(outside_year=year):
                self.assertIsNone(canonical_name("부산", "진구", allowed, year=year))
        self.assertIsNone(canonical_name("경남", "진구", allowed, year=2019))
        self.assertIsNone(canonical_name("부산", "진구", {"부산광역시 중구"}, year=2019))

    def test_fetch_refuses_existing_original_before_any_request(self):
        with tempfile.TemporaryDirectory() as folder:
            rawdir = Path(folder)
            original = rawdir / "taas-2014-2018-page-1.xml"
            original.write_bytes(b"preserved original")
            with self.assertRaises(FileExistsError):
                require_new_raw_directory(rawdir)
            self.assertEqual(original.read_bytes(), b"preserved original")

    def test_independent_reference_rejects_unfiltered_all_accidents(self):
        with self.assertRaises(ValueError):
            verify_reference({2014: 223552})
        verify_reference({2014: 20275, 2019: 33239})

    def test_boundary_change_requires_hold_even_with_identical_name(self):
        self.assertIsNone(canonical_name("충북", "청주시", {"충청북도 청주시"}, year=2014))
        self.assertIsNone(canonical_name("충북", "청원군", {"충청북도 청원군"}, year=2014))

    def test_metadata_accepts_explicit_null_error_from_official_protocol(self):
        client = PublicClient()
        client.post = lambda path, data: b'{"result":{"PatternId":7265},"error":null}'
        self.assertEqual(client.metadata("loadPattern", patternId=7265), {"PatternId": 7265})

    def test_query_translates_saved_filters_and_removes_month(self):
        value = build_parameters(PATTERN, 2014, 2018)
        self.assertIn(':condition="D903@|@P01 S01 #OTE![예]!#;|;"', value)
        self.assertIn(
            ':vcondition="D1443@|@P08 S01 T111 #OTE![201401]!# #OTE![201812]!#;|;"', value
        )
        self.assertIn(':row_list="906:907"', value)
        self.assertIn(':col_list="888"', value)
        self.assertIn(':mea_list="334"', value)

    def test_rejects_unverified_definition_and_over_five_years(self):
        with self.assertRaises(ValueError):
            build_parameters(dict(PATTERN, MenuComment="피해자"), 2014, 2018)
        with self.assertRaises(ValueError):
            build_parameters(dict(PATTERN, Parameter=':condition=""'), 2014, 2018)
        with self.assertRaises(ValueError):
            build_parameters(PATTERN, 2014, 2019)

    def test_parser_carries_province_across_page_rows_and_keeps_zero(self):
        result = parse_page(
            xml([["합계"], ["부산", "합계"], ["중구"], ["서구"]], [[4], [4], [4], [0]]), [2017]
        )
        self.assertEqual(result["rows"][-1], ("부산", "서구", (0,)))
        self.assertEqual(result["rows"][0], ("합계", "합계", (4,)))

    def test_multi_year_total_column_is_checked_then_excluded(self):
        raw = xml([["합계"]], [[7, 4, 3]], years=("합계", 2017, 2018))
        self.assertEqual(parse_page(raw, [2017, 2018])["rows"][0][2], (4, 3))
        with self.assertRaises(ValueError):
            parse_page(xml([["합계"]], [[8, 4, 3]], years=("합계", 2017, 2018)), [2017, 2018])

    def test_rejects_wrong_year_missing_cells_and_wrong_definition(self):
        raw = xml([["합계"]], [[4]])
        with self.assertRaises(ValueError):
            parse_page(raw, [2018])
        with self.assertRaises(ValueError):
            parse_page(xml([["합계"], ["부산", "합계"]], [[4]]), [2017])
        with self.assertRaises(ValueError):
            parse_page(raw.replace("65세 이상".encode(), "피해자".encode()), [2017])

    def test_pages_and_each_province_must_reconcile(self):
        first = parse_page(
            xml([["합계"], ["부산", "합계"], ["중구"]], [[4], [4], [3]], total=2), [2017]
        )
        second = parse_page(xml([["부산", "서구"]], [[1]], page=2, total=2), [2017])
        self.assertEqual(reconcile([first, second], [2017])["national_totals"], {2017: 4})
        with self.assertRaises(ValueError):
            reconcile([first], [2017])
        bad = parse_page(xml([["부산", "서구"]], [[2]], page=2, total=2), [2017])
        with self.assertRaises(ValueError):
            reconcile([first, bad], [2017])

    def test_sejong_single_leaf_is_also_its_province_total(self):
        page = parse_page(
            xml([["합계"], ["부산", "합계"], ["중구"], ["세종", "세종시"]], [[5], [4], [4], [1]]),
            [2017],
        )
        result = reconcile([page], [2017])
        self.assertEqual(result["province_count"], 2)
        self.assertEqual(result["national_totals"], {2017: 5})

    def test_duplicate_district_and_ambiguous_names_are_not_silently_merged(self):
        page = parse_page(
            xml([["합계"], ["부산", "합계"], ["중구"], ["중구"]], [[4], [4], [2], [2]]), [2017]
        )
        with self.assertRaises(ValueError):
            reconcile([page], [2017])
        self.assertEqual(canonical_name("부산", "중구", {"부산광역시 중구"}), "부산광역시 중구")
        self.assertIsNone(
            canonical_name(
                "경기", "고양시 일산구", {"경기도 고양시 일산동구", "경기도 고양시 일산서구"}
            )
        )


if __name__ == "__main__":
    unittest.main()
