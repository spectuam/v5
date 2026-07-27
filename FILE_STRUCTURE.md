# v5 项目文件结构说明

> 给 agent/操作者：v5 项目文件结构、脚本分类、timer 对应、数据位置
> 更新：2026-07-22（加入 docs/、_archived/、branches/、PROJECT.md）

## 快速入口

- **PROJECT.md**：300 字项目概况，新 agent 先读这个
- **本文件**：完整索引

## 目录结构

```
/home/soso/v5/
├── PROJECT.md                   ← 入口文档（新 agent 先读）
├── FILE_STRUCTURE.md            ← 本文件
├── .venv/                       # Python 3.12.3 虚拟环境
│
├── *.py                         ← 生产 timer 脚本 + 公共模块（不动）
│   daily_pick_v5.py, build_ic_daily.py, sina_daily_sync.py,
│   daily_report_v5.py, tdx_vipdoc_sync.py,
│   line_bcd_backtest.py, factor_decay_utils.py, ...
│
├── docs/                        ← 已完成验证的文档（归档）
│   ├── glm0720.md               v5 诊断全记录
│   ├── new_direction_执行.md    翻倍股/动量全记录
│   ├── margin_factor_需求.md    融资融券需求
│   ├── margin_factor_执行.md    融资融券执行记录
│   └── 数据源梳理.md            两个 db + 脚本映射
│
├── _archived/                   ← 废弃脚本
│   └── backtest_validation.py
│
├── v5_diagnosis/                ← 验证 1：因子诊断（glm0720）
├── new_direction/               ← 验证 2：翻倍股/动量
├── margin_factor/               ← 验证 3：融资融券
│
└── branches/                    ← 新验证支路（当前活跃）
    └── state_switch/            ← 分状态策略切换（进行中）
        ├── state_switch_需求.md
        └── state_switch_执行.md  （GLM 跑完写这里）
```

## 数据

- **主数据库**：`~/ading/db/tdx_stock_data.db`（全历史后复权）
- daily_kline.date 格式：`'YYYY-MM-DD 00:00:00'`，查等号用 LIKE

## timer 对应（不受结构变动影响）

| timer | 脚本 | 时间 |
|-------|------|------|
| daily-pick-v5 | /home/soso/v5/daily_pick_v5.py | 14:50 |
| sina-daily-sync | /home/soso/v5/sina_daily_sync.py | 15:05 |
| build-ic-daily | /home/soso/v5/build_ic_daily.py | 15:10 |
| daily-report-v5 | /home/soso/v5/daily_report_v5.py | 15:15 |
| m15-finalize | /home/soso/trading-strategy/m15_snapshot.py | 16:00 |

## 三次验证结论

- v5 诊断：OHLCV 经典因子，分位 0.51
- 翻倍股/动量：AUC 0.82，回测 2.5 年 0.40
- 融资融券：IC -9.4%，回测 0.51-0.53
- **最后建议**：OHLCV + 两融都达不到 0.70，需换数据源或换方法论

## 跑脚本注意

- Python：`~/v5/.venv/bin/python3`
- 子目录脚本需 `cd` 到对应目录
- 内存红线：7GB
