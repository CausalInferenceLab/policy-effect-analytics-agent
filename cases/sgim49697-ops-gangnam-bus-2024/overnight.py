"""10시간 확장 탐색의 수집·분석 단계를 명시적으로 실행한다."""

import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["weather-collect", "weather-prepare", "bus-prepare", "bus-sensitivity", "weather-analysis"])
    args = parser.parse_args()
    from gangnam import (
        overnight_bus,
        overnight_sensitivity,
        overnight_weather,
        overnight_weather_analysis,
    )

    {"weather-collect": overnight_weather.collect, "weather-prepare": overnight_weather.prepare,
     "bus-prepare": overnight_bus.prepare, "bus-sensitivity": overnight_sensitivity.run,
     "weather-analysis": overnight_weather_analysis.run}[args.stage]()


if __name__ == "__main__":
    main()
