# EXAMPLE DATA

These two files are not a client, not a bill, and not a measured saving.

`EXAMPLE_15min_load.csv` is a made-up 15-minute load for `EXAMPLE-SITE`.
`EXAMPLE_omie_marginalpdbc.txt` is a made-up OMIE day. Column 5 is MarginalPT
in EUR/MWh. Column 6 is MarginalES and must not be used.

Run:

```bash
python -m app.assessment \
  --load examples/assessment/EXAMPLE_15min_load.csv \
  --omie examples/assessment/EXAMPLE_omie_marginalpdbc.txt \
  --site-id EXAMPLE-SITE \
  --example-data \
  --shiftable-fraction 0.5 \
  --out /tmp/EXAMPLE_assessment.html
```

`--shiftable-fraction 0.5` is an assumption you type in. It is not a property of the example building. Omit it when you do not want an achievable shift figure stated.
