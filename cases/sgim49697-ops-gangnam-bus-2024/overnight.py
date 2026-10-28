"""10시간 확장 탐색의 수집·분석 단계를 명시적으로 실행한다."""

import argparse
import importlib

STAGES = {
    "weather-collect": ("overnight_weather", "collect", []),
    "weather-prepare": ("overnight_weather", "prepare", []),
    "bus-prepare": ("overnight_bus", "prepare", []),
    "bus-sensitivity": ("overnight_sensitivity", "run", []),
    "weather-analysis": ("overnight_weather_analysis", "run", []),
    "routes": ("overnight_routes", "run", []),
    "route-weather": ("overnight_route_weather", "run", []),
    "route-plots": ("overnight_routes_plots", "plot", []),
    "passenger-collect": ("overnight_bus_data", "passengers", []),
    "passenger-prepare": ("overnight_bus_extract", "prepare", ["passengers"]),
    "passenger-analysis": ("overnight_passengers", "run", []),
    "passenger-covered": ("overnight_covered_passengers", "run", []),
    "passenger-covered-plot": ("overnight_passenger_plots", "plot", []),
    "multiyear-collect": ("overnight_bus_data", "multiyear", []),
    "multiyear-prepare": ("overnight_bus_extract", "prepare", ["multiyear"]),
    "schema2022": ("overnight_2022_audit", "run", []),
    "archives-audit": ("overnight_archive_audit", "run", []),
    "auxiliary-collect": ("overnight_auxiliary_data", "collect", []),
    "auxiliary-probe": ("overnight_transfer_probe", "run", []),
    "auxiliary-quality": ("overnight_auxiliary_quality", "run", []),
    "auxiliary-plots": ("overnight_auxiliary_plots", "plot", []),
    "cards-prepare": ("overnight_card", "prepare", []),
    "cards-analysis": ("overnight_card_analysis", "run", []),
    "daily-card-collect": ("overnight_daily_card_data", "collect", []),
    "daily-card-analysis": ("overnight_daily_card_analysis", "run", []),
    "daily-card-full-collect": ("overnight_daily_card_data", "collect", ["full"]),
    "daily-card-full-analysis": ("overnight_daily_card_analysis", "run", ["full"]),
    "card-records": ("overnight_card_records", "run", []),
    "mechanism": ("overnight_mechanism", "run", []),
    "fare-trim": ("overnight_fare_trim", "run", []),
    "road-context-collect": ("overnight_road_context_data", "collect", []),
    "road-context": ("overnight_road_context", "run", []),
    "road-names": ("overnight_road_names", "run", []),
    "road-names-plot": ("overnight_road_names_plot", "plot", []),
    "operations-plots": ("overnight_operations_plots", "plot", []),
    "forecast-collect": ("overnight_forecast_data", "collect", []),
    "forecast-prepare": ("overnight_forecast_data", "prepare", []),
    "forecast-bus-features": ("overnight_forecast_bus", "prepare", []),
    "forecast-features": ("overnight_forecast_features", "prepare", []),
    "forecast-train": ("overnight_forecast_train", "run", []),
    "forecast-freeze": ("overnight_forecast_freeze", "freeze", []),
    "forecast-test-collect": ("overnight_forecast_data", "collect", ["test"]),
    "forecast-test-prepare": ("overnight_forecast_data", "prepare", ["test"]),
    "forecast-test-bus-collect": ("overnight_forecast_test_bus", "collect", []),
    "forecast-test-bus-prepare": ("overnight_forecast_test_bus", "prepare", []),
    "forecast-test-features": ("overnight_forecast_features", "prepare", ["test"]),
    "forecast-test-evaluate": ("overnight_forecast_evaluate", "evaluate", []),
    "forecast-test-diagnostics": ("overnight_forecast_diagnostics", "run", []),
    "forecast-plots": ("overnight_forecast_plots", "plot", []),
    "baseline-prepare": ("overnight_baseline_runner", "prepare", []),
    "baseline-evaluate": ("overnight_baseline_evaluate", "evaluate", []),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=list(STAGES))
    args = parser.parse_args()
    module, function, arguments = STAGES[args.stage]
    getattr(importlib.import_module("gangnam." + module), function)(*arguments)


if __name__ == "__main__":
    main()
