from __future__ import annotations

import os

import pytest

from finfact_io import FinfactStore


@pytest.mark.skipif(
    os.environ.get("FINFACT_RUN_LOCAL_DATA_TESTS") != "1",
    reason="local source data smoke tests are opt-in",
)
def test_local_ashare_daily_data_smoke() -> None:
    store = FinfactStore()

    report = store.ashare.initialize(validation="sample")
    df = store.ashare.daily_metrics("000001.SZ", start="2024-01-01", end="2024-01-31")

    assert report.zip_archives["daily_metrics"].member_count > 0
    assert not df.empty


@pytest.mark.skipif(
    os.environ.get("FINFACT_RUN_LOCAL_DATA_TESTS") != "1",
    reason="local source data smoke tests are opt-in",
)
def test_local_index_data_smoke() -> None:
    store = FinfactStore()

    index_report = store.index.initialize(validation="sample")
    info = store.index.basic_info("sse", columns="standard")
    bars = store.index.bars(
        "000300.SH",
        freq="day",
        source="combined",
        start="2026-06-01",
        end="2026-06-03",
        columns="standard",
    )
    metrics = store.index.market_metrics(
        "000300.SH",
        source="combined",
        start="2026-06-01",
        end="2026-06-03",
        columns="standard",
    )
    sw_daily = store.industry.daily(
        "sw",
        "801010.SI",
        source="combined",
        start="2026-06-01",
        end="2026-06-03",
        columns="standard",
    )
    citic_daily = store.industry.daily(
        "citic",
        "CI005001.CI",
        source="combined",
        start="2026-06-01",
        end="2026-06-03",
        columns="standard",
    )
    sw_members = store.industry.sw_members(date="2026-06-03", match="exact", columns="standard")
    members = store.constituents.index_members(
        "000300.SH",
        date="2026-04-30",
        provider="auto",
        columns="standard",
    )
    available_day = store.index.available_indices(
        dataset="bars",
        freq="day",
        source="historical",
        columns="standard",
    )
    available_all = store.index.available_indices(columns="standard")

    assert index_report.zip_archives["day"].member_count > 0
    assert "000300.SH" in set(info["index_code"])
    assert len(available_day) == index_report.zip_archives["day"].member_count
    assert "000300.SH" in set(available_all["index_code"])
    assert not bars.empty
    assert not metrics.empty
    assert not sw_daily.empty
    assert not citic_daily.empty
    assert not sw_members.empty
    assert not members.empty
    assert metrics.attrs["field_units"]["total_market_cap_yuan"] == "元"
    assert sw_daily.attrs["field_units"]["total_market_cap_10k_yuan"] == "万元"
