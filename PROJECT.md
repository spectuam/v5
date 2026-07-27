# v5 项目入口

> 给 GLM / 新 agent：进入项目先读此文件，无需从头探索。

## 当前状态（2026-07-27 更新）

- **生产 timer 稳定运行**（IC 定时器已修复，7/21 补完）
- **五轮验证完成**：v5诊断 / 翻倍股 / 融资融券 / 分状态 / factor_persistence
- **Fable5 两版回复消化完成**（2026-07-27）：设计依据在 `docs/fable5回复综合讨论.md`（§1-§16）+ `docs/因子动量评价体系-设计v2.md`
- **目标框架重构**：绝对复利+回撤约束（放弃+3%超额、放弃3年周期改季度/半年）；三层尺子+三红线；当前阶段"走通相对值定位"，绝对值校准（NW/成本/FDR）暂缓后修
- **已核实**：38 因子选择无泄漏（data_range=2000-2015）；NW 滞后不足需修（T+20需≥19）；退市股未入库（幸存者偏差）；零成本假设
- **当前任务**：v5 工程执行（2026-07-2x 启动）。§16 执行清单 12 项分四梯队。**接手先读 `docs/v5工程执行日志.md`**

## 目录

```
v5/
├── PROJECT.md / FILE_STRUCTURE.md
├── *.py（生产 timer，不动）
├── v5_diagnosis/ new_direction/ margin_factor/
└── branches/state_switch/ branches/factor_persistence/
```

## 跑脚本须知

- Python: `~/v5/.venv/bin/python3`
- DB: `~/ading/db/tdx_stock_data.db`（date 格式 'YYYY-MM-DD 00:00:00'，查等号用 LIKE）
- 内存: WSL2 7G

## 新验证支路规范

每个支路放 `branches/<名>/`，含需求.md + 执行.md + 脚本 + result。**不往桌面扔文件。**
