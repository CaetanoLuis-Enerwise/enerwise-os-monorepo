"""Run one shadow-mode assessment and write an HTML report.

Example data only:

    python -m app.assessment \\
        --load examples/assessment/EXAMPLE_15min_load.csv \\
        --omie examples/assessment/EXAMPLE_omie_marginalpdbc.txt \\
        --site-id EXAMPLE-SITE \\
        --example-data \\
        --shiftable-fraction 0.5 \\
        --out /tmp/EXAMPLE_assessment.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.assessment.analysis import run_assessment
from app.assessment.errors import AssessmentInputError
from app.assessment.html_report import render_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Price a 15-minute load CSV with OMIE MarginalPT and write an HTML report."
    )
    parser.add_argument("--load", required=True, type=Path, help="Client 15-minute CSV.")
    parser.add_argument("--omie", required=True, type=Path, help="OMIE marginalpdbc file.")
    parser.add_argument("--out", required=True, type=Path, help="HTML report path.")
    parser.add_argument("--site-id", default="unspecified")
    parser.add_argument(
        "--shiftable-fraction",
        type=float,
        default=None,
        help="Share of each complete hour that may move, from 0 to 1. Omit to leave achievable savings unstated.",
    )
    parser.add_argument(
        "--example-data",
        action="store_true",
        help="Mark the report as example data. Also forced when a filename contains EXAMPLE.",
    )
    args = parser.parse_args(argv)
    try:
        result = run_assessment(
            load_path=args.load,
            omie_path=args.omie,
            site_id=args.site_id,
            shiftable_fraction=args.shiftable_fraction,
            example_data=args.example_data,
        )
    except AssessmentInputError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(result), encoding="utf-8")
    summary = {
        "report": str(args.out),
        "site_id": result["site_id"],
        "example_data": result["example_data"],
        "priced_kwh": result["cost"]["priced_kwh"],
        "priced_cost_eur": result["cost"]["priced_cost_eur"],
        "upper_bound_savings_eur": result["shift"]["upper_bound_savings_eur"],
        "constrained_savings_eur": result["shift"]["constrained_savings_eur"],
        "peak_reduction_kw": result["peak_reduction_kw"],
        "shadow_mode": result["shadow_mode"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
