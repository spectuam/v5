# v5 项目文件结构说明

> 给 agent/操作者：v5 项目文件结构、脚本分类、timer 实况、数据位置
> 更新：2026-08-13（架构整理后重写；timer 表修正为实况）

## 快速入口

- **PROJECT.md**：一页导航，新 agent 先读这个
- **本文件**：完整索引 + 坑

## 目录结构（2026-08-13 整理后）

```
/home/soso/v5/
├── PROJECT.md                   ← 入口（一页导航）
├── FILE_STRUCTURE.md            ← 本文件
├── CLAUDE.md                    ← 项目准则 + 内存红线
├── .venv/                       # Python 3.12 虚拟环境
│
├── daily_pick_v5.py             ← 生产：手动推飞书候选报告（无 timer）
├── daily_report_v5.py           ← 生产：数据状态报告
├── sina_daily_sync.py           ← 生产：Sina 日更同步
├── build_ic_daily.py            ← 生产：IC 日报构建
│
├── _archived/                   ← 废弃脚本+杂物（README 索引在里）
├── docs/                        ← 活跃文档 9 个 + _archive/ 五阶段演进史
├── branches/                    ← 管道主体 7 支路（README 标注状态）
├── v5_diagnosis/ new_direction/ margin_factor/   ← 三次早期验证（完成，原位保留）
└── mlruns/                      ← MLflow 记录（gitignore，Qlib 续用）
```

## timer 对应（2026-08-13 实测修正）

**v5 没有任何生产 timer。** 之前版本写的"daily-pick-v5 14:50 指向 v5"是错的（当时把计划当实况）。

| timer | 脚本（全在 v4 老 repo） | 时间 |
|-------|------|------|
| daily-pick | /home/soso/trading-strategy/run_daily_v4.py | 14:50 |
| daily-report | /home/soso/trading-strategy/daily_report.py | 15:15 |
| sync-daily | /home/soso/trading-strategy/sync_daily.py | - |
| m15-snapshot / m15-finalize | /home/soso/trading-strategy/m15_snapshot.py | 15:50 / 16:00 |
| simulate-build | /home/soso/trading-strategy/simulate_build.py | - |
| panel-update | /home/soso/trading-strategy/panel_update.py | - |
| dscg | /home/soso/ading/infra/dscg/dscg.js | - |
| openclaw-gateway / ading-backup | ~/ading/infra/ 下 | - |

v5 的 daily_pick_v5.py 是**手动执行**（推飞书候选证伪报告，会真发消息，无 dry-run）。

## 数据

- **主数据库**：`~/ading/db/tdx_stock_data.db`（全历史后复权，code 格式 sh600000）
- **15 分钟线**：`~/ading/db/stock_data.db`（code 格式 sh.600000）
- **因子缓存**：`~/ading/cache/t3a_factors/*.pkl`（不在 v5 repo）
- daily_kline.date 格式：`'YYYY-MM-DD 00:00:00'`，查等号用 LIKE

## 验证清单（改动后跑）

```bash
cd /home/soso/v5
PYTHONPATH=/home/soso .venv/bin/python3 branches/compare/compare_pool.py
.venv/bin/python3 branches/compare/report_generator.py
.venv/bin/python3 branches/strategy_factory/orchestrator.py --list
# daily_pick_v5.py 不执行（真推飞书），只查依赖文件存在
```

跑完 `git checkout -- branches/compare/compare_pool_result.json branches/compare/reports/v5_four_piece_report.html` 还原产物。

## 演进史

- 五轮验证结论收敛 0.50-0.53（免费数据源天花板）→ docs/_archive/01/02
- 相对择优器定位定论 → docs/_archive/03/04
- 8/12 收尾（A1-A4）→ docs/v5收尾实施记录-cc.md + docs/_archive/05
- 因子动量复现 TSMOM 进行中 → docs/因子动量方向复盘与复现计划.md + branches/factor_momentum

## 跑脚本注意

- Python：`~/v5/.venv/bin/python3`；ading 模块脚本需 `PYTHONPATH=/home/soso`
- 内存红线：7GB（WSL2 全局杀就位）
- 子目录脚本需 `cd` 到对应目录（或 sys.path 已处理）
