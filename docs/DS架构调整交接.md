# DS 架构调整交接清单（2026-08-12）

> 日期：2026-08-12 · 整理：cc（GLM 窗口）
> 性质：v5 架构理顺交接给 DS 执行。cc 月限额将到 + 状态不稳定，架构调整交 DS 做。
> 原则：**串联 > 零散**。v5 价值在管道串联（数据->因子->候选->成本->RQAlpha->报告->证伪），调整后必须能一键跑通。别为整洁切断管道。
> 关联：`v5系统使用手册-cc.md`（最全手册）· `v5收尾实施记录-cc.md`（怎么来的）· `v5系统定位.md`（定位）

---

## 一、先建立认知（别盲动）

DS 必须先读这三份，建立全局观再动任何文件：

1. **`docs/v5系统使用手册-cc.md`**：架构+数据层+管道7模块+配置+维护+10条坑，最全
2. **`docs/v5收尾实施记录-cc.md`**：8/12 收尾怎么来的 + 最终状态 + commit 索引
3. **`docs/v5系统定位.md`**：定位=程序性裁判系统+四件套（证伪主义，不推荐）

再读：`docs/策略评估管道SOP.md`（管道契约/IO/阈值）· `docs/v5收尾实施计划.md`（蓝图）

---

## 二、管道数据流（串联主线，移动文件前先定位它在哪一环）

```
采集(m15_snapshot/sina_daily_sync -> kline_15m/daily_kline)
  ↓
因子(factor_decay_utils + ~/ading/cache/t3a_factors/*.pkl)
  ↓
候选执行(collect_candidates/heterogeneous/market_benchmark/lowvol_weekly/strategy_factory --backtest
        -> candidates_returns.json [毛收益 source of truth])
  ↓
成本复核(compare_pool.py + cost_utils -> compare_pool_result.json [净口径+毛对照])
  ↓
RQAlpha终审(export_holdings -> run_rq/rq_executor -> rq_terminal_review -> rq_review_*.json [真实撮合])
  ↓
报告(report_generator -> reports/v5_four_piece_report.html)
  ↓
生产推送(daily_pick_v5 读 compare_pool_result+rq_review -> 飞书候选证伪报告)

配置：strategy_config.json(作者域) + pipeline_config.json(评估域)
```

**移动任何文件前，先确认：它在管道哪一环？被谁读？被谁写？引用谁？被谁引用？** 用 `grep -r 文件名` 排查依赖。

---

## 三、文件生态现状（四类）

### 3.1 md 文档（32个，docs/）
**活跃8个（留顶层，调整后仍用）**：
- `v5系统定位.md`（定位核心）
- `v5系统使用手册-cc.md`（怎么用）
- `v5收尾实施记录-cc.md`（怎么来的）
- `v5收尾实施计划.md`（蓝图）
- `策略评估管道SOP.md`（管道契约，B1）
- `筛选流程SOP.md`（因子筛选SOP，7/28冻结）
- `v5策略生成器方向调研-cc.md`（v6方向，8/12）
- `v5引擎对跑验证-cc.md`（RQAlpha对跑/成交现实/14pp，8/11）

**过程24个（归档，按阶段分）**：
- 架构方案3份：`v5架构方案-cc.md`/`v5架构方案-ds.md`/`v5架构方案-合并版.md`（8/7，已被"系统定位"取代但保留历史）
- fable5系列：`fable5回复综合讨论.md`/`fable5回复2-逐句分析.md`（7/23-28）
- 方向讨论：`DS回复-方向对齐.md`/`化学反应方向审查.md`/`v5工程执行复盘建议.md`+`回复.md`/`v5工程执行日志.md`（7/28-29）
- 阶段调研：`v5阶段2-3实现与HMM调研-cc.md`（8/8）
- 会话交接：`v5-dsf会话交接-0809-0812.md`
- 系统认知：`v5系统认知-老板.md`（8/7）
- 方法论：`GK_方法论逐句分析.md`/`EL_方法论逐句分析.md`/`因子动量方向复盘与复现计划.md`（7/29-31）
- 其他：`三层尺子表.md`/`数据源梳理.md`/`state_switch_需求.md`/`margin_factor_需求.md`+`执行.md`/`new_direction_执行.md`/`glm0720.md`（7/22-28）

### 3.2 脚本
**根目录30+散py（按功能归类）**：
- 生产/日常：`daily_pick_v5.py`（A4改造版推候选报告）/`daily_report_v5.py`（15:15数据状态）/`sina_daily_sync.py`（Sina日更）
- 数据构建：`build_qlib_binary.py`/`build_qlib_data.py`/`hdf5_to_sqlite.py`/`tdx_vipdoc_sync.py`
- 因子：`factor_decay_scan.py`/`factor_decay_utils.py`/`build_ic_daily.py`
- 管道/探索：`full_pipeline.py`/`exhaustive_search.py`/`multi_horizon_test.py`/`run_phase_bc.py`/`sharp_vs_persistent.py`/`group_scan.py`
- Qlib ML：`line_bcd_backtest.py`/`line_e_qlib_ml.py`/`line_f_synthesis.py`/`test_qlib_*.py`/`train_lightgbm.py`
- 工具/测试：`verify_hdf5.py`/`v42_vs_v5.py`/`test_weight_schemes*.py`

**branches/ 7个分支（收尾后活跃状态）**：
- `strategy_factory/`（作者域：策略生成/回测/orchestrator/pipeline_config/four_piece_schema/walkforward/forward_tracker）✅活跃
- `compare/`（评估域：funnel/collect_*/compare_pool/export_holdings/rq_executor/run_rq/rq_terminal_review/report_generator + DSF原版rq_*.py）✅活跃
- `cost_layer/`（成本：cost_utils）✅活跃
- `factor_momentum/`（因子动量：factor_returns_*/tsmom/diagnose）✅活跃
- `factor_persistence/`（因子持续性）✅活跃
- `baseline_v0/`（基线存档）✅存档
- `state_switch/`（HMM状态切换）⚠废弃（8/8定论HMM实盘不可达）

### 3.3 数据文件
- **两DB**：`~/ading/db/tdx_stock_data.db`（daily_kline/stock_info/adjustment_factor等，code格式 sh600000）/`~/ading/db/stock_data.db`（kline_15m，code格式 sh.600000）
- **JSON管道产物**（branches/compare/）：candidates_returns.json/compare_pool_result.json/funnel_result.json/factor_returns_*.json/tsmom_ls_K12_holdings.json(50MB!)/daily_pick_holdings.json/rq_review_*.json
- **结果JSON**（branches/strategy_factory/）：walkforward_result.json/forward_track_result.json/param_scan_result.json
- **因子缓存**：`~/ading/cache/t3a_factors/*.pkl`（不在v5 repo）
- **文献pdf**：`docs/EL_Ehsani_Linnainmaa_Factor_Momentum_NBER_w25551.pdf`

### 3.4 结果文件
- **pkl**：`branches/compare/rq_*.pkl`（RQAlpha结果，已.gitignore排除）
- **report HTML**：`branches/compare/reports/*.html`

---

## 四、阶段时序（归档按此分目录）

| 阶段 | 时间 | 内容 | 归档目录 |
|---|---|---|---|
| 01_初始搭建 | 7/22前 | 数据层/因子/Qlib探索 | _archive/01_初始/ |
| 02_分支探索 | 7/22-7/28 | margin/state_switch/new_direction/三层尺子 | _archive/02_分支探索/ |
| 03_fable5回复 | 7/23-7/30 | 逐句分析/方向复盘/GK-EL方法论 | _archive/03_fable5/ |
| 04_重新整理 | 7/29-8/8 | 方向对齐/化学反应/工程复盘/系统认知/架构方案cc-ds-合并/定位/引擎对跑 | _archive/04_重新整理/ |
| 05_收尾 | 8/12 | 实施计划/A1-C2/实施记录/使用手册/策略生成器调研 | _archive/05_收尾/（或留顶层，因最新） |

---

## 五、调整建议（分层+入口+边移边验）

1. **docs分层**：活跃8个留 docs/ 顶层；过程24个归 `docs/_archive/{阶段}/`（按上表5子目录），保留项目演进史
2. **根py归类**：`bin/`（生产：daily_pick/daily_report/sina_sync）`data_build/`（数据：build_qlib*/hdf5/tdx_sync）`explore/`（探索：line_*/test_*/scan）`_archived/`（废弃）。**先 grep import 依赖再移**
3. **branches**：state_switch 标注废弃（README 或 .deprecated 标记）；其余活跃保留
4. **数据/结果**：管道JSON产物可移 `results/`（或留 compare/ 原位，因脚本硬编码路径）；`tsmom_ls_K12_holdings.json` 50MB 超 GitHub 推荐考虑 git-lfs 或移出 repo
5. **PROJECT.md 入口**：改造成导航（活跃文档索引+管道数据流图+分支说明+快速上手+坑提醒），接手者一眼看懂
6. **每移一类立即验证**：跑 `python3 branches/compare/compare_pool.py` + `python3 branches/compare/report_generator.py` + `python3 branches/strategy_factory/orchestrator.py --list`，确认管道不破再继续下一类，分阶段 commit

---

## 六、风险（DS 必查，先排查再动）

1. **import 路径**：脚本用 `sys.path.insert(0, '/home/soso/trading-strategy')`/`from ading.config.paths import DB`/`from factor_zoo_adapter import compute_alpha`/`from feishu import send_text`。移动脚本要改 path。**移动前 `grep -r "from ading\|sys.path.insert\|from factor_zoo\|from feishu" <目标文件>` 排查**
2. **docs 互链**：文档间 `关联：xxx.md`/`见 docs/xxx.md` 引用，移动后改路径
3. **systemd 别动**：`daily-pick.service` 指向 `/home/soso/trading-strategy/run_daily_v4.py`（v4，非v5）。改 systemd 需老板确认。timer 配置在 `~/ading/infra/systemd/`
4. **硬编码绝对路径**（`~/ading/db/...`/`~/ading/cache/...`）不受文件移动影响；**相对路径**（`branches/compare/...`）受影响，移动脚本/数据要改
5. **大文件**：`tsmom_ls_K12_holdings.json` 50.31MB（已push，GitHub warning，未超100MB硬限）
6. **pkl 已 .gitignore**：`*.pkl` 排除，移动pkl不影响 repo（但脚本读pkl路径要注意）
7. **PYTHONPATH**：ading 模块脚本需 `PYTHONPATH=/home/soso`，移动后仍需

---

## 七、验证清单（每阶段commit后跑，确认管道通）

```bash
cd /home/soso/v5

# 1. 成本复核（秒级，读 candidates_returns）
PYTHONPATH=/home/soso .venv/bin/python3 branches/compare/compare_pool.py

# 2. 报告生成（读 compare_pool_result）
.venv/bin/python3 branches/compare/report_generator.py

# 3. 编排器（看管道阶段）
.venv/bin/python3 branches/strategy_factory/orchestrator.py --list

# 4. daily_pick 推送（读 compare_pool_result + rq_review）
.venv/bin/python3 daily_pick_v5.py
```
任一失败 = 移动了被依赖的文件，回查。

---

## 八、核心原则再强调

- **串联 > 零散**：调整后必须能一键跑通 `orchestrator.py --from compare_pool --to rq_review`。别为整洁切断管道。
- **边移边验**：别一次性大移。每移一类，跑验证清单，commit，再下一类。
- **时序保留**：归档按阶段分目录，保留 v5 从初始到收尾的演进史（这是项目资产，不是垃圾）。
- **不确定的不动**：拿不准依赖的文件，先 grep 排查或问，别盲移。
- **systemd / DB / 大文件**：三类高风险，动前必问老板。

## 九、执行层补充（DSF 窗口 8/13 审阅追加——动手前必读）

> 上面 §一~§八 是方案层。本节补执行层：DS Pro 动手时会踩、GLM 方案未覆盖的细节。

**9.1 第一动作：建基线（动任何文件前）**
1. `git status` 清点 untracked（DSF 产出是否全 commit 过需现场核对——8/13 记忆"DSF产出untracked"、补遗 f5cf03f 可能未盖全）
2. 跑一遍 §七 验证清单，确认**整理前管道就是通的**——否则整理中坏了不知道是不是自己搞的

**9.2 用 `git mv` 移动**
大量移动文件，用 `mv` 会让 git 记成 delete+add，**演进史全丢**（归档的意义就是保留历史）。

**9.3 验证清单两个坑**
- §七 第 4 条 `daily_pick_v5.py` **会真推飞书**——验证时用 dry-run 模式，或只验证其依赖文件存在，别真推送
- §八 "一键跑通 `orchestrator.py --from compare_pool --to rq_review`"——CLI 参数**先验证存在**再写进文档/交付物
- 验证清单缺 `forward_tracker` / `walkforward`（也是管道环节，补上）

**9.4 push 环节（8/12 已踩过的坑）**
整理完必然 push——8/12 push 失败（GitHub 认证超时，origin 落后 15+ commit）。**开工前先解决认证/代理**（surflare 状态、gh 认证），否则整理完卡在 push。

**9.5 归档的语义：不是搬家是建索引**
每个归档目录配 README（一句话：这是什么/为什么归档/活跃替代在哪）——否则"保留演进史"变"死文件堆"。

**9.6 一个决策点先问老板**
`v5系统认知-老板.md` 在归档清单（04 阶段）——但老板 8/8 说过**要续写它**（可能回到起点讨论）。归档前先问老板。

**9.7 仓库健康（决策归老板）**
`mlruns/`（MLflow 实验记录，可能很大）是否被 git 追踪？50MB holdings + repo 总大小——DS Pro 汇报仓库健康数据，大文件处理（gitignore/git-lfs/移出 repo）由老板定。

**9.8 老板自己的未 commit**
`CLAUDE.md` + `因子动量方向复盘与复现计划.md`（老板改的）——动手前先处理（commit 或明确先放着）。

**9.9 交付物定义（"理顺"的验收标准）**
完成时交付三样：① PROJECT.md 更新成一页导航（目录图）② §七 验证清单全部通过 ③ commit 历史清晰（git log 能看出"整理"过程）。无交付物定义，"理顺"就没有完成标准。

**9.10 认知补一份**
§一 三份必读外加读 `v5-dsf会话交接-0809-0812.md`（管道/对跑/RQAlpha 来历，DSF 侧细节）。

---

## 十、给 DS Pro 的开场交代（GLM 文档外交接时直接转发）

> 以下是新 session 开场给 DS Pro 的口头交代，覆盖"文档没写但必须知道"的部分。

```
DS，v5 架构理顺工作交给你。先读 docs/DS架构调整交接.md（方案层）+ 本段（执行层）。

【开工前】
1. 先跑 git status 清点未提交文件，跑一遍交接文档 §七 验证清单，确认整理前管道是通的（基线）。
2. push 认证问题先解决（8/12 失败过：GitHub 认证超时，origin 落后 15+ commit）。surflare 状态、gh 认证确认好。
3. 老板有两处未 commit 的改动（CLAUDE.md、因子动量复盘文档），先问老板怎么处理。

【执行中】
4. 所有移动用 git mv（保留演进史，归档的意义就在这）。
5. 边移边验，每移一类跑验证清单 commit。验证时 daily_pick_v5.py 用 dry-run（它会真推飞书）。
6. orchestrator 的 --from/--to 参数先验证存在再依赖它。
7. 归档不是搬家：每个归档目录写 README 索引（是什么/为什么归档/活跃替代在哪）。
8. mlruns/、50MB holdings、repo 总大小——仓库健康数据整理完汇报老板，大文件处理老板定。
9. 老板的 v5系统认知-老板.md 在归档清单里，但老板可能还要续写——先问老板再动。

【交付标准】
10. 完成时交付三样：PROJECT.md 一页导航 + 验证清单全通 + commit 历史清晰。
11. 全程原则：串联 > 零散，别为整洁切断管道。拿不准的不动，先问。
```

## 关联
`v5系统使用手册-cc.md` · `v5收尾实施记录-cc.md` · `v5系统定位.md` · `策略评估管道SOP.md` · `v5策略生成器方向调研-cc.md` · memory `session-state-2026-08-12`
