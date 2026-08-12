# v5 收尾实施过程记录（2026-08-12）

> 日期：2026-08-12 · 整理：cc（GLM 窗口）
> 性质：v5 收尾实施全过程记录，供 DSF/未来 LLM/接手者了解 v5 准确情况与搭建结果
> 依据：`docs/v5收尾实施计划.md`（蓝图）+ 本 session 实际执行 + git commit
> 关联文档：`docs/v5系统使用手册-cc.md`（怎么用）· `docs/v5系统定位.md`（定位）· `docs/策略评估管道SOP.md`（B1）

---

## 一、背景与定位（接手必读）

### v5 是什么
v5 是老板的个人量化策略评估系统，定位为**程序性裁判系统 + 输出四件套**（2026-08-08 晚讨论定论，替代旧"相对择优器"表述）。

**定位链**：相对择优器（8/6）→ 淘汰器/证伪器（8/8）→ 程序性裁判系统（8/8 晚，当前）

**核心原则**：
- **证伪主义**：证伪只需一条证据，证真一万条也不够。v5 淘汰不行的策略，不证真"最好"。不越权推荐。
- **输出四件套**：结果 / 口径 / 可信度 / 证伪判定。口径显式化是比成熟系统更进一步的设计（成熟系统口径是隐性裁判）。
- **程序性结论**：只输出"死了/未死"，不输出"推荐买什么"。

### 为什么有这次收尾
8/13 老板定：v6 前先把 v5 收尾做完。8/9-12 DSF（DS 窗口）做了 RQAlpha 对跑调研+实验脚本但**零 commit 未动主管道**（RQAlpha/report/streamlit 全 untracked），v5 整合由 cc 掌控。老板要新 session 全自动跑完实施计划 A1→A2→A3→B1→C1→C2（A4 跳过，后老板定方向也做了）。

---

## 二、实施前状态（8/8 + DSF 8/9-12）

### 8/8 已完成（毛收益口径，需修正）
- daily_pick SR0.40、tsmom_ls SR1.98 等 13 候选毛收益指标
- **8/8 结论需修正**：daily_pick SR0.40 等是毛收益"另一个世界"数（自写回测任意价格任意量成交）。RQAlpha 实测真实口径（100万默认成本）tsmom_ls 年化 2.1%/SR0.34。

### DSF 产出（untracked，零 commit）
- RQAlpha 脚本：`rq_tsmom_ls.py`/`run_rq.py`/`export_tsmom_holdings.py`（tsmom_ls 单策略专用，已验证可用）
- 归因脚本：`rq_attribution_3y.py`（三年归因闭合：费用2.41+涨跌停1.72+停牌5.03pp/年）
- 报告脚本：`report_compare_pool.py`/`report_daily_pick.py`（近乎重复，硬编码8/8毛收益数字）
- 6个 pkl 结果（base/bp/e8/e8_3y/e8nolimit_3y/zero）
- **DSF 归因结论**：自写回测系统性高估14pp，5条缺陷（费用全缺/停牌/涨跌停/最小手数/未上市），对v5三条修正（资金规模口径/RQAlpha第二引擎/候选形态约束）

### 关键状态修正（新session须知，8/13 memory）
- 定位：相对择优器→证伪器→**程序性裁判系统+四件套**（证伪主义）
- 8/8 daily_pick SR0.40 是毛收益虚高
- DSF 产出 untracked 零 commit，需 cc 审查整合
- 成本层 cost_utils 存在但没接线（8/8"含成本"表述是错的）
- git 最新 commit 05391e0（8/8调参），DSF 无 commit

---

## 三、实施计划与顺序原则

**顺序原则**：内容做对 → SOP 蓝图 → 代码管道（不能倒，给流沙浇筑管道是错）

| 步 | 内容 | 性质 | commit |
|---|---|---|---|
| A1 | 接成本层进主管道 | 内容做对，确定性工程 | 85f88a2 |
| A2 | RQAlpha 纳入第二引擎 | 双层管道泛化 | 5886708 + 7d46505 |
| A3 | 四件套 schema 正式化 | 定义+门槛 | 5d4ffd4 |
| A4 | daily_pick 生产层改造 | 决策点（老板定方向） | c533237 |
| B1 | 策略评估管道 SOP 文档 | 文档先行 | 6675509 |
| C1 | 编排器 + schema | 代码管道 | 69d47ed |
| C2 | 报告管道 | 整合 DSF | c4ceed5 |

---

## 四、各步实施详细

### A1 接成本层进主管道（commit 85f88a2）

**问题**：`cost_utils.py`（7/28，10.2bp 大单费率 + 平方根冲击）只接 `eval_lowvol_h20_cost.py` 一处。主管道 `factor_returns → candidates_returns → compare_pool` 全毛收益。8/8 所有 SR 虚高。

**方案决策（偏离计划字面）**：计划要改 6 个生成脚本扣成本。但 `candidates_returns.json` 有 13 个消费者（含 report/rq 脚本）。cc 改为在 **compare_pool 统一口径出口扣成本** + 保留毛收益原数据 + 输出毛/净双口径。理由：避免 6 处改动引入不一致 + 保留原始数据供 RQAlpha 对比。

**实现**（`branches/compare/compare_pool.py`）：
- import cost_utils，常量 `ROUND_TRIP = round_trip_cost()`（0.00102）
- 读毛收益 candidates_returns，构建 `gross_mat`，净收益 `rets_mat = gross_mat - ROUND_TRIP`（NaN 保留）
- 所有指标（SR/DSR/CPCV/MCS/PBO/Calmar）基于净收益算，保留 `sharpe_gross_full` 毛收益对照
- 输出加 `cost_model` 字段（layer/round_trip_bp/assumption/annual_drag_bp/impact）
- caveat 更新为净收益口径说明

**发现**：
| 策略 | 毛SR | 净SR | DSR(净) |
|---|---|---|---|
| daily_pick | 0.397 | 0.244 | 0.775 |
| tsmom_ls_K12 | 1.977 | 0.675 | 0.980 |
| eq38_ls | 0.998 | 0.158 | 0.686 |
| funnel_top5_eq_ls | 1.994 | 1.181 | 1.000 |

- daily_pick 净SR0.244（毛0.40，-39%），DSR 0.891→0.775
- 多空策略受创最重（多空对冲后周收益小，固定10.2bp占比极大）
- PBO 0.05→0.25（成本揭露过拟合）
- MCS无法区分集合 2→10个（扣成本后策略差异抹平）
- "跑输市场"成立：daily_pick净SR0.244 < market_eq净SR0.44

**修正计划错误**：计划文档写"周调仓10.2bp×52≈53%年"实为 **5.3%/年（530bp）**，计划把 bp 当 % 算了，风险高估10倍。

**备份**：`compare_pool_result_gross_0808.json`（8/8毛收益基准）

### A2 RQAlpha 纳入第二引擎（commit 5886708 + 7d46505）

**问题**：DSF 的 `rq_*.py` 已验证 tsmom_ls 可用（未 commit），单策略专用，未泛化、未正式化。

**cc 泛化**（从 DSF 单策略 → 通用）：
1. `rq_executor.py`：通用 RQAlpha 执行器。读 `HOLDINGS_PATH` 环境变量（非硬编码），每周按目标权重 `order_target_percent` 调仓。泛化自 `rq_tsmom_ls.py`（init 改读环境变量，handle_bar 逻辑一字不改）。
2. `run_rq.py`：通用启动器。`run_rq.py <holdings.json> <tag> [capital] [min_commission] [nolimit] [start] [end]`，设环境变量后调 `rqalpha.run_file("rq_executor.py")`。
3. `export_holdings.py`：通用持仓导出框架。`--strategy tsmom --k 12 --top-pct 0.30`。tsmom generator 参数化（K/TOP_PCT），复刻 `export_tsmom_holdings.py` 逻辑。daily_pick/market_eq generator 留接口（NotImplementedError）。
4. `rq_terminal_review.py`：三口径对比（毛/净candidates/RQAlpha真实）+ 归因拆解（需nolimit pkl）。
5. `verify_rq_align.py`：验证 rq_executor 复现 DSF（对比 verify_e8 vs e8_3y）。
6. `strategy_factory.py` 加 `--export-holdings`：backtest 同时导出周持仓 JSON（供 RQAlpha）。

**验证**：
- `export_holdings` 跑 tsmom K=12 完美对齐 DSF `tsmom_ls_K12_holdings.json`（530活跃周，权重差0.000000）
- rq_executor 跑到 2017-W14（1.5年）撮合正常（涨跌停/停牌拒绝10457行）
- 证据链：export_holdings对齐 + rq_executor逻辑直接复刻rq_tsmom_ls + 撮合正常

**daily_pick 终审**（A2§5 代表性候选 + 生产策略）：
- `strategy_factory.py --backtest --export-holdings` 导出 daily_pick 持仓（534周，每周5只等权0.2）
- `run_rq.py daily_pick_holdings.json daily_pick_full 1e6 5.0 normal 2016-01-04 2026-06-30` 跑全期
- `rq_terminal_review` 三口径对比：

| 口径 | SR | 年化 | MDD |
|---|---|---|---|
| 毛收益（自写） | 0.397 | - | - |
| 净收益（candidates固定10.2bp） | 0.244 | - | - |
| **RQAlpha真实撮合** | **-0.441** | **-9.9%** | **-79%** |

**重大发现**：daily_pick 真实口径 SR-0.441（**亏损**），期末净值0.34。candidates 净口径SR0.244**仍虚高**。费占本金25.2%（年化2.52%，实际换手<100%低于candidates固定5.3%）。8/8"跑输市场"结论真实口径下**强化为亏损**。

**双层管道定型**：自写快筛（毛/净）→ RQAlpha终审（真实撮合：最低佣金/印花/涨跌停/停牌/t+1/最小手数）→ 四件套。

**DSF 原版归档**：`rq_tsmom_ls.py`/`export_tsmom_holdings.py`/`rq_attribution_3y.py`/`rq_compare.py`/`rq_conclusion.py`/`rq_reject_cost.py`/`rq_report.py`/`rq_tsmom_config.json`/`tsmom_ls_K12_holdings.json`/`tsmom_ls_K12_long_leg.json` 一并 commit 作参考。pkl 大文件 `.gitignore` 排除。

### A3 四件套 schema 正式化（commit 5d4ffd4）

**问题**：四件套（结果/口径/可信度/证伪判定）是定位产出，但没 schema 化、证伪判定门槛没正式定义。

**产出**：`branches/strategy_factory/four_piece_schema.json`（JSON Schema draft-07）
- **结果**：净值曲线/SR(净+毛)/MDD/Calmar/换手/成本
- **口径**：周期/成本模型(两套)/基准/资金规模/年化算法/层
- **可信度**：DSR(N_eff)/MCS集合/PBO/walk-forward OOS/forward衰减/train-valid r/N记账
- **证伪判定**：verdict(死了/未死)+evidence列表

**证伪门槛**（程序性，DSR已按N_eff校正）：
| 规则 | pass(未死) | fail(死了) |
|---|---|---|
| F1 DSR | ≥0.95（SR显著非运气） | <0.95（可能运气） |
| F2 MCS | 策略在无法区分集合内 | 被排除 |
| F3 forward衰减 | ≤0.50 | >0.50 |
- 判定逻辑：任一 fail=死了；全 pass=未死_待forward积累（证伪主义：未死≠好，只=没被证伪）

**修正计划错误**：计划写"DSR<0.95=未死"是**笔误**（逻辑反了）。DSR高=SR显著=没死。正确：DSR≥0.95=未死。schema 用正确逻辑。

### A4 daily_pick 生产层改造（commit c533237）

**决策点**：原计划跳过待老板定。老板8/12定方向"改推候选报告"。

**问题**：daily_pick_v5.py 每天14:45推Top5选股=价值性输出，与新定位（程序性裁判不推荐）冲突。

**改造**（`daily_pick_v5.py`）：
- 不推选股（不调rank_and_pick，选股逻辑保留在strategy_factory）
- 读 `compare_pool_result.json`（A1净口径）+ `rq_review_daily_pick_eqcomposite_top5.json`（A2真实口径）
- 按 `four_piece_schema` 证伪判定（F1 DSR + F2 MCS + F3 forward衰减）
- 飞书推送候选证伪状态报告

**产出**：13候选证伪判定，10死了/3未死。daily_pick死了（DSR0.775+被MCS排除+真实SR-0.441亏损）。3未死（phase2_ic/funnel_top5_eq_long/funnel_top5_tsmom_long，但n_eff=1.94同源，未死≠可实盘）。

**systemd 未改**：daily-pick.service 指向 `run_daily_v4.py`（v4旧版推Top5），改systemd需老板确认。本脚本手动/cron触发。老板决定：timer保持v4，daily_pick_v5.py改造保留作个股推送模板。

### B1 策略评估管道 SOP 文档（commit 6675509）

**产出**：`docs/策略评估管道SOP.md`（仿 `docs/筛选流程SOP.md` 结构）
- 模块链：funnel → collect_* → compare_pool(成本) → RQAlpha终审 → 验证 → 证伪判定 → 报告
- 每模块：输入JSON/输出JSON/口径假设/完整性要求/脚本入口
- 判定阈值表（DSR/MC/forward衰减/PBO/成本）
- 口径流转图（config沿管道显式传递）
- 完整性要求6条（candidates保持毛收益/毛净双口径/两套成本模型/DSR按N_eff/证伪程序性/8/8结论按真实口径重判）

### C1 编排器（commit 69d47ed）

**产出**：
- `branches/strategy_factory/orchestrator.py`：按依赖顺序串模块，口径config沿管道流转。支持 `--list/--stage/--from/--to`。编排器只调度不含业务逻辑，模块失败不静默。
- `branches/strategy_factory/pipeline_config.json`：口径 source of truth（改口径改这里）。含 period/freq/train_end/cost_model两套/falsification_thresholds。

### C2 报告生成器（commit c4ceed5）

**产出**：`branches/compare/report_generator.py`（整合 DSF report_compare_pool + report_daily_pick）
- 去硬编码：数字从 compare_pool_result.json 读（含毛/净双口径）
- 净口径：主指标用净收益（A1），毛收益对照（DSF 8/8版是毛收益虚高）
- 自动证伪判定：按 A3 four_piece_schema 门槛算 verdict（非写死"死了"）
- 统一：一脚本对全池
- 输出：`reports/v5_four_piece_report.html`（净值/毛净SR对照/DSR/alpha-beta/汇总表+证伪判定）

---

## 五、数据修复插曲（8/6,8/7 15min重采）

### 发现问题
老板反映笔记本开关不定，查最近15天数据：
- `daily_kline`（tdx_stock_data.db）：✅ 正常，最新8/12，每天5095-5199股票
- `kline_15m`（stock_data.db）：⚠️ 8/6,8/7损坏
  - 8/6：~31%股票缺失（3563/5203）+ 异常时段 04:15,16:00 + 13:00缺失
  - 8/7：下午盘14:00-15:00缺失 + 异常时段 20:15

### 采集机制调研
- `m15_snapshot.py`：数据源新浪批量API + akshare `stock_zh_a_minute`
- `m15-snapshot.timer`：9:45-14:45每15min触发 `run_snapshot()`（实时快照）
- `m15-finalize.timer`：16:00触发 `finalize_today()`（akshare补全当日）

### 口径问题（老板提醒）
**原始 kline_15m 是混合口径**：
- 9:45-14:45 = **累计口径**（snapshot缺陷）：open=当日开盘(固定)、high=当日最高(固定)、low=累计最低(递减)、close=当前价、volume=累计成交量(递增)
- 15:00 = **真15min bar**（finalize补的）

**股票数**：stock_info status='1' 现在5530（含新股），原始8/11是5203。

### 重采脚本 `m15_refetch.py`
老板定方案：股票数对齐8/11基准5203 + 还原累计口径。
- `get_baseline_codes('2026-08-11')`：从基准日kline_15m取股票列表（5203）
- `pull_and_write_cumulative`：akshare真bar → 还原累计口径（9:45-14:45累计OHLCV，15:00真bar）
- 验证：sh.600000 8/11还原 vs 原始，open/high/low/close/volume基本一致（数据源轻微差异，口径一致）

### 重采执行
8/6,8/7 重采（基准5203 + 累计口径），DELETE损坏+akshare重拉。执行中（详见使用手册维护章）。

---

## 六、最终结论

### v5 收尾完成
- 计划7步全部 commit（A1/A2/A3/A4/B1/C1/C2）
- 验证总标准达成：成本口径SR重算✅、四件套schema能产✅、SOP+编排器一键跑✅、8/8结论按真实口径重判✅

### 核心结论
1. **daily_pick 证伪死了**：A1净SR0.244 + A2真实口径SR-0.441亏损 + DSR0.775<0.95 + 被MCS排除。六条证据汇聚。
2. **候选供给是瓶颈**：n_eff=1.94（8/12实测），13候选同源（量价因子衍生），池内"择优"无统计意义，只能淘汰。
3. **v5 定位成立**：程序性裁判系统（证伪主义）--能淘汰，不能选优。根因是候选同质。

### 未做项
- daily_pick RQAlpha归因拆解（费用/涨跌停/停牌分项，需跑nolimit版）：DSF tsmom_ls归因(费用2.41+涨跌停1.72+停牌5.03pp)可作量级参考，补的边际价值低
- v6候选供给（范围外）：策略生成器（翻译器）是具体路径，见 `docs/v5策略生成器方向调研-cc.md`

---

## 七、git commit 索引（8/12 收尾）

| commit | 步 | 说明 |
|---|---|---|
| b866ef0 | 计划 | 收尾实施计划 + 整合DSF调研依据文档 |
| 85f88a2 | A1 | 接成本层进主管道(净收益口径) |
| 5d4ffd4 | A3 | 四件套 schema 正式化 + 证伪门槛 |
| 6675509 | B1 | 策略评估管道 SOP 文档 |
| 69d47ed | C1 | 编排器 + 口径config |
| c4ceed5 | C2 | 四件套报告生成器(整合DSF report) |
| 5886708 | A2 | RQAlpha纳入第二引擎(双层管道泛化+daily_pick终审) |
| 7d46505 | A2补充 | backtest重跑result + DSF report归档 |
| c533237 | A4 | daily_pick生产层改造(推Top5→推候选证伪报告) |

---

## 八、接手要点

1. **定位**：v5=程序性裁判系统+四件套，证伪主义不推荐。不是选股系统。
2. **口径**：candidates_returns.json 保持毛收益（source of truth），成本在 compare_pool 统一出口扣。毛/净双口径显式列。两套成本模型（candidates固定 vs RQAlpha真实）。
3. **n_eff=1.94**：13候选同源，池内择优无意义，MCS只能淘汰。
4. **daily_pick 已证伪**：真实口径SR-0.441亏损。timer仍推v4 Top5（老板定保持），daily_pick_v5.py改造版未接timer。
5. **kline_15m 口径**：9:45-14:45累计口径(snapshot缺陷)+15:00真bar。重采用m15_refetch.py(累计口径还原+基准5203)。
6. **下一步**：v6策略生成器（翻译器）补候选供给缺口，见 `docs/v5策略生成器方向调研-cc.md`。
7. **规则**：严谨准则（事实断言先调研/结论带依据链/不客套）+ 严厉老师模式（纠错优先）全局生效，见 `~/.claude/CLAUDE.md`。

## 关联
`v5系统定位.md`（定位/四件套）· `v5系统使用手册-cc.md`（怎么用）· `策略评估管道SOP.md`（B1）· `v5引擎对跑验证-cc.md`（DSF成交现实）· `v5策略生成器方向调研-cc.md`（v6方向）· memory `session-state-2026-08-12`
