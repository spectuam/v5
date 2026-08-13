# 02_分支探索（7/22-7/28）

> 三次方向探索：翻倍股/动量、融资融券、分状态切换。全部收敛 0.50-0.53，未达 0.70 目标。
> 探索代码在根目录 `new_direction/`、`margin_factor/`、`v5_diagnosis/`（原位保留）。

| 文件 | 是什么 | 活跃替代 |
|---|---|---|
| `三层尺子表.md` | 三层尺子评估框架（绝对/相对/稳健） | 框架定论在 `docs/v5系统定位.md` |
| `state_switch_需求.md` | HMM 分状态切换需求 | 8/8 定论 HMM 实盘不可达，支路废弃（branches/state_switch） |
| `margin_factor_需求.md` / `margin_factor_执行.md` | 融资融券方向需求+执行记录 | 结论：IC -9.4%，已证伪 |
| `new_direction_执行.md` | 翻倍股/动量方向执行记录 | 结论：AUC 0.82 但回测 0.40，已证伪 |
