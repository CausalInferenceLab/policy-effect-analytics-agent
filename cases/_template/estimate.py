"""Step 3 - estimate the effect defined in plan.yaml.

Run:  python cases/<your-case>/estimate.py
Reads data/processed/panel.csv, writes figures/*.png and prints the estimate.
"""

from __future__ import annotations

from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
PANEL = CASE_DIR / "data" / "processed" / "panel.csv"
FIG_DIR = CASE_DIR / "figures"

try:  # keep the template importable even if core is not installed yet
    from core.pipeline import run_plan
    from core.report import render_report  # noqa: F401  (see _example_night_clinic)
    from core.schema.plan import load_plan
except ImportError:  # pragma: no cover
    run_plan = None
    load_plan = None


def main() -> None:
    if load_plan is None or run_plan is None:
        raise SystemExit("core is not installed. Run `make install` at the repo root.")
    if not PANEL.exists():
        raise SystemExit(f"{PANEL} not found. Run fetch.py first.")

    import pandas as pd

    plan = load_plan(CASE_DIR / "plan.yaml")
    panel = pd.read_csv(PANEL)
    FIG_DIR.mkdir(exist_ok=True)

    # run_plan: estimator in plan.estimator.method -> refutations -> abstention verdict
    results = run_plan(plan, panel)
    for r in results:
        print(r)
    # TODO: figures + report.md — copy the pattern in cases/_example_night_clinic/estimate.py


if __name__ == "__main__":
    main()
