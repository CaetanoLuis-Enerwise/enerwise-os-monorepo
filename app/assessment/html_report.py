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
            f"<td>{html.escape(', '.join(hour.get('access_periods') or [])) or '—'}</td>"
            f"<td>{_num(hour.get('access_eur'), 2)}</td>"
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
    bill = result.get("bill") or {}
    access = bill.get("access") or {"applied": False}
    if access.get("applied"):
        period_rows = "".join(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{_num(values['kwh'], 3)}</td>"
            f"<td>{html.escape(str(values['eur_per_kwh']))}</td>"
            f"<td>{_num(values['eur'], 2)}</td>"
            "</tr>"
            for name, values in access["by_period"].items()
        )
        access_block = (
            f"<p>Voltage {html.escape(access['voltage'])}, {html.escape(access['cycle_label'])}. "
            f"Tariff year {access['tariff_year']}. Prices are the ERSE access workbook for 1 January 2026; "
            "the 1 October 2026 workbook still shows these BTE and MT prices. "
            f"Access energy: <strong>{_eur(access['energy_eur'])}</strong>.</p>"
            "<table><thead><tr><th>Period</th><th>kWh</th><th>EUR/kWh</th><th>EUR</th></tr></thead>"
            f"<tbody>{period_rows}</tbody></table>"
            f"<p>Contracted power: {_eur(access['contracted_power_eur'])} "
            f"({html.escape(access['contracted_power_eur_per_kw_day'])} EUR/kW.day, "
            f"{access['contracted_power_days']} days). "
            f"{'Not supplied, so this charge is omitted.' if access['contracted_power_omitted'] else ''}</p>"
            f"<p>Peak power: {_eur(access['peak_power_eur'])}. Basis: {html.escape(access['peak_power_basis'])}. "
            "The shift does not reduce this charge. Reported peak reduction remains 0.0 kW.</p>"
            "<p>Reactive energy is not charged. No reactive series was uploaded.</p>"
        )
    else:
        access_block = f"<p>{html.escape(access.get('reason', 'Access tariffs were not applied.'))}</p>"
    with_access = (result.get("shift") or {}).get("with_access")
    if with_access:
        access_shift = (
            "<p>The same shift, repriced with OMIE plus the time-of-use access energy"
            f"{', the supplied loss factor' if with_access['includes_loss_factor'] else ''}"
            f"{', the supplied supplier margin' if with_access['includes_supplier_margin'] else ''}"
            f"{', and the supplied IEC' if with_access['includes_iec'] else ''}: "
            f"upper bound <strong>{_eur(with_access['upper_bound_savings_eur'])}</strong>, "
            f"constrained <strong>{_eur(with_access['constrained_savings_eur'])}</strong>. "
            "Power charges are not in that saving.</p>"
        )
    else:
        access_shift = (
            "<p>No access cycle was supplied, so the shift above is wholesale OMIE only.</p>"
        )
    input_rows = []
    for key in ("loss_factor", "supplier_margin", "iec", "iva", "cav", "cav_iva", "dgeg"):
        item = bill.get(key)
        if not item:
            continue
        state = "supplied" if item["supplied"] else "not supplied — left out"
        input_rows.append(
            "<tr>"
            f"<td>{html.escape(item['name'])}</td>"
            f"<td>{_eur(item['eur']) if item['supplied'] else state}</td>"
            f"<td>{html.escape(item['source'])}</td>"
            "</tr>"
        )
    inputs_table = (
        "<table><thead><tr><th>Input</th><th>Amount</th><th>Source note</th></tr></thead><tbody>"
        + "".join(input_rows)
        + "</tbody></table>"
        + f"<p>Partial total of what this run actually priced: <strong>{_eur(bill.get('total_eur'))}</strong>. "
        "Lines that were not supplied are not inside that number.</p>"
    )
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
<p class="meta">Site {html.escape(result['site_id'])}. OMIE energy and, when a voltage and cycle are supplied, ERSE network access. No physical dispatch. Peak reduction reported as 0.0 kW.</p>
<h2>OMIE cost</h2>
<p class="figure">Priced load: <strong>{_num(cost['priced_kwh'], 3)} kWh</strong>. OMIE MarginalPT cost: <strong>{_eur(cost['priced_cost_eur'])}</strong>.</p>
<p>Unpriced load left out of that total: {_num(cost['unpriced_kwh'], 3)} kWh across {cost['unpriced_intervals']} intervals. Those intervals were not given a made-up price.</p>
<h2>Shift from expensive hours to cheap hours</h2>
<p>Theoretical upper bound, if every complete-hour kWh could move to the cheapest complete hour that same Lisbon day: <strong>{_eur(shift['upper_bound_savings_eur'])}</strong>. This is not an achievable saving.</p>
{constrained}
{access_shift}
<p>Reported peak reduction: <strong>0.0 kW</strong>. Reference site SITE-00 historical benchmark maximum monthly peak reduction is 0.0 kW. This assessment does not calculate or sell a peak cut.</p>
<h2>Network access tariffs</h2>
{access_block}
<h2>Margin, losses and taxes</h2>
{inputs_table}
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
<thead><tr><th>Hour start (Europe/Lisbon)</th><th>kWh</th><th>OMIE EUR/MWh</th><th>EUR/kWh</th><th>OMIE EUR</th><th>Access period</th><th>Access EUR</th><th>Complete hour</th></tr></thead>
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
