# _archived/ 归档索引（2026-08-13 整理）

> 本目录 = 7/22 架构设计定义的"废弃脚本区"。2026-08-13 把根目录历史探索产物归档至此。
> 归档原则：零引用（grep 核实）+ 无 timer + 已被后续支路取代。**任何文件被证明仍被活跃脚本引用，移回原位。**

## 一批归档（2026-08-13）

### 探索脚本（7/15-7/20，Qlib ML 线 + 因子探索，v5 诊断后废弃）

| 文件 | 是什么 | 为什么归档 | 活跃替代 |
|---|---|---|---|
| `backtest_validation.py` | 最早的回测验证脚本 | 7/22 已归档 | branches/strategy_factory/ |
| `build_qlib_binary.py` / `build_qlib_data.py` | Qlib 数据转换（hdf5→qlib binary） | Qlib 线因内存不足暂停，7GB 红线 | 数据层现用 sina_daily_sync |
| `train_lightgbm.py` / `line_e_qlib_ml.py` | Qlib ML 训练线 | 同上，ML 线暂停 | - |
| `line_bcd_backtest.py` / `line_f_synthesis.py` | 五线架构 BCD/F 线 | 已被 branches 各支路取代 | branches/ |
| `hdf5_to_sqlite.py` / `verify_hdf5.py` | hdf5→sqlite 转换 + 校验 | hdf5 数据源已弃用 | 数据全在 ~/ading/db/tdx_stock_data.db |
| `tdx_vipdoc_sync.py` | TDX 本地数据同步 | 零引用，sina 日更已取代 | sina_daily_sync.py |
| `factor_decay_scan.py` / `factor_decay_utils.py` | 因子衰减扫描 + 工具 | 只被本目录死脚本引用 | branches/factor_persistence/ 等 |
| `exhaustive_search.py` / `multi_horizon_test.py` / `group_scan.py` / `sharp_vs_persistent.py` / `run_phase_bc.py` / `v42_vs_v5.py` | 因子历遍/多周期/分组/持续性探索 | 结论已定论（收敛0.5-0.53） | 结论在 docs/ |
| `full_pipeline.py` | 早期全管道脚本 | 被 branches/strategy_factory/orchestrator.py 取代 | orchestrator.py |
| `test_qlib_data.py` / `test_qlib_factors.py` / `test_weight_schemes.py` / `test_weight_schemes_ic.py` | Qlib 数据/因子/加权测试 | 测试目标已归档 | - |

### 杂物

| 文件 | 是什么 | 为什么归档 |
|---|---|---|
| `三层递进架构方案.md` / `日更方案.md` | 7/20 早期架构/日更设计稿 | 已被 v5 收尾架构取代，设计定论在 docs/ |
| `backtest_output.txt` / `phase_bc_output.txt` | 早期回测运行输出 | 运行产物，结论已记录 |
| `t1_t2_diag_result.json` | T1/T2 诊断结果副本 | 与 v5_diagnosis/ 下同名文件重复，v5_diagnosis 为原始保留 |
| `daily_pick_v5.py.bak` | 8/8 A4 改造前备份 | 改造已定稿，正式版在根目录 |
| `workflow_five_lines.js` | 五线工作流 JS | 零引用，架构已变 |

## 保留在根目录的（生产/活跃）

- `daily_pick_v5.py`（手动推飞书候选报告，被 strategy_factory import）
- `daily_report_v5.py`、`sina_daily_sync.py`、`build_ic_daily.py`
- `CLAUDE.md`、`PROJECT.md`（入口）、`FILE_STRUCTURE.md`（索引）
