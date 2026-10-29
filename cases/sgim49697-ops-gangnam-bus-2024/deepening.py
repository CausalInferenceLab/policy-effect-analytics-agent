"""두 번째 집중 탐색의 별도 수집·분석 명령을 실행한다."""

import argparse
import importlib

COMMANDS = {
    "infrastructure-raw": ("deepening_infrastructure_raw", "run"),
    "infrastructure-check": ("deepening_infrastructure_check", "run"),
    "infrastructure-plots": ("deepening_infrastructure_plots", "run"),
    "infrastructure-groups": ("deepening_route_groups", "run"),
    "infrastructure-prepare": ("deepening_infrastructure", "prepare"),
    "infrastructure-history": ("deepening_infrastructure", "history_audit"),
    "metadata-audit": ("deepening_metadata", "run"),
    "transition-raw-check": ("deepening_transition_check", "raw_check"),
    "transition-result-check": ("deepening_transition_check", "result_check"),
    "transition-plots": ("deepening_transition_plots", "run"),
    "transition-prepare": ("deepening_transition", "prepare"),
    "transition-audit": ("deepening_transition", "run"),
    "archive-plots": ("deepening_archive_plots", "run"),
    "archive-result-check": ("deepening_archive_result_check", "run"),
    "archive-feature-check": ("deepening_archive_check", "run"),
    "archive-eval-prepare": ("deepening_archive_evaluate", "prepare_context"),
    "archive-evaluate": ("deepening_archive_evaluate", "run"),
    "archive-train": ("deepening_archive_models", "run"),
    "archive-prepare": ("deepening_archive_data", "prepare"),
    "archive-features": ("deepening_archive_features", "run"),
    "episode-check": ("deepening_episode_check", "run"),
    "forecast-plots": ("deepening_forecast_plots", "run"),
    "availability-audit": ("deepening_availability", "run"),
    "episode-prepare": ("deepening_episode", "prepare"),
    "episode-audit": ("deepening_episode", "run"),
    "geometry-audit": ("deepening_geometry", "run"),
    "road-plots": ("deepening_road_plots", "run"),
    "geometry-prepare": ("deepening_geometry_data", "prepare"),
    "geometry-collect": ("deepening_geometry_data", "collect"),
    "road-raw-check": ("deepening_road_raw_check", "run"),
    "road-context": ("deepening_road", "run"),
    "gyeonggi-plots": ("deepening_gyeonggi_plots", "run"),
    "gyeonggi-audit": ("deepening_gyeonggi_audit", "run"),
    "gyeonggi-parse": ("deepening_gyeonggi_parse", "run"),
    "gyeonggi-prepare": ("deepening_gyeonggi_data", "prepare"),
    "gyeonggi-collect": ("deepening_gyeonggi_data", "collect"),
    "definitions-audit": ("deepening_definitions", "run"),
    "cohort-plots": ("deepening_cohort_plots", "run"),
    "cohort-raw-check": ("deepening_raw_check", "run"),
    "cohort-audit": ("deepening_cohort", "run"),
    "history-audit": ("deepening_identity", "audit"),
    "history-prepare": ("deepening_history_data", "prepare_requests"),
    "history-collect": ("deepening_history_data", "collect"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()
    module, function = COMMANDS[args.command]
    getattr(importlib.import_module("gangnam." + module), function)()


if __name__ == "__main__":
    main()
