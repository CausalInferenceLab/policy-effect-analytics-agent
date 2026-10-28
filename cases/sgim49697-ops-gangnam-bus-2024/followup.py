"""강남대로 후속 탐색의 수집·추출·분석·그림을 실행하는 진입점."""

import argparse

from gangnam.followup import analyze, prepare
from gangnam.followup_data import collect


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["collect", "prepare", "analyze", "plot"])
    args = p.parse_args()
    if args.stage == "plot":
        from gangnam.followup_plots import plot
        plot()
    else:
        {"collect": collect, "prepare": prepare, "analyze": analyze}[args.stage]()


if __name__ == "__main__":
    main()
