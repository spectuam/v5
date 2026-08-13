# margin_factor 执行记录（融资融券因子分析）

> 起：2026-07-21
> 需求：桌面 docs/_archive/02_分支探索/margin_factor_需求.md
> 独立目录：`/home/soso/v5/margin_factor/`（不与其他验证混）
> 环境：~/v5/.venv，数据 ~/ading/db/tdx_stock_data.db（margin_detail 表）
> 数据源：akshare（融资融券，独立于 tdx 量价）

---

## 背景

OHLCV 榨干（v5 分位 0.51，动量 2.5 年 0.40）。换数据源：融资融券（独立信息源，akshare 免费 T+1，研究 IC -4%~-7%）。

## 跑前测试

- akshare 1.18.64 接口可用（沪市 1760/天，深市 1818/天）
- 沪深字段不同：沪市 9 字段（含融资偿还额/融券偿还量），深市 8 字段（无，有融券余额）。映射统一，深市缺填 None
- daily_kline 无流通市值：RZ_ratio/RQ_ratio/RZ_DTC 3 因子需要，先跑 7 个不需的（含 RZ_buy_ratio 聚源最强），3 个待补

## Phase 1：数据拉取

- 脚本：`margin_pull.py`
- 方法：akshare stock_margin_detail_sse/szse，2023-2026，沪深映射，断点续传，代码加 sh/sz 前缀
- 表：`margin_detail`（code, date, rz_ye, rz_buy, rz_repay, rq_yl, rq_sell, rq_repay；深市 rz_repay/rq_repay=None）
- **完成**：318 万行，856 天（2023-01-03~2026-07-17），4449 标的。沪 156 万 + 深 162 万。akshare 靠谱（856 天只 1 次深市 ERR：2026-01-09 Connection reset，0.1%）

## Phase 2+3：因子 + IC

- 脚本：`margin_factors_ic.py`
- 7 因子：RZ_buy_ratio, RZ_chg_1d/5d/20d, RQ_chg_5d, RQ_sell_ratio, RZ_RQ_ratio

| factor | T1 IC/ICIR | T20 IC/ICIR |
|--------|-----------|-------------|
| **RZ_buy_ratio**（聚源最强）| -0.0654/-0.45 | -0.0941/-0.65 |
| RZ_chg_20d | -0.0268/-0.37 | -0.0411/-0.61 |
| cum_ret_20（OHLCV 对比）| -0.0384/-0.21 | -0.0573/-0.35 |

- RZ_buy_ratio IC -6.5%~-9.4%，ICIR -0.45~-0.65，**远超 OHLCV**（-3.8%~-5.7%，ICIR -0.21~-0.36）。超聚源预期（-6.66%）
- IC 负（融资买入多->未来跌，反向）：选股选 RZ_buy_ratio 最低
- RZ_RQ_ratio IC 正（+0.01~+0.05，多空比高->未来涨）

## Phase 4：回测三步

1. **扩展测试期**（`margin_backtest_extended.py`）：RZ_buy_ratio 全段 0.5076（稳定，分年 0.50-0.51），但 0.51 没到 0.70
2. **调选股**（`margin_backtest_quantile.py`，Top20/50/100）：0.530-0.531，略升没突破
3. **多因子组合**（`margin_backtest_combo.py`，rank 合成）：0.471/0.492，反而降

IC 强但回测 0.51 背离（rank IC 显著但选股超额弱）。

## Phase 5：LightGBM + 组合

- **LightGBM 多因子**（`margin_lightgbm.py`）：AUC 0.5332（弱），回测 Top10=0.524 / Top50=0.528。没提升
- **融资融券×OHLCV 组合**（`margin_combo_ohlcv.py`）：Top10=0.519 / Top50=0.519。没突破

都没到 0.70，和单因子(0.51)相当。

## 结论

融资融券 IC 强（-0.094，ICIR -0.65）且稳定（全段 0.51，分年 0.50-0.51），但回测 0.51-0.53，LightGBM/组合/调选股都没突破 0.70。**IC 强但回测背离**（rank IC 显著但选股超额弱）。可能 0.70 在现有数据（OHLCV+融资融券）下达不到。

## 下一步

1. 补流通市值（RZ_ratio/RQ_ratio，需拉数据，涉及数据源问题）
2. 加更多数据（龙虎榜/北向/事件）
3. 接受 0.51-0.53

## 产物（脚本归档 `/home/soso/v5/margin_factor/`）

- `margin_pull.py`（数据拉取）
- `margin_factors_ic.py`（因子+IC）
- `margin_backtest.py`（3月回测）
- `margin_backtest_extended.py`（全段+分年）
- `margin_backtest_quantile.py`（Top20/50/100）
- `margin_backtest_combo.py`（多因子rank合成）
- `margin_lightgbm.py`（LightGBM多因子）
- `margin_combo_ohlcv.py`（融资融券×OHLCV组合）
- 各 `*_result.json` / `*_run.log`

数据：`margin_detail` 表（tdx_stock_data.db）
