"""합성 자료로 분모의 연령·중첩·코드 오류를 검사한다."""

import csv
import hashlib
import io
import unittest

from population import (
    download_query,
    inspect_population,
    population_header,
    query,
    verify_saved_source,
)


def source(rows, year=2013):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(population_header(year))
    for label, ages in rows:
        writer.writerow([label, sum(ages), sum(ages), *ages])
    return output.getvalue().encode("cp949")


def ages(young=0, older=0, oldest=0):
    values = [0] * 101
    values[64], values[65], values[100] = young, older, oldest
    return values


class PopulationTests(unittest.TestCase):
    def test_replay_rejects_changed_raw_bytes_and_missing_acquisition_metadata(self):
        raw = b"original public CSV"
        record = {"sha256": hashlib.sha256(raw).hexdigest()}
        verify_saved_source(raw, record)
        with self.assertRaisesRegex(ValueError, "해시"):
            verify_saved_source(raw + b"changed", record)
        with self.assertRaisesRegex(ValueError, "해시"):
            verify_saved_source(raw, {})

    def test_includes_65_and_100_but_not_64_and_preserves_zero(self):
        data, checks = inspect_population(
            source(
                [
                    ("부산광역시 (2600000000)", ages(9, 4, 2)),
                    ("부산광역시 중구 (2611000000)", ages(9, 4, 2)),
                    ("부산광역시 서구 (2614000000)", ages()),
                ]
            ),
            2013,
            expected_provinces=1,
        )
        self.assertEqual(data[1]["population_65plus"], 6)
        self.assertEqual(data[2]["population_65plus"], 0)
        self.assertEqual(data[1]["outcome_year"], 2014)
        self.assertEqual(checks["province_reconciliations"], 1)

    def test_city_and_districts_are_not_double_counted(self):
        rows = [
            ("전라북도 (4500000000)", ages(5, 7)),
            ("전라북도 전주시 (4511000000)", ages(2, 3)),
            ("전라북도 전주시 완산구 (4511100000)", ages(1, 1)),
            ("전라북도 전주시 덕진구 (4511300000)", ages(1, 2)),
            ("전라북도 군산시 (4513000000)", ages(3, 4)),
        ]
        data, checks = inspect_population(source(rows), 2013, expected_provinces=1)
        self.assertTrue(data[1]["overlapping_city_total"])
        self.assertFalse(data[2]["is_aggregate"])
        self.assertEqual(checks["leaf_65plus"], 7)

    def test_rejects_duplicate_code_even_when_labels_differ(self):
        rows = [
            ("부산광역시 (2600000000)", ages()),
            ("부산광역시 중구 (2611000000)", ages()),
            ("부산광역시 서구 (2611000000)", ages()),
        ]
        with self.assertRaisesRegex(ValueError, "중복"):
            inspect_population(source(rows), 2013, expected_provinces=1)

    def test_rejects_wrong_year_and_missing_values(self):
        raw = source([("부산광역시 (2600000000)", ages())])
        with self.assertRaisesRegex(ValueError, "헤더"):
            inspect_population(raw, 2014, expected_provinces=1)
        raw = raw.replace(b"0,0,", b"0,,", 1)
        with self.assertRaises(ValueError):
            inspect_population(raw, 2013, expected_provinces=1)

    def test_rejects_inconsistent_city_total(self):
        rows = [
            ("전라북도 (4500000000)", ages(0, 7)),
            ("전라북도 전주시 (4511000000)", ages(0, 6)),
            ("전라북도 전주시 완산구 (4511100000)", ages(0, 7)),
        ]
        with self.assertRaisesRegex(ValueError, "합계"):
            inspect_population(source(rows), 2013, expected_provinces=1)

    def test_response_form_must_match_requested_date_age_and_population_type(self):
        fields = {
            k: v
            for k, v in query(2013).items()
            if k not in {"sum", "searchYearMonth", "tableChart"}
        }
        fields["category"] = "month"
        html = (
            '<form id="formXlsDown">'
            + "".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in fields.items())
            + "</form>downloadCsvAge.do xlsStats=2"
        )
        self.assertEqual(download_query(html, 2013)["gender"], "")
        with self.assertRaisesRegex(ValueError, "조건"):
            download_query(html.replace('value="2013"', 'value="2014"'), 2013)


if __name__ == "__main__":
    unittest.main()
