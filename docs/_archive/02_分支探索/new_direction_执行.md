# new_direction 执行记录（结果驱动模式捕捉）

> 起：2026-07-20 夜 ~ 2026-07-21 凌晨
> 任务书：桌面 new_direction.md
> 约束：仅 OHLCV 日线，目标收益分位 > 0.70（跑赢 80%）

## TL;DR（最终）

- **Triple Barrier 方向**（波动率触上门）：AUC 0.54-0.56，无效，放弃
- **翻倍股方向**（20天涨100%）：AUC 0.82（突破），但回测收益分位 0.55-0.625，没到 0.70
- **纯动量 ≈ 分类器**（0.571 vs 0.586），策略本质=动量
- 调优（horizon/Top/cum 窗口）到顶 0.55-0.625，3 个月测试期波动大
- **结论**：OHLCV 动量策略 0.55-0.625，比 v5(0.51) 好但没到 0.70。测试期太短，要扩展确认

## Phase 1: Triple Barrier 标注

- 脚本 `triple_barrier_label.py`，波动率缩放三元障碍（K=10, scale=1.5, vol 过去20天）
- 1480 万样本，+1 强势 19.7% / 0 平庸 66% / -1 弱势 14.3%

## Phase 2/3a: 量价特征 + 分类器（Triple Barrier 标签）

- `phase2_features.py` / `phase2b_features.py` / `phase3a_classifier.py` / `phase3a_v2.py` / `phase3a_v3.py` / `tb_sweep.py`
- 特征差异显著（t=5-14）但幅度小；AUC 0.54-0.56（接近随机）；调参/加 38 因子+行业无效
- **放弃 Triple Barrier 方向**

## 转折：老板要翻倍股（绝对涨幅 100%）

前 20 日均价 X，后 20 交易日 high>=2X（涨 100%+）。绝对涨幅，非波动率相对。

## 翻倍股系列

### find_doublers（找翻倍股）
- 脚本 `find_doublers.py`，锚定 t 前 20 日均价 X，后 20 日 high>=2X
- **70261 翻倍股**（2000-2026），牛市集中（2015 最多 10396，熊市极少）
- 数据：`doublers` 表

### doubler_features（特征差异）
- 脚本 `doubler_features.py`，翻倍 vs 非翻倍，t 前 20/10/30 量价，t 检验
- **特征差异巨大**（t=8-44，远超 Triple Barrier 5-14）。翻倍股涨前：强动量（cum_ret_30 +42%）+ 上涨天数多（63.6%）+ 振幅大 + 放量 + 量价齐升
- 但 cum_ret_30=42% 说明 t 时已涨（涨中非起点）

### doubler_classifier（分类器）
- 脚本 `doubler_classifier.py`，LightGBM 翻倍 vs 非翻倍，训练<2019 测试>=2019
- **AUC 0.8163**（突破！远超 0.54）。precision@top 0.73。特征：大盘 + 个股动量

### doubler_backtest（回测选股）
- 脚本 `doubler_backtest.py`，测试期 2026-04~07 每天 Top5，T+20 收益+全市场分位
- bug 修复：daily_kline.date 格式 'YYYY-MM-DD 00:00:00'，t20 用 LIKE + date>'当天末' 修复
- **收益分位 0.586**（目标 0.70，差 11 个百分点）。比 v5(0.51) 好但没达标

### doubler_backtest_v2（刚启动过滤）
- 脚本 `doubler_backtest_v2.py`，过滤 cum_ret_30<中位数（刚启动）+ Top5
- **0.475**（比 0.586 反而降！）。说明动量延续（已涨多继续涨），过滤动量=更差。涨中偏差假设错

### 纯动量（doubler_backtest_momentum）
- 脚本 `doubler_backtest_momentum.py`，cum_ret_30 排序 Top5（不用分类器），T+20 分位
- **0.571**（分类器 0.586，差仅 1.5 个百分点）。分类器无额外贡献，策略本质=动量

### momentum sweep1（horizon×Top）
- 脚本 `doubler_momentum_sweep.py`，horizon(5/10/20)×Top(5/10)
- 最优 T+10 Top10=0.625。短 horizon+Top10 好。没到 0.70

### momentum sweep2（cum_ret×horizon×Top）
- 脚本 `doubler_momentum_sweep2.py`，cum_ret(10/20/30)×horizon(3/7/10)×Top(10/20)，18 组
- 最优 cum30_h10_t10=0.553。和 sweep1 的 0.625 不一致（算法/测试期波动）。都不到 0.70

## 扩展测试期 + 分状态分析

### 扩展测试期（doubler_backtest_extended.py）
- 测试期 2024-2026（2.5 年），纯动量 cum30_h10_t10
- **整体 0.4024**（3 个月 0.625 是偶然！比 v5 0.51 还差）
- 分年：2024 0.334（极差）/ 2025 0.443 / 2026 0.458

### 2024 分月分析（analyze_2024.py）
- 2024 全年动量失效（分位 0.26-0.47，没月 >0.5）
- 大盘 2024 震荡/微跌（ret 多接近 0 或负）
- 动量和大盘 ret 不强相关（9 月大盘 +1.17% 但动量 0.343）

### 分市场状态（analyze_by_regime.py）
- 上升 0.403 / 下降 0.388 / 震荡 0.424
- 都 <0.5，**全面失效**（推翻"动量趋势期有效"假设）
- 动量在所有状态失效，不是震荡期失效

## 最终结论

- 翻倍股分类器 AUC 0.82（区分力强），但回测收益分位 0.55-0.625（没到 0.70）
- 纯动量 ≈ 分类器，策略本质=动量（选已涨多）
- 调优到顶 0.55-0.625，没突破 0.70
- 3 个月测试期短，波动大（sweep1 0.625 vs sweep2 0.553），不可靠
- **比 v5(0.51) 好，但没达标**。OHLCV 动量天花板约 0.55-0.625

## 明天接上

下一步选项（老板定）：
1. **扩展测试期**（2024-2026，2年）确认 0.55-0.625 稳定性（3 个月太短）
2. 接受纯动量 0.55-0.625（比 v5 好没达标）
3. 换方向（动量是 OHLCV 天花板，换数据/方法）

环境：~/v5/.venv，~/ading/db/tdx_stock_data.db（daily_kline/triple_barrier_labels/doublers 表），38 因子 pkl 在 ~/ading/cache/t3a_factors/

## 工具流程与脚本位置

脚本位置：`/home/soso/v5/new_direction/`

工具流程：
1. `triple_barrier_label.py`：三元障碍标注（1480 万样本）
2. `phase2_features.py`/`phase2b_features.py`：特征差异（t 检验）
3. `phase3a_classifier.py`/`_v2`/`_v3`：LightGBM 分类器（AUC 0.54-0.56，无效）
4. `tb_sweep.py`：调参（无效）
5. `find_doublers.py`：找翻倍股（70261）
6. `doubler_features.py`：翻倍股特征差异（t=8-44）
7. `doubler_classifier.py`：翻倍股分类器（AUC 0.82）
8. `doubler_backtest.py`/`_v2`/`_momentum`/`_sweep`/`_sweep2`/`_extended`：回测（0.4024-0.625）
9. `analyze_2024.py`/`analyze_by_regime.py`：2024 失效分析（分状态都~0.40）

跑前清单：同 v5。daily_kline.date 格式 'YYYY-MM-DD 00:00:00'（查等号用 LIKE）。

**最后建议**：OHLCV 动量/选股长周期不行（2.5 年 0.40，分状态都~0.40）。要达标得**放开约束换数据**：推荐资金流（龙虎榜/北向/融资，akshare 免费）+ 事件（公告）。基本面季频太慢。

## 产物

- 脚本：find_doublers.py, doubler_features.py, doubler_classifier.py, doubler_backtest.py, doubler_backtest_v2.py, doubler_backtest_momentum.py, doubler_momentum_sweep.py, doubler_momentum_sweep2.py
- 数据：doublers 表（70261 翻倍股）
- 结果：各 _result.json
