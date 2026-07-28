# 基线 v0 快照存档

> 跑时：2026-07-28 08:42 起
> 跑者：cc（v5 工程开工第一天）
> 依据：`docs/v5工程执行日志.md` §3
> 用途：后续每步改动（#1-#12）的对比基准。不存档就不知道每步改了什么。

## 元信息

- **git commit hash**：`86629019f4f6f2f1d0e698255091b97429267055`（short `8662901`，docs: §8 cc 审阅段）-- 基线锚点，工程启动点
- **数据截止**：daily_kline 2026-07-27 / factor_ic_daily 2026-07-24
- **Python**：`~/v5/.venv/bin/python3`（3.12.3）
- **DB**：`~/ading/db/tdx_stock_data.db`（daily_kline date 格式 `YYYY-MM-DD 00:00:00`）

## ③ factor_map 现状（回填前基线）

- sqlite `factor_map` 表：**7392 行**
- **42 因子**（4 OHLCV + 38 正交）
- 5 颗粒度：week 5376 / month 1260 / quarter 420 / half 210 / year 126
- month 切片：30（1260/42）
- 与 7/23 执行记录一致，未变

## ① 38 因子 IC + t 值（NW 修复前基线）

两套并存（老板拍板）。

### ①a t1_t2（IC/IR/t，普通 t，不受 #7 NW 修复影响）

- 脚本：`v5_diagnosis/t1_t2_diagnose.py`
- 数据源：`factor_ic_daily`（Spearman rank IC，2006-2026，6 窗口×5horizon）
- 正交池：38 因子，matched **37/38**（alpha_019 在 factor_ic_daily 无数据，skip）
- 近期(P5, 2025-2026)仍显著|t|>2：**36/37**
- 选择期显著但 test 期衰减：**0/37**
- 全段|IR|>0.3：**36/37**
- 近期仍显著因子含：alpha_016, alpha_044, alpha_015, alpha_026, alpha_090, alpha_023/024, gtja191/alpha_016 等（36 个全列见 result）
- **可复现性**：summary 计数与 7/20 备份一致（36/36/36, 0/0）；单因子 t 值微变（factor_ic_daily 7/20 后更新至 7/24，P5 窗口多 4 天 IC 数据所致，预期内）。#7 NW 修复不影响此套（普通 t 非 NW t）。

### ①b factor_pers_B（NW 切片超额 t，#7 NW 修复直接对比对象）

- 脚本：`branches/factor_persistence/factor_pers_B.py`
- 方法：38 因子 Top10 T+20，超额 vs 全市场等权，月切片正超额概率 + Newey-West t
- NW `max_lag`：`min(int(4*(n/100)**(2/9)), n//4)` -- **#7 要改成 `max(自动, 持有期-1)=max(自动,19)`**
- TEST_END 2026-06-30；但 daily_kline 7/23 后补了 3 天 6/30 前数据（n_days 597->600），重跑不完全=7/23
- **结果（重跑 2026-07-28 08:55，exit 0）**：
  - 有苗头(t_abs>2)：**10/38**（7/23 为 12/38；少的 2 个是边界噪声：alpha_026 t=2.057 / alpha_092 t=2.010 跨 2.0 阈值）
  - alpha_016：t_abs=2.34, t_exc=**2.14**, prob=0.53（超额显著，比旧 2.04 更强）
  - alpha_044：t_abs=2.13, t_exc=**2.31**, prob=0.70（超额显著，比旧 2.24 更强）
  - 其他 8 个有苗头：alpha_037/026/025/090/002/015/001/055（t_abs 2.05-2.33，t_exc 不显著）
- **可复现性**：核心结论可复现且更强（alpha_016/044 超额显著）；12->10 是 alpha_026/092 边界噪声；32/38 因子 t_abs 微变（n_days +3）。#7 NW 修复后对比此基线。

## ② lowvol 零成本回测（成本层接入前基线）

- 脚本：`branches/state_switch/eval_lowvol_h20.py`
- 方法：vol_20 最低 Top10 T+20，2024-01~2026-06-30，零成本
- 与 #12 lowvol 扣成本核算对齐（#12 在此基础上加往返 11bp+分层冲击）
- **结果（重跑 2026-07-28 08:55，exit 0）**：
  - 全段：胜率 0.5605 / 盈亏比 1.4118 / 夏普 **2.7102** / 回撤 -13.5053 / 均收 1.31%/T+20 / n=6000
  - 分年：2024 夏普 4.0834（强）/ 2025 夏普 2.6449 / 2026 夏普 **-0.7954**（转负）
- **可复现性**：vs 7/23 备份，格局一致（夏普 2.65→2.71，2024 强 2026 弱），回撤完全一致（-13.5053）。n 5970→6000（daily_kline 7/23 后补 3 天 6/30 前数据所致）。

## 存档文件

| 文件 | 来源 | 状态 |
|------|------|------|
| `t1_t2_diag_result.json` | 重跑 2026-07-28 08:41 | ✅ |
| `factor_pers_B_result.json` + `factor_pers_B_done.json` | 重跑 2026-07-28 08:55 | ✅ |
| `eval_lowvol_h20_result.json` | 重跑 2026-07-28 08:55 | ✅ |
| `raw_0723/` | 7/20-7/23 原始 result 备份（可复现性对比） | ✅ |

## 跑法（可复现）

```bash
# ①a t1_t2（纯SQL，~2s）
cd ~/v5/v5_diagnosis && ~/v5/.venv/bin/python3 t1_t2_diagnose.py

# ①b factor_pers_B（删 done 重跑，~15min）
cd ~/v5/branches/factor_persistence && rm -f factor_pers_B_done.json && ~/v5/.venv/bin/python3 factor_pers_B.py

# ② lowvol_h20（~15min）
cd ~/v5/branches/state_switch && ~/v5/.venv/bin/python3 eval_lowvol_h20.py
```
