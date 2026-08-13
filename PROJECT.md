# v5 项目入口

> 新 agent / 新会话接手先读本页（一页导航，2026-08-13 架构整理后更新）。
> 一句话定位：**v5 = 程序性裁判系统（相对择优器）**，把"人肉挑策略"变成可复现的证伪管道。产出是候选证伪报告，不是荐股。

## 目录图

```
v5/
├── PROJECT.md                 ← 本页（入口导航）
├── FILE_STRUCTURE.md          ← 完整索引（timer 实况/数据/坑）
├── CLAUDE.md                  ← 项目准则 + 内存红线
│
├── daily_pick_v5.py           ← 生产脚本（手动推飞书候选报告，被 strategy_factory import）
├── daily_report_v5.py         ← 15:15 数据状态报告
├── sina_daily_sync.py         ← Sina 日更同步（数据层源头）
├── build_ic_daily.py          ← IC 日报构建
├── _archived/                 ← 7/15-7/20 探索脚本+杂物归档（README 索引在里）
│
├── docs/                      ← 活跃文档 9 个（见下）+ _archive/ 五阶段演进史
├── branches/                  ← 管道主体（7 支路，README 标注状态，勿移动内部文件）
│   ├── strategy_factory/  compare/  cost_layer/   ← ✅ 作者域+评估域+成本
│   ├── factor_momentum/  factor_persistence/      ← ✅ 因子动量复现+持续性
│   ├── baseline_v0/                               ← 📦 8/12 基线存档
│   └── state_switch/                              ← ⚠️ 废弃（HMM 实盘不可达）
│
├── v5_diagnosis/  new_direction/  margin_factor/  ← 三次早期验证（已完成，原位保留）
└── mlruns/                    ← MLflow 记录（gitignore 了，Qlib 线内存够后续用）
```

## 活跃文档（docs/ 顶层 9 个）

| 文档 | 用途 |
|---|---|
| `v5系统定位.md` | 定位核心：程序性裁判系统 + 四件套（证伪主义，不推荐） |
| `v5系统使用手册-cc.md` | 最全手册：架构+数据层+管道7模块+配置+10条坑 |
| `v5收尾实施记录-cc.md` | 8/12 收尾怎么来的 + 最终状态 + commit 索引 |
| `v5收尾实施计划.md` | 收尾蓝图（内容→SOP→管道） |
| `策略评估管道SOP.md` | 管道契约：IO/阈值（B1） |
| `筛选流程SOP.md` | 因子筛选 SOP（7/28 冻结） |
| `v5引擎对跑验证-cc.md` | RQAlpha 对跑：自写回测高估 14pp 归因（8/11） |
| `v5策略生成器方向调研-cc.md` | v6 方向调研：双向翻译器（8/12） |
| `因子动量方向复盘与复现计划.md` | **进行中**：回文献复现 TSMOM（对应 branches/factor_momentum） |

过程文档在 `docs/_archive/{01初始|02分支|03_fable5|04重新整理|05收尾}/`，总览见 `docs/_archive/README.md`。

## 管道数据流（串联主线）

```
采集(sina_daily_sync → ~/ading/db/tdx_stock_data.db)
  ↓
因子(factor_decay_utils + ~/ading/cache/t3a_factors/*.pkl)
  ↓
候选执行(strategy_factory: funnel→collect→compare_pool→export_holdings)
  ↓
RQAlpha 终审(compare/: rq_executor→rq_review，真实撮合)
  ↓
报告(compare/report_generator → reports/v5_four_piece_report.html)
  ↓
推送(daily_pick_v5.py 手动 → 飞书候选证伪报告)
```

一键编排：`orchestrator.py --from compare_pool --to rq_review`（CLI 参数已核实存在）。

## 跑脚本须知

- Python：`~/v5/.venv/bin/python3`；ading 模块脚本加 `PYTHONPATH=/home/soso`
- DB：`~/ading/db/tdx_stock_data.db`（daily_kline date 格式 `'YYYY-MM-DD 00:00:00'`，查等号用 LIKE）
- 内存红线：WSL2 7GB（全局 systemd 杀就位）

## 坑提醒（动手前必读）

1. **v5 无任何生产 timer**——systemd 19 个 service 全指向 `/home/soso/trading-strategy/`（v4）和 `~/ading/infra/`。v5 内文件移动不碰生产。
2. **daily_pick_v5.py 会真推飞书**，无 dry-run 参数——验证时只查依赖，不执行。
3. **branches 内文件不要移动**：36 个脚本硬编码路径，移动必断管道。验证清单见 `branches/README.md`。
4. 管道产物（json/html）被 git 追踪，跑验证后 `git checkout --` 还原。
5. 归档语义：`_archived/` = 死代码，`docs/_archive/` = 演进史。取回 = git mv 回原位 + 更新 README。
