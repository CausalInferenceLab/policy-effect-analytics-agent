"""Step 2 - fetch public data for this case.

Run:  python cases/<your-case>/fetch.py
Writes raw files to data/raw/ (git-ignored) and a tidy panel to data/processed/.
"""

from __future__ import annotations

import os
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
RAW_DIR = CASE_DIR / "data" / "raw"
PROCESSED_DIR = CASE_DIR / "data" / "processed"

try:  # core is evolving; keep the template importable even if its API changes.
    from core.schema.plan import load_plan
except ImportError:  # pragma: no cover
    load_plan = None


def read_plan() -> dict:
    """Load plan.yaml via core if available, else as plain YAML."""
    path = CASE_DIR / "plan.yaml"
    if load_plan is not None:
        return load_plan(path)
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> None:
    plan = read_plan()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    sources = plan.get("data_sources", []) if isinstance(plan, dict) else plan.data_sources
    for src in sources:
        name = src["name"] if isinstance(src, dict) else src.name
        key_env = (
            src.get("api_key_env") if isinstance(src, dict) else getattr(src, "api_key_env", None)
        )
        if key_env and not os.getenv(key_env):
            raise SystemExit(f"{key_env} is not set. Copy .env.example to .env and fill it in.")
        # TODO: call a core adapter (e.g. core.adapters.kosis) and save to RAW_DIR
        print(f"[fetch] TODO: {name}")

    # TODO: clean raw -> tidy panel (one row per `unit`), save PROCESSED_DIR / "panel.csv"


if __name__ == "__main__":
    main()
