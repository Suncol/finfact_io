# LGBM Style Factors

This directory contains compact daily style features from
2023-09-01 to 2026-06-03.

The model-facing feature columns are:

- `industry_l1_code_id`, declared as a LightGBM categorical feature.
- `listing_board_id`, declared as a LightGBM categorical feature.
- `size_tier`, declared as a LightGBM categorical feature with ordered economic meaning.
- `total_market_cap_rank_pct`, the daily cross-sectional percentile rank of total market cap.

By default the stock universe excludes Beijing Stock Exchange (`BSE`) rows before
the daily market-cap percentile rank is calculated. Set `include_bse=True` when
building the export to include them.

The export intentionally excludes industry one-hot columns, separate index membership
flags, raw market cap, raw market-cap rank, and log10 market cap.
