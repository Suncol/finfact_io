# SW2021 Current Industry Reference

This directory contains a static SW2021 industry lookup based only on the
申万行业成分 snapshot dated 2026-06-03.

The data is intended for historical industry exposure and constraint analysis
where every date uses the same current industry classification. It is not a
historical point-in-time industry membership dataset.

Files:

- `current_snapshot.csv`: one row per stock in the 2026-06-03 SW snapshot.
- `industry_taxonomy.csv`: SW2021 L1/L2/L3 industry taxonomy.
- `industry_matrix_edges.csv`: long-form L1/L2/L3 matrix memberships.
- `data_quality.csv`: validation checks for uniqueness, taxonomy consistency,
  listed-stock coverage, and static-reference metadata.
- `manifest.json`: machine-readable source and methodology metadata.

If the current snapshot contains an industry code absent from the official
taxonomy files, the snapshot code is preserved and added to
`industry_taxonomy.csv` with `taxonomy_source_status=snapshot_inferred`.
