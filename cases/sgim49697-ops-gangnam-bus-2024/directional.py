"""방향·계절·기상 후속 점검의 수집과 분석 단계를 실행한다."""

import argparse

from gangnam.directional_data import collect, prepare


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["collect", "prepare", "weather", "analyze", "plot"])
    args = p.parse_args()
    if args.stage in {"collect", "prepare"}:
        {"collect": collect, "prepare": prepare}[args.stage]()
    elif args.stage == "weather":
        from gangnam.directional_weather import collect_weather
        collect_weather()
    elif args.stage == "analyze":
        from gangnam.directional import analyze
        analyze()
    else:
        from gangnam.directional_plots import plot
        plot()


if __name__ == "__main__":
    main()
