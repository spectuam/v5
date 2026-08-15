# 策略评估管道 SOP（v5 收尾，B1）

> 冻结：2026-08-12（v5 收尾实施计划 B1）
> 依据：`docs/v5收尾实施计划.md` + `docs/v5系统定位.md` §七 + `docs/筛选流程SOP.md`(范式)
> 用途：策略评估从候选到证伪判定的完整管道，可复用。每步标注 IO 契约 + 口径 + 完整性。
> 性质：v5 定位=程序性裁判系统+四件套(证伪主义)。管道产出四件套，不越权推荐。
> 顺序原则：内容做对(A) -> SOP 蓝图(B) -> 代码管道(C)。

## 流程总览

```
阶段1 因子筛选(funnel)        产出候选因子集 + 候选策略 returns
  ↓
阶段2 候选执行(collect_*/strategy_factory)  产出 candidates_returns.json(毛收益)
  ↓
阶段3 成本复核(compare_pool + cost_utils)  产出 compare_pool_result.json(净口径, 毛/净双列)
  ↓
阶段4 第二引擎终审(RQAlpha)   export_holdings -> rq_executor -> rq_terminal_review
  ↓                          真实撮合(佣金/印花/涨跌停/停牌/最小手数)
阶段5 验证(walk-forward + forward tracker)  OOS 可信度
  ↓
阶段6 证伪判定(four_piece_schema)  四件套: 结果/口径/可信度/证伪判定
  ↓
阶段7 报告(report管道, C2)  四件套 HTML
```

**关键时序**：阶段3(成本)必须在阶段4(RQAlpha)前--成本口径分层清晰(固定费率 vs 真实撮合)，RQAlpha 补真实换手率/冲击。各阶段口径 config 沿管道显式传递(阶段 C1 编排器)。

## 阶段1 因子筛选（funnel）

- 脚本：`branches/compare/funnel.py`
- 输入：double_selection_result.json + ir_result.json + fdr_result.json + monotonicity_result.json + factor_returns_week.json + factor_returns_top_30.json
- 输出：`funnel_result.json`(top因子+综合排名) + 合并候选进 `candidates_returns.json`(funnel_top5_eq_ls / funnel_top5_eq_long / funnel_top5_tsmom_long)
- 口径：D去冗余 -> A/B/C打分 -> Top5因子 -> 三种策略(等权多空/等权多头/TSMOM多头)
- 完整性：四路(D∩A∩B∩C，A/B/C非硬筛用排名)，非单路选
- E路已删(2026-08-15决策)：经济合理性论证是文献人工作业(AHM前置论证)，违反管道运行时无人工判断原则；v5实现是名字规则分类+全True零剔除的空壳

## 阶段2 候选执行

各候选策略独立生成周收益，合并进 `candidates_returns.json`（毛收益，source of truth）：

| 候选 | 脚本 | 输入 | 口径 |
|---|---|---|---|
| tsmom_long_K{1,4,12,24} | collect_candidates.py | factor_returns_week.json + factor_returns_top_30.json | TSMOM信号多头, K变体 |
| tsmom_ls_K12 / eq38_ls | collect_heterogeneous.py | factor_returns_week.json | TSMOM多空 / 等权38因子多空 |
| market_eq | market_benchmark.py | DB daily_kline | 全市场等权 T+5 |
| lowvol_weekly | lowvol_weekly.py | DB daily_kline | vol_20最低Top10 T+5 |
| phase2_ic_weekly | phase2_weekly.py | (IC选股) | phase2 放行因子选股 |
| daily_pick_eqcomposite_top5 | strategy_factory.backtest | strategy_config.json + DB | 生产策略复合因子Top5 |

- 输出格式：`{strategy_name: [[week, ret], ...]}`，ret=周组合收益率(小数, 毛收益)
- 口径：全周度 T+5，对齐 compare_pool
- 完整性：**毛收益原始数据**(candidates_returns.json 不扣成本，成本在阶段3统一出口扣)

## 阶段3 成本复核（compare_pool + cost_utils）

- 脚本：`branches/compare/compare_pool.py`
- 输入：`candidates_returns.json`(毛收益) + `branches/cost_layer/cost_utils.py`
- 输出：`compare_pool_result.json`(净口径主指标 + 毛收益对照)
- 口径：**candidates 层扣固定 round_trip(10.2bp/周, 满换仓假设上界)**
  - `net_ret = gross_ret - round_trip_cost()`，所有指标(SR/DSR/CPCV/MCS/PBO)基于净收益
  - 保留 `sharpe_gross_full` 毛收益对照
  - impact 成本 candidates 层无法算(无持仓明细) -> 见阶段4 RQAlpha
- 成本模型字段：`cost_model.{layer, round_trip_bp, assumption, annual_drag_bp, impact}`
  - annual_drag_bp = 530(5.3%/年, 非53%)
- 完整性：毛/净双口径显式列 + 成本假设标注(满换仓上界, 真实换手率<100%)
- 统计：CPCV(purge+embargo+多split) + DSR(N_eff特征值校正) + MCS(block bootstrap) + Calmar + PBO + Spearman稳定性

## 阶段4 第二引擎终审（RQAlpha）

双层管道第二层：真实撮合补 candidates 层缺的真实换手率/冲击/涨跌停/停牌。

- 持仓导出：`branches/compare/export_holdings.py --strategy <type>`
  - 输出：`{strategy, holdings: {week: {code_RQformat: weight}}}.json`
  - 已实现 generator: tsmom(K/top_pct 参数化)
  - 待实现: daily_pick(需 strategy_factory 全历史因子预算) / market_eq / lowvol
- RQAlpha 执行：`branches/compare/run_rq.py <holdings.json> <tag> [capital] [min_commission] [nolimit] [start] [end]`
  - 策略文件：`rq_executor.py`(通用, 读 HOLDINGS_PATH 环境变量, 非硬编码)
  - 输出：`rq_result_<tag>.pkl`(portfolio + trades)
  - 真实撮合：最低佣金 / 印花税 / 涨跌停(price_limit) / 停牌 / t+1 / 最小手数
- 终审对比：`branches/compare/rq_terminal_review.py --pkl <pkl> --strategy <name> [--nolimit-pkl <path>]`
  - 三口径对比：毛收益 / 净收益(candidates固定) / RQAlpha真实
  - 归因(需 nolimit pkl)：费用(trades实测) + 涨跌停(含限制-无限制) + 停牌+其余
  - 输出：`rq_review_<strategy>.json`
- 完整性：两套成本口径(candidates固定 vs RQAlpha真实)在四件套"口径"显式列

## 阶段5 验证（walk-forward + forward tracker）

- walk-forward：`branches/strategy_factory/walkforward_result.json`(expanding factor_ic, OOS sharpe)
- forward tracker：`forward_track_result.json`(持续 OOS 积累)
- 完整性：OOS 真实持有期，非 IS 分布内 CPCV(后者对未来无验证效力)

## 阶段6 证伪判定（four_piece_schema）

- schema：`branches/strategy_factory/four_piece_schema.json`
- 四件套：结果(净SR/毛SR/MDD/换手/净值) + 口径(周期/成本模型两套/基准/资金/层) + 可信度(DSR_N_eff/MCS/PBO/walk-forward/forward衰减/N记账) + 证伪判定(verdict+evidence)
- 证伪门槛(见 schema falsification_thresholds)：
  | 规则 | pass(未死) | fail(死了) |
  |---|---|---|
  | F1 DSR | >=0.95(SR显著非运气) | <0.95(可能运气) |
  | F2 MCS | 策略在无法区分集合内 | 被排除 |
  | F3 forward衰减 | <=0.50 | >0.50 |
- 判定逻辑：任一 fail=死了；全 pass=未死_待forward积累(证伪主义：未死≠好)
- 完整性：程序性结论(死了/未死)，不推荐

## 脚本入口表

| 阶段 | 脚本 | 产出 |
|---|---|---|
| 1 筛选 | funnel.py | funnel_result.json + 候选进 candidates_returns |
| 2 执行 | collect_candidates/heterogeneous/market_benchmark/lowvol_weekly/strategy_factory | candidates_returns.json(毛收益) |
| 3 成本 | compare_pool.py + cost_utils.py | compare_pool_result.json(净口径) |
| 4 RQAlpha | export_holdings.py -> run_rq.py -> rq_executor.py -> rq_terminal_review.py | rq_result_*.pkl + rq_review_*.json |
| 5 验证 | (walkforward + forward_track) | walkforward_result.json |
| 6 证伪 | four_piece_schema.json | 四件套 |
| 7 报告 | (C2 report管道) | 四件套 HTML |

## 判定阈值表

| 阈值 | 值 | 来源 |
|---|---|---|
| DSR(证伪F1) | >=0.95 未死 | A3 schema |
| MCS(证伪F2) | 在集合内 未死 | A3 schema |
| forward衰减(证伪F3) | <=0.50 未死 | A3 schema |
| PBO | <0.50(过拟合警戒) | 设计 §4 |
| candidates固定 round_trip | 10.2bp/周(满换仓上界) | cost_utils |
| 年化成本拖累 | 530bp(5.3%/年) | A1实测 |
| RQAlpha 资金 | 1e6(最低佣金主导) / 1e8(冲击显现) | DSF 8/9 |

## 口径流转（config 沿管道显式传递）

```
strategy_config.json (因子集/TopK/涨停过滤/信号)
  -> strategy_factory.backtest (毛收益 returns)
  -> candidates_returns.json (毛收益 source of truth)
  -> compare_pool.py (扣固定 round_trip -> 净口径, 毛对照)
  -> compare_pool_result.json
  -> export_holdings.py (导持仓, 不算收益)
  -> rq_executor.py (RQAlpha 真实撮合)
  -> rq_result_*.pkl
  -> rq_terminal_review.py (三口径对比+归因)
  -> four_piece_schema (口径字段显式列两套成本模型)
```

## 完整性要求（不简化点）

1. candidates_returns.json 保持毛收益(不动原始数据)，成本在 compare_pool 统一出口扣
2. 毛/净双口径显式列(避免 8/8 虚高重演)
3. 两套成本模型(candidates固定 vs RQAlpha真实)在四件套"口径"显式列
4. DSR 按 N_eff 校正(特征值法, 非假设独立)
5. 证伪判定程序性(死了/未死)，不越权推荐
6. 8/8 "跑输市场"结论按真实口径重判(毛收益相对结论可能仍成立, 绝对数修正)

## 当前结论（A1 成本口径重算后）

- daily_pick 净SR0.24(毛0.40)，DSR 0.775(<0.95 -> 证伪F1 fail -> 死了)
- 多空策略受创最重: tsmom_ls 1.98->0.67, eq38_ls 1.00->0.16
- PBO 0.05->0.25(成本揭露过拟合)
- MCS无法区分集合 2->10个(扣成本后策略差异抹平)
- "跑输市场"成立: daily_pick净SR0.24 < market_eq净SR0.44
