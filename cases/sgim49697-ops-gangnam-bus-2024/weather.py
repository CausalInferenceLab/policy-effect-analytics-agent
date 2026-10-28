"""서울 ASOS 일별 CSV를 공식 정의와 함께 등록한다. 원본은 data/에만 둔다."""

import argparse
from pathlib import Path

from gangnam.common import CASE
from gangnam.weather import normalize_weather


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, default=CASE / "data/weather/daily.csv")
    args = p.parse_args()
    normalize_weather(args.input, args.evidence, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
