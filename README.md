# finfact-io

Python IO utilities for local financial text datasets.

## Raw data roots

Raw source data defaults to `/data/A-share/raw_data_tb`. `FinfactStore()` derives
the A-share daily root from `A股数据_每日指标/` and the index root from `指数数据/`
under that directory.

Override discovery with `FINFACT_RAW_DATA_DIR` for the parent directory, or use
`FINFACT_ASHARE_DAILY_DIR` and `FINFACT_INDEX_DATA_DIR` for dataset-specific
roots. Explicit constructor arguments and script flags take precedence over
environment variables.

## Read generated data directory

Use `DataDirectoryReader` to read the generated datasets under the current
repository `data/` directory. This reader is independent from `FinfactStore`:
`FinfactStore` reads raw source directories, while `DataDirectoryReader` reads
already-built local outputs.

```python
from finfact_io.data_directory import DataDirectoryReader

reader = DataDirectoryReader("data")

latest = reader.ashare_daily_by_date("2026-06-03", symbols=["000001.SZ"])
weights = reader.csi1000_weights_by_date("2026-06-03")
csi300_weights = reader.index_weights_by_date("csi300", "2026-06-03")
industry = reader.sw_industry_snapshot(symbols=["000001.SZ"])
board_counts = reader.listing_board_counts(scope="listed")

dimensions = reader.join_stock_dimensions(["000001.SZ", "688001.SH"])
industry_matrix = reader.sw_industry_matrix(level="L1", stocks=["000001.SZ", "688001.SH"])
board_matrix = reader.listing_board_matrix(stocks=["000001.SZ", "688001.SH"])
```

## A-share daily metrics by trading day

Build all A-share daily metrics from the configured A-share daily data root:

```bash
.venv/bin/python scripts/build_ashare_daily_metrics_dataset.py
```

The default output is `data/ashare_daily_metrics/` and includes one standard
English-column CSV per trading day under `daily_metrics/YYYY-MM/YYYY-MM-DD.csv`,
a date index, schema metadata, data quality checks, and a manifest. The default
date range is 1990-12-19 through 2026-06-03.

## CSI point-in-time index datasets

Build local point-in-time index data directories from the configured index data
root:

```bash
.venv/bin/python scripts/build_csi300_dataset.py
.venv/bin/python scripts/build_csi500_dataset.py
.venv/bin/python scripts/build_csi1000_dataset.py
.venv/bin/python scripts/build_csi2000_dataset.py
```

The default outputs are `data/csi300/`, `data/csi500/`, `data/csi1000/`, and
`data/csi2000/`. Each directory includes daily index returns, date-partitioned
constituent-weight snapshots, a date-partitioned daily point-in-time as-of
expansion, quality checks, and a manifest. `DataDirectoryReader` exposes generic
`index_*` methods for all four datasets while preserving the existing
`csi1000_*` compatibility methods.

## SW2021 current industry reference

Build the static SW2021 current industry lookup from the configured index and
A-share data roots:

```bash
.venv/bin/python scripts/build_industry_sw_reference_dataset.py
```

The default output is `data/industry_sw_current_reference/`. It uses only the
申万行业成分 snapshot dated 2026-06-03, writes one `current_snapshot.csv`, a
SW2021 taxonomy table, and long-form L1/L2/L3 matrix edges. This is a static
current industry reference for historical exposure calculations, not a
historical point-in-time industry membership dataset.

## A-share listing-board current reference

Build the static A-share listing-board lookup from the configured A-share data
root:

```bash
.venv/bin/python scripts/build_listing_board_reference_dataset.py
```

The default output is `data/listing_board_current_reference/`. It uses
`股票列表.csv` and `退市股票列表.csv` to create an independent listing-board
dimension (`主板`, `创业板`, `科创板`, `北交所`), plus a long-form matrix edge
table for board exposure calculations. This is separate from SW/CITIC industry
classification and is a static current reference, not a historical
point-in-time reconstruction of board migrations.
