# v5 系统使用手册（2026-08-12）

> 日期：2026-08-12 · 整理：cc
> 性质：v5 系统搭建与使用手册，供 DSF/未来 LLM/接手者实操参考
> 关联：`docs/v5收尾实施记录-cc.md`（怎么来的）· `docs/v5系统定位.md`（定位）· `docs/策略评估管道SOP.md`（管道契约）

---

## 一、系统定位

**v5 = 程序性裁判系统 + 输出四件套**。证伪主义（淘汰不行的，不证真最好），不越权推荐。

**四件套**：结果 / 口径 / 可信度 / 证伪判定。口径显式化是核心设计（成熟系统口径隐性，v5 显式输出）。

**产出边界**：只输出"死了/未死"程序性结论 + 证据，不输出"推荐买什么"。

---

## 二、架构总览

```
阶段1 因子筛选(funnel)        候选因子集 + 候选策略returns
  ↓
阶段2 候选执行(collect_*/strategy_factory)  candidates_returns.json(毛收益source of truth)
  ↓
阶段3 成本复核(compare_pool + cost_utils)  compare_pool_result.json(净口径+毛对照)
  ↓
阶段4 RQAlpha终审(export_holdings -> rq_executor -> rq_terminal_review)  真实撮合
  ↓
阶段5 验证(walk-forward + forward tracker)  OOS可信度
  ↓
阶段6 证伪判定(four_piece_schema)  四件套
  ↓
阶段7 报告(report_generator)  四件套HTML
```

**顺序原则**：内容做对(A) -> SOP蓝图(B) -> 代码管道(C)。口径 config 沿管道显式传递。

---

## 三、环境搭建

### 3.1 运行环境
- **OS**：WSL2 (Linux 6.18 microsoft-standard)，内存 7-10GB（实测 9.9GB total）
- **Python**：`/home/soso/v5/.venv/bin/python3`（Python 3.12，专用 venv）
- **PYTHONPATH**：跑 ading 模块脚本需 `PYTHONPATH=/home/soso`（`from ading.config.paths import DB`）
- **项目根**：`/home/soso/v5`

### 3.2 关键依赖
- `rqalpha==6.3.0`（RQAlpha 回测引擎，bundle 在 `/home/soso/.rqalpha/bundle`）
- `akshare`（15min历史数据拉取，A股东财/新浪分钟数据）
- `scipy`/`numpy`/`pandas`/`plotly`（统计与绘图）
- factor_zoo: `/home/soso/.local/lib/python3.12/site-packages/src/factors`（`from factor_zoo_adapter import compute_alpha`）
- trading-strategy: `/home/soso/trading-strategy`（m15_snapshot 等采集脚本）

### 3.3 systemd timer（数据采集与推送）
| timer | 时间 | 作用 |
|---|---|---|
| m15-snapshot.timer | 9:45-14:45 每15min | 15min K线实时快照（新浪API） |
| m15-finalize.timer | 16:00 | 收盘后akshare补全当日15min |
| sync-daily.timer | (日) | 日线数据同步 |
| daily-pick.timer | 14:45 | 推Top5选股飞书（**当前指向v4 run_daily_v4.py，非v5**） |
| daily-report.timer | 15:15 | 每日数据状态报告 |

⚠ 改 systemd 是危险操作，需老板确认。timer 配置在 `~/ading/infra/systemd/`。

---

## 四、数据层

### 4.1 两个 SQLite DB

**`~/ading/db/tdx_stock_data.db`**（3.3GB，v5回测主用）
- `daily_kline`：日K（code格式 `sh600000` 无点），列：code/date/open/high/low/close/volume/amount
- `stock_info`：股票信息（symbol/name/class/status），status='1'为活跃（注意含新股，与历史口径可能不一致）
- `adjustment_factor`：后复权因子（code/hfq_factor）
- `factor_ic_daily`/`factor_map`/`stock_sw2`/`triple_barrier_labels`/`doublers`/`margin_detail`等

**`~/ading/db/stock_data.db`**（4.2GB，15min数据）
- `kline_15m`：15min K线（code格式 `sh.600000` 有点），列：code/datetime/open/high/low/close/volume（**无amount**）
- `daily_kline`/`daily_kline_old`：日K（stock_data.db版）

### 4.2 kline_15m 口径（重要，有缺陷）

**混合口径**：
- 9:45-14:45 = **累计口径**（snapshot缺陷）：open=当日开盘(固定)、high=当日最高(固定)、low=累计最低(递减)、close=当前价、volume=累计成交量(递增)
- 15:00 = **真15min bar**（finalize补的，OHLCV是该15min的）

**原因**：`m15_snapshot.py` 的 `run_snapshot()` 用新浪实时API，写的是当日开盘+累计高低+当前价（非真15min bar）。`finalize_today()` 用akshare拉真bar，但 `INSERT OR IGNORE` 不覆盖已写的snapshot。

**验证方法**：
```python
# 查某日某股，看9:45-14:45的open是否固定=当日开盘
import sqlite3
db=sqlite3.connect('~/ading/db/stock_data.db')
for r in db.execute("SELECT substr(datetime,12,5) t,open,high,low,close FROM kline_15m WHERE code='sh.600000' AND datetime LIKE '2026-08-11%' ORDER BY datetime"):
    print(r)  # open应全=9.27, high全=9.34
```

### 4.3 数据采集
- **15min**：`/home/soso/trading-strategy/m15_snapshot.py`（timer触发，见3.3）
- **日线**：sync-daily.service
- **Sina实时**：`_pull_sina_today()`（daily_pick/strategy_factory用）

---

## 五、管道模块详解

### 5.1 阶段1 因子筛选 `funnel.py`
- **路径**：`branches/compare/funnel.py`
- **输入**：double_selection_result/ir_result/fdr_result/monotonicity_result/factor_returns_week/factor_returns_top_30
- **输出**：`funnel_result.json` + 合并候选进 `candidates_returns.json`（funnel_top5_eq_ls/eq_long/tsmom_long）
- **口径**：D去冗余 -> A/B/C打分 -> Top5因子 -> 三策略（E路经济先验已删，2026-08-15决策：经济合理性论证是文献人工作业，管道运行时无人工判断，且实现为空壳）
- **跑**：`python3 branches/compare/funnel.py`

### 5.2 阶段2 候选执行（多脚本，写 candidates_returns.json）

**`candidates_returns.json` 格式**：`{strategy_name: [[week, ret], ...]}`，ret=周组合收益率(小数，**毛收益source of truth，不扣成本**)

| 脚本 | 候选 | 数据源 | 耗时 |
|---|---|---|---|
| `collect_candidates.py` | tsmom_long_K{1,4,12,24} | factor_returns_week + top_30 | 秒级 |
| `collect_heterogeneous.py` | tsmom_ls_K12, eq38_ls | factor_returns_week | 秒级 |
| `market_benchmark.py` | market_eq | DB daily_kline | ~10min |
| `lowvol_weekly.py` | lowvol_weekly | DB daily_kline | ~10min |
| `phase2_weekly.py` | phase2_ic_weekly | IC选股 | - |
| `strategy_factory.py --backtest` | daily_pick_eqcomposite_top5 | DB+因子预算 | ~10min |

⚠ market_benchmark/lowvol/strategy_factory 碰DB重计算，避免与其他重任务并行（内存碰撞）。

### 5.3 阶段3 成本复核 `compare_pool.py`
- **路径**：`branches/compare/compare_pool.py`
- **输入**：`candidates_returns.json`(毛) + `cost_utils.py`
- **输出**：`compare_pool_result.json`（净口径主+毛对照）
- **口径**：candidates层扣固定 `ROUND_TRIP=round_trip_cost()=0.00102`（10.2bp/周，满换仓上界）。impact无持仓明细无法算（见RQAlpha）。
- **统计**：CPCV(purge+embargo+多split) + DSR(N_eff特征值) + MCS(block bootstrap) + Calmar + PBO + Spearman
- **跑**：`python3 branches/compare/compare_pool.py`（秒级，纯numpy）
- **结果字段**：每策略 sharpe_full(净)/sharpe_gross_full(毛)/sharpe_train/sharpe_oos/dsr/calmar/max_dd/cpcv_oos_dist；顶层 cost_model/n_eff/mcs_set/pbo

### 5.4 阶段4 RQAlpha终审（双层管道第二层）

**4a 持仓导出 `export_holdings.py`**
- **路径**：`branches/compare/export_holdings.py`
- **用法**：`python3 export_holdings.py --strategy tsmom --k 12 --top-pct 0.30 --name tsmom_ls_K12`
- **输出**：`{strategy, holdings: {week: {code_RQformat: weight}}}.json`（code格式 `600000.XSHG`）
- **已实现**：tsmom generator（参数化K/top_pct）
- **待实现**：daily_pick（用strategy_factory --export-holdings替代）/market_eq/lowvol

**daily_pick 持仓**（走strategy_factory）：
```bash
python3 strategy_factory.py --backtest --export-holdings
# 输出 branches/strategy_factory/daily_pick_holdings.json (534周,每周5只等权0.2)
```

**4b RQAlpha执行 `run_rq.py`**
- **路径**：`branches/compare/run_rq.py`
- **用法**：`python3 run_rq.py <holdings.json> <tag> [capital] [min_commission] [nolimit] [start] [end]`
- **策略文件**：`rq_executor.py`（通用，读HOLDINGS_PATH环境变量）
- **输出**：`rq_result_<tag>.pkl`（portfolio+trades）
- **真实撮合**：最低佣金/印花税/涨跌停(price_limit)/停牌/t+1/最小手数
- **示例**：`python3 run_rq.py branches/strategy_factory/daily_pick_holdings.json daily_pick_full 1e6 5.0 normal 2016-01-04 2026-06-30`

**4c 终审对比 `rq_terminal_review.py`**
- **用法**：`python3 rq_terminal_review.py --pkl <rq_result_tag.pkl> --strategy <name> [--nolimit-pkl <path>]`
- **输出**：三口径对比(毛/净candidates/RQAlpha真实) + 归因(需nolimit pkl)
- **示例**：`python3 rq_terminal_review.py --pkl branches/compare/rq_result_daily_pick_full.pkl --strategy daily_pick_eqcomposite_top5`

### 5.5 阶段5 验证
- `walkforward.py` -> `walkforward_result.json`（expanding factor_ic，OOS sharpe）
- `forward_tracker.py` -> `forward_track_result.json`（持续OOS积累）

### 5.6 阶段6 证伪判定 `four_piece_schema.json`
- **路径**：`branches/strategy_factory/four_piece_schema.json`
- **证伪门槛**：F1 DSR≥0.95 / F2 MCS集合内 / F3 forward衰减≤0.50。任一fail=死了。
- 自动判定逻辑见 `report_generator.py` 的 `falsify()` 和 `daily_pick_v5.py` 的 `falsify()`

### 5.7 阶段7 报告 `report_generator.py`
- **路径**：`branches/compare/report_generator.py`
- **跑**：`python3 branches/compare/report_generator.py`
- **输出**：`branches/compare/reports/v5_four_piece_report.html`（净值/毛净SR对照/DSR/alpha-beta/汇总表+证伪判定）
- **特点**：去硬编码(数字从JSON读)、净口径主、自动证伪判定、统一脚本

---

## 六、配置体系

### 6.1 `pipeline_config.json`（评估域，口径source of truth）
- **路径**：`branches/strategy_factory/pipeline_config.json`
- **内容**：period/freq/train_end/start/end/benchmark + cost_model两套 + falsification_thresholds
- **改口径改这里**，不改脚本
```json
{
  "cost_model": {
    "candidates_layer": {"round_trip_bp": 10.2, "assumption": "满换仓上界", "annual_drag_bp": 530},
    "rqalpha_layer": {"capital": 1000000, "min_commission": 5.0, "price_limit": true}
  },
  "falsification_thresholds": {"F1_dsr": 0.95, "F3_forward_decay": 0.50}
}
```

### 6.2 `strategy_config.json`（作者域，策略定义）
- **路径**：`branches/strategy_factory/strategy_config.json`
- **内容**：factor_set/panel/selection/signal/filters（因子集/lookback/TopK/投票/涨停过滤）
- **生产与回测共用**：`daily_pick_v5.py` 和 `strategy_factory.backtest` 读同一份，口径匹配

### 6.3 作者域 vs 评估域（分域框架）
- **作者域**（策略定义）：factor_set/组合/选股/周期/频率 -> strategy_factory config
- **评估域**（口径）：成本/基准/资金/时段/年化 -> compare_pool 口径参数 / pipeline_config

---

## 七、使用流程

### 7.1 一键跑全管道（编排器）
```bash
cd /home/soso/v5
python3 branches/strategy_factory/orchestrator.py --list                    # 看阶段
python3 branches/strategy_factory/orchestrator.py --stage compare_pool       # 跑单阶段
python3 branches/strategy_factory/orchestrator.py --from compare_pool --to rq_review  # 跑范围
python3 branches/strategy_factory/orchestrator.py --strategy tsmom_K12 --stage export_holdings  # 带策略
```
**阶段**：funnel -> collect -> compare_pool -> export_holdings -> rq_executor -> rq_review

### 7.2 单步跑
```bash
# 成本复核（秒级）
python3 branches/compare/compare_pool.py

# 导tsmom持仓（秒级）
python3 branches/compare/export_holdings.py --strategy tsmom --k 12 --name tsmom_ls_K12

# RQAlpha终审（5-15min，Top5快/多因子慢）
python3 branches/compare/run_rq.py <holdings.json> <tag> 1e6 5.0 normal 2016-01-04 2026-06-30

# 三口径对比
python3 branches/compare/rq_terminal_review.py --pkl branches/compare/rq_result_<tag>.pkl --strategy <name>

# 生成报告
python3 branches/compare/report_generator.py
```

### 7.3 daily_pick 生产推送（改造版）
```bash
python3 /home/soso/v5/daily_pick_v5.py
# 推候选证伪状态报告到飞书（非选股）。需 compare_pool_result.json + rq_review_daily_pick_eqcomposite_top5.json
```
⚠ timer 当前推 v4 Top5（run_daily_v4.py），非此脚本。此脚本手动/cron触发。

### 7.4 验证RQAlpha管道正确性
```bash
python3 branches/compare/verify_rq_align.py verify_e8 e8_3y
# 对比 rq_executor产出 vs DSF e8_3y（同配置），确认泛化正确
```

---

## 八、维护

### 8.1 数据采集检查
```bash
# daily_kline 最近15天（tdx_stock_data.db）
python3 -c "
import sqlite3
db=sqlite3.connect(os.path.expanduser('~/ading/db/tdx_stock_data.db'))
print(db.execute('SELECT MAX(date) FROM daily_kline').fetchone()[0])
for r in db.execute(\"SELECT substr(date,1,10) d, COUNT(DISTINCT code) FROM daily_kline WHERE date>=date('now','-15 days') GROUP BY d ORDER BY d\"): print(r)
"

# kline_15m 最近15天（stock_data.db）
python3 -c "
import sqlite3
db=sqlite3.connect(os.path.expanduser('~/ading/db/stock_data.db'))
print(db.execute('SELECT MAX(datetime) FROM kline_15m').fetchone()[0])
for r in db.execute(\"SELECT substr(datetime,1,10) d, COUNT(DISTINCT code),COUNT(*) FROM kline_15m WHERE datetime>=date('now','-15 days') GROUP BY d ORDER BY d\"): print(r)
"
```
正常：每天5203股票，15min约83248行（16根×5203）。异常时段（非9:45-15:00）=数据损坏。

### 8.2 15min重采（修复损坏）
```bash
# dry-run看影响
PYTHONPATH=/home/soso python3 /home/soso/trading-strategy/m15_refetch.py --date 2026-08-06 --dry-run

# 执行重采（累计口径+基准8/11股票5203）
PYTHONPATH=/home/soso python3 /home/soso/trading-strategy/m15_refetch.py --date 2026-08-06 --date 2026-08-07 --baseline 2026-08-11 --workers 10
```
**口径**：还原累计口径（9:45-14:45累计OHLCV，15:00真bar）。股票数对齐基准日（默认8/11的5203，不用stock_info现在的5530）。

### 8.3 日常检查清单
- daily_kline 最新日期 = 今日（交易日）
- kline_15m 最新 datetime = 今日 15:00
- 最近15天每天5203股票，无异常时段
- compare_pool_result.json 的 run_at 是最新
- systemd timer 状态：`systemctl --user list-timers` 或 `systemctl list-timers`（可能需sudo）

---

## 九、常见坑

1. **PYTHONPATH**：ading 模块脚本（m15_snapshot/m15_refetch）需 `PYTHONPATH=/home/soso`，否则 `No module named 'ading'`
2. **内存碰撞**：market_benchmark/lowvol/strategy_factory.backtest 碰DB重计算，勿与RQAlpha/其他重任务并行（WSL内存紧张时OOM）
3. **code格式**：tdx_stock_data.db 用 `sh600000`（无点），stock_data.db 用 `sh.600000`（有点），RQAlpha 用 `600000.XSHG`。转换：`code.replace('.','')` / `code_to_rq()`
4. **kline_15m 无amount**：只有volume。daily_kline 有amount
5. **RQAlpha pkl 大**：多因子策略pkl可达600MB+，`.gitignore` 排除 *.pkl
6. **n_eff=1.94**：13候选同源，池内择优无统计意义，MCS只能淘汰。不要试图"选最优"
7. **daily_pick 已证伪**：真实口径SR-0.441亏损。timer仍推v4 Top5（老板定保持），非v5评估结论
8. **cost_utils 10.2bp**：年化5.3%（非53%）。candidates层固定费率，真实成本见RQAlpha
9. **DSR门槛**：DSR≥0.95=未死（高=SR显著）。计划旧文档"DSR<0.95=未死"是笔误，已修正
10. **systemd 改动**：危险操作，需老板确认。timer配置在 ~/ading/infra/systemd/

---

## 十、关键文件索引

| 类别 | 文件 |
|---|---|
| 管道 | branches/compare/{funnel,collect_*,compare_pool,export_holdings,run_rq,rq_executor,rq_terminal_review,report_generator}.py |
| 成本 | branches/cost_layer/cost_utils.py |
| 编排 | branches/strategy_factory/{orchestrator.py,pipeline_config.json,strategy_factory.py,strategy_config.json} |
| 四件套 | branches/strategy_factory/four_piece_schema.json |
| 生产 | daily_pick_v5.py（改造版推候选报告） |
| 采集 | ~/trading-strategy/{m15_snapshot.py,m15_refetch.py} |
| 文档 | docs/{v5收尾实施记录-cc.md,v5系统定位.md,策略评估管道SOP.md,v5策略生成器方向调研-cc.md} |
| 数据 | ~/ading/db/{tdx_stock_data.db,stock_data.db} |

## 关联
`v5收尾实施记录-cc.md`（怎么来的）· `v5系统定位.md`（定位）· `策略评估管道SOP.md`（管道契约）· `v5引擎对跑验证-cc.md`（成交现实/14pp）· memory `session-state-2026-08-12`
