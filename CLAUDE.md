# v5 项目 CLAUDE.md

## 内存红线

- WSL2 VM 上限 10GB (`.wslconfig`) + 全局杀 `user.slice MemoryMax=7G, MemoryHigh=6G`
- **禁止一次性囤积大量 DataFrame 或大数组**
- 因子扫描四层防线: IC/IR预筛选 → pickle文件临时存储 → 流式计算不囤矩阵 → user.slice 7G兜底
- 开了 `dangerously-skip-permissions`，cc 必须自己在代码里控制内存，炸了没有兜底

## 环境

- Python: `~/v5/.venv/bin/python3`（venv, Python 3.12.3）
- 因子库: `/home/soso/.local/lib/python3.12/site-packages/src/factors/`
- 数据库: `~/ading/db/stock_data.db` (daily_kline 后复权，610天)
- v4.2 适配层: `/home/soso/trading-strategy/factor_zoo_adapter.py`

## 项目结构

```
~/v5/
├── CLAUDE.md                    ← 本文件
├── .venv/                       ← Python venv
├── factor_decay_scan.py         ← 因子衰减扫描主脚本（周末跑, v4磁盘辅助版）
├── factor_decay_utils.py        ← 工具函数（IC、衰减拟合、随机对照、分类）
├── build_qlib_binary.py         ← daily_kline → Qlib 二进制
├── full_pipeline.py             ← Qlib ML 全流程
├── train_lightgbm.py            ← Qlib LightGBM 训练
├── test_qlib_data.py            ← Qlib 数据接入测试
└── test_qlib_factors.py         ← Qlib 因子+IC 测试
```

## v5 因子衰减扫描 — 实施记录 (2026-07-15)

### 架构（v4 磁盘辅助版）
```
Step 1: daily_kline(610天) → panel (内存~500MB)
Step 2: 456因子计算 → IC_mean(内存) + stacked.pkl(磁盘)
        + IC≥0.02/IR≥0.3预筛选（省内存,同v4.2 factor_cluster）
Step 3: 从pkl读stacked → 流式贪婪正交(corr>0.7踢) → 释放pkl
Step 4: 正交池因子 compute一次 → 衰减T+1/3/5/10/20 + 随机对照 → 释放
Step 5: 分类 + 逐个叠加IC找拐点 → 定N → 输出JSON
```

### 首次运行结果 (2026-07-15)
- 456/456因子通过, IC+IR预筛→48候选, 正交→28入选, N=3
- Top 3: qlib158/vma60, qlib158/qtld30, alpha101/alpha_040
- 23/28个因子为persistent (IC不衰减, 半衰期20天)
- 耗时~10分钟, 内存峰值~500MB

### 踩坑记录
| # | 问题 | 根因 | 修复 |
|:---:|------|------|------|
| 1 | WSL2被Windows杀 | 439个DataFrame积压3GB+内核缓存>10G | 流式处理,不攒DataFrame |
| 2 | 内存颠簸卡死 | factor_stacked 439个Series=1.7GB | 改存磁盘pickle文件 |
| 3 | 正交化太慢(每因子重算compute_alpha) | Step 3逐个CPU重算 | Step 2存文件→Step 3读IO |
| 4 | 正交池候选太少(25个) | LOOKBACK_DAYS=250(只用166天) | 改为9999用全部610天 |
| 5 | 分类全标degraded | 指数衰减模型拟合不了"IC不衰减"的因子 | 加persistent规则: T+20≥T+1×0.9则给20天半衰期 |
| 6 | 面板缺vwap/amount | build_daily_panel未取这些列 | 补上vwap+amount字段 |
| 7 | 忘了IC+IR预筛选 | v4.2 factor_cluster有但v5漏了 | Step 2加IC≥0.02+IR≥0.3门槛 |

### 因子分类规则（已实现）
| 优先级 | 条件 | 分类 | 处理 |
|:---:|------|------|------|
| 1 | IC < 0.02 | eliminated (dead) | 淘汰 |
| 2 | alpha_t < 2.0 | eliminated (noise) | 淘汰 |
| 3 | half_life < 2天 | eliminated (too_short) | 淘汰 |
| 4a | R²<0.3 且 T+20 IC ≥ T+1×0.9 | persistent | 保留, 半衰期=20天 |
| 4b | R²<0.3 但不满足4a | degraded | 降级, 半衰期=3天 |
| 5 | 正常衰减 | short/medium/long | 按半衰期 |

### 下一步（待完成）
1. daily_pick_v5.py — 14:50 Sina实时→后复权EOD→TopN因子→排名→Top5飞书
2. 6:2:2 回测验证 — 训练选因子→验证测WR→测试最终评判(目标:跑赢80%的人)
3. 因子衰减扫描设为systemd timer（每周末自动跑）

## 文档索引
- v5规划: `C:\Users\Administrator\Downloads\cc\2026-07-14-v5-规划.md`
- 分支方案: `~/.claude/plans/snappy-gliding-scone.md`
