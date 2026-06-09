# 中证500数据目录

本目录由对应的 `scripts/build_csi500_dataset.py` 生成，主指数代码为 `000905.SH`。

## 文件

- `index_daily.csv`: 日频指数行情与收益率，`return` 为小数收益率，`return_pct` 为原始百分比。
- `constituent_weights_snapshots.csv`: 快照日期索引；每行指向 `constituent_weights_snapshots/YYYY-MM-DD.csv`。
- `constituent_weights_snapshots/`: 原始月度/快照成分股权重，每个快照日一个 CSV。
- `constituent_weights_daily_asof.csv`: 日频 as-of 日期索引；每行指向 `constituent_weights_daily_asof/YYYY-MM-DD.csv`。
- `constituent_weights_daily_asof/`: 按 point-in-time 规则展开后的成分股权重，每个交易日一个 CSV。
- `data_quality.csv`: 可诊断的数据质量检查。
- `manifest.json`: 生成时间、来源、覆盖范围、行数和 caveats。

## Point-in-time 口径

当前 as-of 策略为 `next_trading_day`：
snapshot weights become usable on the next available trading day。

## 已知限制

`total_return` 会使用配置中的候选全收益指数；如果本地未发现可用日线行情则留空。
成分快照完整性按预期成员数 `500` 和权重和区间 `[95, 105]` 标记，需结合 `quality_status` 和 `data_quality.csv` 使用。
