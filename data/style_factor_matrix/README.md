# Style Factor Matrix

This directory contains daily A-share style factor matrices from 2023-09-01 to 2026-06-03.

Each partitioned daily CSV is keyed by `(trade_date, symbol)` and contains:

- static SW industry one-hot columns from the current reference snapshot dated 2026-06-03;
- point-in-time CSI 300/500/1000/2000 membership one-hot columns;
- total market capitalization in 万元 plus ascending rank, percentile rank, and log10.

The industry columns intentionally use the static current reference exported in
`data/industry_sw_current_reference`. They are not historical point-in-time
industry memberships.
