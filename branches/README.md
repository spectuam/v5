# branches/ 支路总览（2026-08-13 整理）

> **本目录是 v5 管道主体，任何文件不要移动**：36 个脚本硬编码 `/home/soso/v5` 或相对 `branches/` 路径，移动必断管道。
> 管道数据流：`strategy_factory`（作者域）→ `compare`（评估域）→ `daily_pick_v5.py`（推送，根目录）。

| 支路 | 状态 | 职责 |
|---|---|---|
| `strategy_factory/` | ✅ 活跃 | 作者域：策略生成/回测/orchestrator 编排/pipeline_config/walkforward/forward_tracker |
| `compare/` | ✅ 活跃 | 评估域：五路漏斗/候选执行/成本复核(compare_pool)/RQAlpha 终审/报告生成 |
| `cost_layer/` | ✅ 活跃 | 成本模型（compare_pool 的依赖，被 sys.path 插入） |
| `factor_momentum/` | ✅ 活跃 | 因子动量复现 TSMOM（对应 docs/因子动量方向复盘与复现计划.md） |
| `factor_persistence/` | ✅ 活跃 | 因子持续性验证 |
| `baseline_v0/` | 📦 存档 | 8/12 基线存档（锚定 commit 8662901，12→10 边界噪声修正） |
| `state_switch/` | ⚠️ 废弃 | HMM 状态切换（8/8 定论：实盘不可达），见 `.deprecated` |

## 验证清单（改动后跑，确认管道通）

```bash
cd /home/soso/v5
PYTHONPATH=/home/soso .venv/bin/python3 branches/compare/compare_pool.py        # 成本复核
.venv/bin/python3 branches/compare/report_generator.py                          # 报告生成
.venv/bin/python3 branches/strategy_factory/orchestrator.py --list              # 编排器
# daily_pick_v5.py 无 dry-run 参数，验证时只查依赖文件存在，不执行（会真推飞书）
```

## 已知坑

- 脚本 import 依赖 `PYTHONPATH=/home/soso`（ading 模块）
- `strategy_factory/strategy_factory.py` 还引用 `/home/soso/trading-strategy`（v4 老 repo，历史遗留）
- 管道产物（json/html）被 git 追踪，跑验证清单会弄脏 working tree，验证后 `git checkout --` 还原
- `tsmom_ls_K12_holdings.json` 50MB（已 push，未超 GitHub 硬限）
