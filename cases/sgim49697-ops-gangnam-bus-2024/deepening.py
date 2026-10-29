"""두 번째 집중 탐색의 별도 수집·분석 명령을 실행한다."""

import argparse
import importlib

COMMANDS = {
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
