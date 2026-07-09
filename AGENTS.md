# AGENTS.md

本文件适用于整个 `/Users/sun/Documents/Code/finfact-io` 仓库。后续任何 agent 或开发者在本仓库工作时，都必须先阅读并遵守这里的说明。

## 核心要求

用户的要求是：尽最大能力、严谨地完成问题，不需要为了节省时间而降低质量。这个仓库当前的核心任务不是做展示页，也不是做交易策略，而是把本地分散的 A 股、指数、行业、成分股、市值、估值等文本数据抽象成一个稳定的 Python IO 库。

目标产物应是一个可复用 Python package，建议包名使用 `finfact_io`，项目名可继续使用 `finfact-io`。

## 当前运行环境

当前项目环境由 `uv` 创建。Windows PowerShell 下当前观察到的环境为：

```powershell
uv venv
Using CPython 3.12.13
Creating virtual environment at: .venv
Activate with: .venv\Scripts\activate
```

在 Windows PowerShell 中，如果脚本执行策略阻止激活虚拟环境，先在当前进程临时放开执行策略，再进入虚拟环境：

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.\.venv\Scripts\Activate.ps1
python --version
```

macOS/Linux 环境路径保持不变：

```bash
uv venv
Using CPython 3.12.12
Creating virtual environment at: .venv
Activate with: source .venv/bin/activate
```

Windows 下已观察到的 `.venv/pyvenv.cfg` 信息：

```text
implementation = CPython
uv = 0.11.18
version_info = 3.12.13
include-system-site-packages = false
prompt = finfact_io
```

macOS/Linux 下已观察到的 `.venv/pyvenv.cfg` 信息：

```text
implementation = CPython
uv = 0.10.2
version_info = 3.12.12
include-system-site-packages = false
prompt = finfact-io
```

工作时优先按当前系统选择对应激活方式。Windows PowerShell 优先使用：

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.\.venv\Scripts\Activate.ps1
python --version
```

macOS/Linux 优先使用：

```bash
source .venv/bin/activate
python --version
```

如果后续需要初始化 Python package，优先使用 `uv` 管理依赖、运行测试和构建：

```bash
uv init --package
uv add ...
uv run pytest
```

不要假设仓库已有 `pyproject.toml`、`src/`、测试目录或包结构；在撰写本文件时，仓库基本为空，仅有 `.git`、`.venv`，以及本 `AGENTS.md`。

## 数据源目录

必须重点读取和理解下面这个本地原始数据总目录，以及其中两个核心子目录：

```text
/data/A-share/raw_data_tb
/data/A-share/raw_data_tb/指数数据
/data/A-share/raw_data_tb/A股数据_每日指标
```

这些目录在仓库外部，是本项目的原始数据源目录。代码可以读取它们，但不要把大型 zip 或 CSV 原始数据复制进仓库；不要在这些源目录里写入、覆盖、删除文件，除非用户明确要求。

建议后续库支持显式传入数据根目录，并支持环境变量覆盖：

```text
FINFACT_RAW_DATA_DIR=/data/A-share/raw_data_tb
FINFACT_INDEX_DATA_DIR=/data/A-share/raw_data_tb/指数数据
FINFACT_ASHARE_DAILY_DIR=/data/A-share/raw_data_tb/A股数据_每日指标
```

默认路径应指向上述 `/data/A-share/raw_data_tb` 原始数据总目录，并由统一的 catalog/config/path resolver 派生核心子目录。路径优先级应为：显式传入的具体数据集目录、具体数据集环境变量、`FINFACT_RAW_DATA_DIR` 下的约定子目录、包内默认路径。API 设计上不要把路径写死到深层函数里。

## 已观察到的数据布局

### `/data/A-share/raw_data_tb/A股数据_每日指标`

顶层包含：

```text
交易日历.csv
股票列表.csv
退市股票列表.csv
每日指标.zip
技术因子_前复权.zip
技术因子_后复权.zip
增量数据/
```

已观察到：

- `股票列表.csv` 与 `退市股票列表.csv` 是 UTF-8 BOM CSV，表头包括 `TS代码`、`股票代码`、`股票名称`、`地域`、`所属行业`、`股票全称`、`英文全称`、`拼音缩写`、`市场类型`、`交易所代码`、`交易货币`、`上市状态`、`上市日期`、`退市日期`、`沪深港通标的`、`实控人名称`、`实控人企业性质`。
- `交易日历.csv` 表头为 `交易所`、`日期`、`是否交易`、`上一个交易日`，日期格式是 `YYYY-MM-DD`。
- `每日指标.zip` 是按股票代码分文件的历史包，zip 内有 5861 个 CSV，例如 `000001.SZ.csv`、`000002.SZ.csv`、`688001.SH.csv`、`920992.BJ.csv`。
- `技术因子_前复权.zip` 和 `技术因子_后复权.zip` 也是按股票代码分文件，zip 内均为 5860 个 CSV。
- `增量数据/每日指标/<YYYY-MM>/<YYYYMMDD>.csv` 是按交易日分文件，例如 `增量数据/每日指标/2026-06/20260603.csv`。
- `增量数据/每日指标` 当前已观察到 8679 个按日文件，日期范围为 1990-12-19 到 2026-07-08。
- `增量数据/技术因子_后复权/<YYYY-MM>/技术因子_<YYYYMMDD>.csv` 是按交易日分文件，当前已观察到日期范围为 2026-05-22 到 2026-07-08。当前未观察到 `增量数据/技术因子_前复权` 目录，不能假设它一定存在。

`每日指标.zip` 内单个股票 CSV 表头包括：

```text
股票代码,交易日期,开盘价,最高价,最低价,收盘价,昨收价,涨跌额,涨跌幅,
成交量(手),成交额(千元),换手率,换手率(自由流通股),量比,
市盈率,市盈率TTM,市净率,市销率,市销率TTM,股息率,
股息率TTM,总股本(万股),流通股本(万股),自由流通股本(万股),
总市值(万元),流通市值(万元)
```

这是个股市值、市净率、市盈率等数据的核心来源之一。主键应视为：

```text
(股票代码, 交易日期)
```

`技术因子_前复权.zip` 和 `技术因子_后复权.zip` 的表头包括：

```text
股票代码,交易日期,开盘价,最高价,最低价,收盘价,成交量(手),成交额(千元),
涨跌幅(%),换手率(%),量比,复权因子,MA5,MA10,MA20,MA60,EMA5,EMA10,...
```

技术因子数据应带上复权类型维度，主键可视为：

```text
(股票代码, 交易日期, 复权类型)
```

### `/data/A-share/raw_data_tb/指数数据`

顶层包含指数基本信息、指数/行业行情 zip、行业分类、指数成分、增量数据等：

```text
指数基本信息_MSCI指数.csv
指数基本信息_上交所指数.csv
指数基本信息_中证指数.csv
指数基本信息_中金指数.csv
指数基本信息_其他指数.csv
指数基本信息_深交所指数.csv
指数基本信息_申万指数.csv
指数日线行情.zip
指数周线行情.zip
指数月线行情.zip
大盘指数每日指标/
申万行业日线行情.zip
中信行业日线行情.zip
申万行业分类/
中信行业分类/
申万行业成分_每日更新/
上交所指数成分/
深交所指数成分/
中证指数成分/
增量数据/
```

已核验这些指数基本信息文件均可用 `utf-8-sig` 读取，共同表头为：

```text
指数代码,简称,市场,发布方,指数类别,基期,基点,发布日期
```

读取 CSV 时仍应保留备用编码和清晰错误信息：优先尝试 `utf-8-sig`，失败再尝试 `utf-8`、`gb18030` 或可配置编码；如果必须容错替换字符，应记录 warning，不要静默吞掉编码问题。

`指数日线行情.zip` 是按指数代码分文件的历史包，zip 内有 6947 个 CSV，例如：

```text
000001.SH.csv
000300.SH.csv
399001.SZ.csv
930050.CSI.csv
h30001.CSI.csv
```

`指数周线行情.zip` 与 `指数月线行情.zip` 也是按指数代码分文件，分别有 2256 个和 2262 个 CSV。

指数日/周/月线行情表头包括：

```text
指数代码,交易日期,收盘点位,开盘点位,最高点位,最低点位,
昨日收盘点,涨跌点,涨跌幅(%),成交量(手),成交额(千元)
```

主键应视为：

```text
(指数代码, 交易日期, 频率)
```

`大盘指数每日指标/` 是少量主要指数和板块指数的每日指标明细，例如 `沪深300.csv`、`中证500.csv`、`上证50.csv`、`上证综指.csv`。表头包括：

```text
指数代码,交易日期,总市值(元),流通市值(元),总股本(股),流通股本(股),
自由流通股本(股),换手率,换手率(自由流通),市盈率,市盈率TTM,市净率
```

这是指数层面总市值、流通市值、市盈率、市净率等数据的核心来源之一。主键应视为：

```text
(指数代码, 交易日期)
```

`申万行业日线行情.zip` 是按申万行业指数代码分文件，zip 内有 430 个 CSV。表头包括：

```text
指数代码,交易日期,行业名称,开盘点位,最高点位,最低点位,收盘点位,
涨跌点位,涨跌幅,成交量(万股),成交额(万元),市盈率,市净率,
流通市值(万元),总市值(万元)
```

这是申万行业层面估值和市值数据的核心来源。主键应视为：

```text
(指数代码, 交易日期)
```

`中信行业日线行情.zip` 是按中信行业指数代码分文件，zip 内有 582 个 CSV。表头包括：

```text
指数代码,交易日期,开盘点位,最高点位,最低点位,收盘点位,
昨日收盘点位,涨跌点位,涨跌幅,成交量(万股),成交额(万元)
```

中信行业行情本身不包含市盈率、市净率、总市值等估值字段；如需要行业名称、层级、成分股，必须结合 `中信行业分类/` 下的分类文件。

`中信行业分类/中信行业分类_行业层级表.csv` 表头为：

```text
指数代码,行业名称,行业分级,行业代码,是否发布指数,父级代码
```

`中信行业分类/中信行业分类_成分股_全部_CITIC.csv` 表头为：

```text
一级行业代码,一级行业名称,二级行业代码,二级行业名称,三级行业代码,三级行业名称,
股票代码,股票名称,纳入日期,剔除日期,是否最新
```

`申万行业分类/` 包含 `申万行业分类_L1_SW2021.csv`、`申万行业分类_L2_SW2021.csv`、`申万行业分类_L3_SW2021.csv`。表头包括：

```text
指数代码,行业名称,行业分级,行业代码,是否发布指数,父级代码,分类来源
```

`申万行业成分_每日更新/<YYYY-MM>/申万行业成分_<YYYYMMDD>.csv` 是按交易日分文件，表头包括：

```text
一级行业代码,一级行业名称,二级行业代码,二级行业名称,三级行业代码,三级行业名称,
股票代码,股票名称,纳入日期,剔除日期
```

`上交所指数成分/`、`深交所指数成分/`、`中证指数成分/` 是按成分日期打包的 zip 目录。已观察到最新样本为 `*_20260630.zip`，zip 内再按指数代码分 CSV。表头为：

```text
指数代码,成分股票代码,交易日期,权重
```

主键应视为：

```text
(指数代码, 成分股票代码, 交易日期)
```

`指数数据/增量数据/` 包含：

```text
大盘指数每日指标/
指数日线行情/
申万行业日线行情/
中信行业日线行情/
```

增量目录通常按 `<YYYY-MM>/<YYYYMMDD>_指数日线行情.csv` 组织，是按交易日聚合的横截面文件。当前已观察到 `指数日线行情` 增量日期范围为 2026-01-02 到 2026-07-08，`大盘指数每日指标` 为 2025-09-19 到 2026-07-08，`申万行业日线行情` 为 2025-09-19 到 2026-07-08，`中信行业日线行情` 为 2019-11-29 到 2026-07-08。读取历史包与增量数据时，必须考虑同一主键重复的情况；如果历史包和增量文件都有同一条记录，应明确去重策略，通常以增量文件为较新来源优先。

## 数据读取原则

1. 使用 `pathlib.Path` 管理路径，不要手写字符串拼接路径。
2. 中文文件名和中文列名必须原样支持。
3. CSV 读取应优先尝试 `utf-8-sig`，再尝试 `utf-8`、`gb18030` 或可配置编码；如果必须容错替换字符，应记录 warning。
4. 日期字段主要有两类：`YYYYMMDD` 和 `YYYY-MM-DD`。读入后应规范化为 `datetime.date` 或稳定的日期类型，但保留原始字段能力。
5. 空字符串、缺失估值、停牌或退市导致的空值必须保持为缺失值，不要用 0 替代。
6. 大型 zip 不要一次性全量解压到仓库或源目录。优先使用 `zipfile`、流式读取、按代码/日期选择性读取。
7. 不要依赖 `ls` 输出顺序表达业务顺序；需要按日期排序时，从文件名或字段中解析日期。
8. 任何合并历史包和增量文件的逻辑都必须显式去重，并保留来源信息或可调试路径。

## 推荐库结构

后续实现建议采用 `src` layout：

```text
finfact-io/
  pyproject.toml
  AGENTS.md
  src/
    finfact_io/
      __init__.py
      config.py
      catalog.py
      readers/
        csv.py
        zip_csv.py
      datasets/
        ashare.py
        index.py
        industry.py
        constituents.py
      schema.py
      fields.py
      errors.py
  tests/
    fixtures/
    test_*.py
```

职责建议：

- `config.py`：定义数据根目录、环境变量、默认路径。
- `catalog.py`：集中声明所有已知数据集、文件名模式、zip 包、增量目录。
- `readers/csv.py`：普通 CSV 的编码检测、字段读取、日期解析。
- `readers/zip_csv.py`：zip 内 CSV 枚举、按 member 读取、按代码读取、按日期读取。
- `datasets/ashare.py`：股票列表、退市股票列表、交易日历、每日指标、技术因子。
- `datasets/index.py`：指数基本信息、指数日/周/月行情、大盘指数每日指标。
- `datasets/industry.py`：申万/中信行业分类、行业行情、行业成分。
- `datasets/constituents.py`：上交所、深交所、中证指数成分。
- `schema.py`：核心字段、主键、数据类型、列名别名。
- `fields.py`：中文原始列名到英文规范字段的映射。
- `errors.py`：定义清晰的异常，例如数据根目录不存在、代码不存在、日期范围无数据、编码失败。

## API 设计方向

首要目标是“提取数据”，不是先做复杂计算。API 应先稳定地解决这些问题：

- 给定股票代码与日期范围，读取个股每日指标。
- 给定股票代码、复权类型与日期范围，读取技术因子。
- 给定指数代码、频率与日期范围，读取指数行情。
- 给定指数代码与日期范围，读取指数估值/市值指标。
- 给定行业体系（申万/中信）、层级、日期范围，读取行业分类、行业成分和行业行情。
- 给定指数代码和成分日期，读取指数成分及权重。
- 给定交易所和日期范围，读取交易日历。

建议的高层用法形态：

```python
from finfact_io import FinfactStore

store = FinfactStore(
    raw_data_dir="/data/A-share/raw_data_tb",
)

df = store.ashare.daily_metrics("000001.SZ", start="2024-01-01", end="2024-12-31")
df = store.ashare.technical_factors("000001.SZ", adjustment="qfq")
df = store.index.market_metrics("000300.SH", start="2020-01-01")
df = store.index.bars("000300.SH", freq="day")
df = store.industry.sw_daily("801010.SI")
df = store.constituents.index_members("000300.SH", date="2026-06-30")
```

返回值可优先选择 `pandas.DataFrame`，但底层读取层不要和 pandas 过度耦合；如果数据量较大，后续可以支持 `polars` 或 `pyarrow`。无论返回什么结构，都必须提供原始中文列名可用性，并可以选择输出规范化英文字段。

建议提供字段别名，例如：

```text
股票代码 -> symbol
指数代码 -> index_code
交易日期 -> trade_date
总市值 / 总市值(元) / 总市值(万元) -> total_market_cap
流通市值 / 流通市值(元) / 流通市值(万元) -> float_market_cap
市净率 -> pb
市盈率 -> pe
市盈率TTM -> pe_ttm
成交额(千元) / 成交额(万元) -> amount
成交量(手) / 成交量(万股) -> volume
```

注意单位差异非常重要：个股每日指标里的 `总市值(万元)`、`流通市值(万元)`，大盘指数每日指标的 `总市值(元)`，以及申万行业日线行情的 `总市值(万元)` 单位不同。规范字段必须带上单位元数据，不能只改列名后混用。

## 实现注意事项

- 优先实现小而可靠的 IO 层，再实现便利查询层。
- 不要先把所有 zip 读进内存。按代码读取历史包时，只打开目标 member。
- 对“按代码分文件”的历史包和“按日期分文件”的增量目录，分别建索引，然后在查询层统一输出。
- 对日期范围过滤，应尽可能在读取后立即过滤，避免无谓保留大表。
- 对文件不存在、member 不存在、日期无数据、字段缺失等情况，抛出有上下文的异常。
- 保留原始文件路径或 zip member 信息，有助于排查数据来源。
- 不要把金融代码当作数字处理。股票代码、指数代码必须保持字符串，例如 `000001.SZ` 不能变成 `1`。
- 不要删除退市股票；退市股票在历史研究中仍然重要。`退市股票列表.csv` 与 `每日指标.zip` 内的退市代码都需要支持。
- 对 `BJ`、`SH`、`SZ`、`CSI`、`SI`、`CI`、小写 `h` 前缀等代码形态保持开放，不要写过窄正则。
- 任何缓存都应可关闭、可重建、可定位；不要让缓存成为唯一数据来源。

## 测试要求

后续开发必须添加自动化测试。不要把真实大型数据复制到 `tests/fixtures`。应构造很小的 CSV/zip fixture，覆盖真实数据的结构特征。

至少测试：

- UTF-8 BOM CSV 正常读取。
- 备用编码路径或编码异常路径能给出 warning 或可诊断错误。
- zip 内按 member 读取单个代码文件。
- 按日期分增量 CSV 的读取与日期解析。
- 历史包与增量数据同主键去重。
- `YYYYMMDD` 与 `YYYY-MM-DD` 两种日期格式。
- 股票/指数代码保持字符串。
- 空估值字段保持缺失值。
- 路径不存在、zip member 不存在、字段缺失时错误信息清晰。

如果写集成测试读取用户本地真实目录，必须默认跳过，只有显式设置环境变量时才运行，例如：

```bash
FINFACT_RUN_LOCAL_DATA_TESTS=1 uv run pytest
```

## 验证方式

每次改动后，根据改动范围选择验证：

```bash
uv run pytest
uv run python -m finfact_io...
```

如果还没有 package 和测试框架，至少用最小 smoke check 验证：

```bash
python - <<'PY'
from pathlib import Path
print(Path('/data/A-share/raw_data_tb').exists())
print(Path('/data/A-share/raw_data_tb/指数数据').exists())
print(Path('/data/A-share/raw_data_tb/A股数据_每日指标').exists())
PY
```

不要在没有运行任何验证的情况下宣称功能完成。

## 开发优先级

建议按以下顺序推进：

1. 初始化 Python package 与基础测试框架。
2. 实现 `FinfactStore` 配置对象和数据根目录校验。
3. 实现普通 CSV 与 zip CSV 的统一读取工具。
4. 实现股票列表、退市股票列表、交易日历读取。
5. 实现个股每日指标历史包读取。
6. 实现个股每日指标增量读取，并与历史包合并去重。
7. 实现指数基本信息、指数行情、大盘指数每日指标读取。
8. 实现申万行业分类、申万行业行情、申万行业成分读取。
9. 实现中信行业分类、中信行业行情读取。
10. 实现上交所、深交所、中证指数成分读取。
11. 增加字段别名、单位元数据、文档示例。

## 代码风格

- Python 代码使用类型标注。
- 使用 `pathlib.Path`、`dataclasses` 或清晰的轻量模型。
- 对 CSV/zip 这类结构化数据，使用标准库、pandas、polars 或 pyarrow 等结构化 API，不要用脆弱的字符串切分。
- 函数命名用英文，文档和注释可以用中文解释金融字段。
- 保持接口稳定、错误信息明确、实现可测试。
- 不做无关重构，不引入与 IO 目标无关的服务、前端或数据库。

## 重要提醒

这个项目的价值在于把“分散、本地、中文字段、压缩包、大量小文件”的金融文本数据变成可靠、可查询、可组合的 Python IO 接口。后续所有实现都应围绕这一点：先读对，再读稳，再读快。
