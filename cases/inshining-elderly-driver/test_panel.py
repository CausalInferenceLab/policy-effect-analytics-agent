"""지역·기간 불일치가 사고율로 조용히 바뀌지 않는지 검사한다."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from panel import build_panel, read_verified_csv


def pop(name="부산광역시 중구", code="2611000000", year=2013, older=100):
    return dict(
        region_name=name,
        region_code=code,
        province_code=code[:2] + "00000000",
        reference_year=year,
        reference_date=f"{year}-12-31",
        outcome_year=year + 1,
        population_65plus=older,
    )


def accident(name="부산광역시 중구", year=2014, count=2):
    return dict(region_name=name, year=year, older_accidents=count)


class PanelTests(unittest.TestCase):
    def test_modified_derived_input_cannot_bypass_source_qc(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.csv"
            path.write_text("region_name,year,older_accidents\n부산광역시 중구,2014,2\n")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(read_verified_csv(path, digest)[0]["older_accidents"], "2")
            path.write_text(path.read_text().replace(",2\n", ",3\n"))
            with self.assertRaisesRegex(ValueError, "해시"):
                read_verified_csv(path, digest)

    def test_joins_previous_december_and_uses_full_region_name(self):
        records = [pop(), pop("서울특별시 중구", "1114000000", older=200), pop(year=2014, older=50)]
        output = build_panel([accident(), accident("서울특별시 중구", count=0)], records)
        self.assertEqual(output[0]["population65_start"], 100)
        self.assertEqual(output[0]["crashes65_per_10000_residents"], 200)
        self.assertEqual(output[1]["crashes65_per_10000_residents"], 0)
        self.assertNotIn("first_treat", output[0])

    def test_missing_region_is_an_error_not_zero(self):
        with self.assertRaisesRegex(ValueError, "분모 없음"):
            build_panel([accident("부산광역시 해운대구")], [pop()])

    def test_sejong_province_total_and_same_name_district_are_distinct_levels(self):
        province = pop("세종특별자치시", "3600000000")
        province["is_province_total"] = "True"
        district = pop("세종특별자치시", "3611000000")
        district["is_province_total"] = "False"
        output = build_panel([accident("세종특별자치시")], [province, district])
        self.assertEqual(output[0]["region_id"], "3611000000")

    def test_duplicate_source_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "사고 키 중복"):
            build_panel([accident(), accident()], [pop()])
        with self.assertRaisesRegex(ValueError, "인구 키 중복"):
            build_panel([accident()], [pop(), pop()])

    def test_zero_or_missing_denominator_and_negative_accidents_fail(self):
        for value in [0, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_panel([accident()], [pop(older=value)])
        with self.assertRaises(ValueError):
            build_panel([accident(count=-1)], [pop()])

    def test_mislabelled_reference_year_fails(self):
        record = pop()
        record["reference_year"] = 2014
        with self.assertRaisesRegex(ValueError, "직전연도"):
            build_panel([accident()], [record])
        record = pop()
        record["reference_date"] = "2013-01-31"
        with self.assertRaisesRegex(ValueError, "12월"):
            build_panel([accident()], [record])

    def test_parent_and_child_accident_units_cannot_both_enter(self):
        with self.assertRaisesRegex(ValueError, "공간 중첩"):
            build_panel(
                [accident("전라북도 전주시"), accident("전라북도 전주시 완산구")],
                [pop("전라북도 전주시", "4511000000"), pop("전라북도 전주시 완산구", "4511100000")],
            )

    def test_empty_accident_input_cannot_produce_successful_panel(self):
        with self.assertRaisesRegex(ValueError, "사고 자료 없음"):
            build_panel([], [pop()])


if __name__ == "__main__":
    unittest.main()
