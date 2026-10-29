"""Self-contained HTML assessment report. Numbers come from the computed result."""

from __future__ import annotations

import html
import json


def _eur(value: float | None) -> str:
    if value is None:
        return "not stated"
    return f"EUR {value:,.2f}"


def _num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def render_html(result: dict) -> str:
    example = result["example_data"]
    banner = (
        "<p class=\"banner\">EXAMPLE DATA. This report is not a client result and not a bill.</p>"
        if example
        else ""
    )
    shift = result["shift"]
    if shift["constrained_savings_stated"]:
        fraction = shift["shiftable_fraction"]
        constrained = (
            f"<p>Under the stated assumption that <strong>{fraction:.0%}</strong> of each "
            f"complete hour can move to a cheaper hour the same Lisbon day, without raising "
            f"any hour above that day's highest complete-hour energy, the estimated shift "
            f"saving is <strong>{_eur(shift['constrained_savings_eur'])}</strong>.</p>"
        )
    else:
        constrained = (
            "<p>No shiftable fraction was supplied, so this report does not state an "
            "achievable shift saving.</p>"
        )

    hour_rows = []
    for hour in result["cost"]["hours"]:
        hour_rows.append(
            "<tr>"
            f"<td>{html.escape(hour['hour_start_lisbon'])}</td>"
            f"<td>{_num(hour['kwh'], 3)}</td>"
            f"<td>{_num(hour['omie_eur_mwh'], 2)}</td>"
            f"<td>{_num(hour['omie_eur_kwh'], 5)}</td>"
            f"<td>{_num(hour['cost_eur'], 2)}</td>"
            f"<td>{'yes' if hour['complete'] else 'no'}</td>"
            "</tr>"
        )
    month_rows = []
    for month in result["cost"]["months"]:
        month_rows.append(
            "<tr>"
            f"<td>{html.escape(month['month'])}</td>"
            f"<td>{_num(month['kwh'], 3)}</td>"
            f"<td>{_num(month['cost_eur'], 2)}</td>"
            f"<td>{month['hours']}</td>"
            "</tr>"
        )
    rejected = result["omie"]["rejected_days"]
    if rejected:
        rejected_html = "<ul>" + "".join(
            "<li>"
            f"{html.escape(item['delivery_day'])}: {html.escape(item['reason'])}"
            "</li>"
            for item in rejected
        ) + "</ul>"
    else:
        rejected_html = "<p>None.</p>"

    assumptions = "".join(f"<li>{html.escape(line)}</li>" for line in result["assumptions"])
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    load = result["load"]
    cost = result["cost"]
    coverage_pct = load["coverage"] * 100

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Enerwise assessment {html.escape(result['site_id'])}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; color: #1c1915; margin: 2rem auto; max-width: 920px; line-height: 1.45; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 0.2rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 1.8rem; }}
  table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
  th, td {{ border-bottom: 1px solid #d6d0c6; text-align: left; padding: 0.35rem 0.5rem; vertical-align: top; }}
  th {{ font-size: 0.82rem; letter-spacing: 0.02em; }}
  td:nth-child(n+2), th:nth-child(n+2) {{ text-align: right; }}
  .banner {{ background: #f4e4c4; border: 1px solid #b45309; padding: 0.8rem 1rem; }}
  .meta {{ color: #444; }}
  .figure {{ font-size: 1.15rem; }}
  @media print {{ body {{ margin: 0.6cm; }} }}
</style>
</head>
<body>
{banner}
<h1>Enerwise shadow-mode data assessment</h1>
<p class="meta">Site {html.escape(result['site_id'])}. Wholesale OMIE energy only. No physical dispatch. Peak reduction reported as 0.0 kW.</p>
<h2>OMIE cost</h2>
<p class="figure">Priced load: <strong>{_num(cost['priced_kwh'], 3)} kWh</strong>. OMIE MarginalPT cost: <strong>{_eur(cost['priced_cost_eur'])}</strong>.</p>
<p>Unpriced load left out of that total: {_num(cost['unpriced_kwh'], 3)} kWh across {cost['unpriced_intervals']} intervals. Those intervals were not given a made-up price.</p>
<h2>Shift from expensive hours to cheap hours</h2>
<p>Theoretical upper bound, if every complete-hour kWh could move to the cheapest complete hour that same Lisbon day: <strong>{_eur(shift['upper_bound_savings_eur'])}</strong>. This is not an achievable saving.</p>
{constrained}
<p>Reported peak reduction: <strong>0.0 kW</strong>. Reference site SITE-00 historical benchmark maximum monthly peak reduction is 0.0 kW. This assessment does not calculate or sell a peak cut.</p>
<h2>Load file</h2>
<table>
<tr><th>Item</th><th>Value</th></tr>
<tr><td>File</td><td>{html.escape(result['load_file'])}</td></tr>
<tr><td>Rows</td><td>{load['rows']}</td></tr>
<tr><td>First timestamp (Europe/Lisbon)</td><td>{html.escape(load['first_timestamp_lisbon'])}</td></tr>
<tr><td>Last timestamp (Europe/Lisbon)</td><td>{html.escape(load['last_timestamp_lisbon'])}</td></tr>
<tr><td>Span (days)</td><td>{_num(load['span_days'], 3)}</td></tr>
<tr><td>Interval coverage</td><td>{coverage_pct:.2f}%</td></tr>
<tr><td>Missing intervals</td><td>{load['missing_intervals']}</td></tr>
<tr><td>Coverage meets 98%</td><td>{"yes" if load["coverage_meets_98_percent"] else "no"}</td></tr>
<tr><td>Meets 12-month minimum</td><td>{"yes" if load["meets_12_month_minimum"] else "no"}</td></tr>
<tr><td>Blank or non-numeric load rows</td><td>{load['blank_or_non_numeric_rows']}</td></tr>
</table>
<h2>OMIE file</h2>
<p>File {html.escape(result['omie_file'])}. Column used: MarginalPT (default column 5). Spain's MarginalES is not used. Priced periods: {result['omie']['priced_periods']}. Market clock: Europe/Madrid. Load clock: Europe/Lisbon.</p>
<h3>Delivery days excluded</h3>
{rejected_html}
<h2>Cost by month</h2>
<table>
<thead><tr><th>Month</th><th>kWh</th><th>Cost EUR</th><th>Hours</th></tr></thead>
<tbody>
{''.join(month_rows)}
</tbody>
</table>
<h2>OMIE cost per hour</h2>
<table>
<thead><tr><th>Hour start (Europe/Lisbon)</th><th>kWh</th><th>OMIE EUR/MWh</th><th>EUR/kWh</th><th>Cost EUR</th><th>Complete hour</th></tr></thead>
<tbody>
{''.join(hour_rows)}
</tbody>
</table>
<h2>Assumptions</h2>
<ul>
{assumptions}
</ul>
<p class="meta">Print this page to PDF if a PDF file is needed. This version writes HTML and does not render a separate PDF.</p>
<script type="application/json" id="enerwise-assessment">{payload}</script>
</body>
</html>
"""
