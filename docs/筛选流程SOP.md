# 因子筛选流程 SOP（可复用 pipeline）

> 冻结：2026-07-28（阶段 4，全盘重做后）
> 依据：`docs/fable5回复综合讨论.md` §1-§16 + `docs/因子动量评价体系-设计v2.md`
> 用途：新因子引入走此流程，确保完整严谨可复用。每步标注**完整性要求**（不简化点）。
> 性质：冻结后不重新讨论。推翻需显式标注 + 老板确认。

## 流程总览

```
阶段0 底层函数（最先，下游都依赖，改一次定底）
  #7 NW 修复（newey_west_t, max_lag=max(自动,持有期-1)）-- 所有用 NW t 的脚本
  #5 block optimal（block_bootstrap_ci, Politis-Romano optimal）
  ↓
诊断层（#3/#4/#5）-> 决策门 A
  MinTRL -> AR(1)+K扫描 -> 转移矩阵 -> 颗粒度 -> 综合判定
  辅助：#3 Decile 单调性 + #4 多头端 IC（因子用法标注）
  ↓
校准（#7/#8/#9，贯穿）
  NW修复(所有脚本) -> #8 FDR(有效N特征值) -> #9 成本层(分项+平方根冲击)
  ↓
阶段二（#11）-> 决策门 B（仅 A 阳性）
  预登记 -> #11 2.2 选股级回测 -> OOS -> #11 2.4 block bootstrap -> #11 2.5 PBO/DSR(完整CPCV) -> #11 2.6 护栏 -> 综合判定
  ↓
阶段二b 成本复核（#9✅后）
  扣成本重跑 OOS -> 最终判决
```

**关键时序**：阶段 0 底层必须先做对，否则 #4/#5/#11 用旧底层，#7/#5 block 修后又得重算（反复）。后面不污染前面：底层函数改后下游重算（依赖非污染），各脚本独立，`baseline_v0/` 只读。

## 阶段 0 底层函数

### #7 NW 修复
- 脚本：`branches/factor_persistence/factor_pers_B.py` + `factor_persistence.py` 的 `newey_west_t`
- 要求：`max_lag = max(min(int(4*(n/100)**(2/9)), n//4), HORIZON-1)`
- **完整性**：所有用 NW t 的脚本都要修（38 正交 + 4 OHLCV + #4 多头 IC t）

### #5 block optimal
- 脚本：`branches/factor_momentum/diagnose.py` 的 `block_bootstrap_ci`
- 要求：`block = max(1, int(round(2 * n**(1/3))))`（Politis-Romano optimal 经验公式）
- **完整性**：数据驱动 block，不固定

## 诊断层（#3/#4/#5）-> 决策门 A

### #5 诊断层（`diagnose.py`）
- 1.1 MinTRL：训练段 month 切片数，K=12 有效，block=6 有效 block >10
- 1.2 AR(1)：38 因子月度 IC 一阶自相关，两档（AR(1)>0 占比 vs GK 91% + 显著为正）+ K 扫描(1,3,6,12)
- 1.3 转移矩阵：P(TopK->TopK) vs 基准，χ² + block bootstrap CI（optimal block）
- 1.4 颗粒度：week/month/quarter 信噪比（P_TT + CI）
- **决策门 A**：AR(1)>0 接近 91% **或** 转移 P 显著 > 基准 -> 进阶段二；两者阴性 -> 归档

### #3 Decile（`decile.py`）
- 市值加权（`get_weights`：amount 代理前 20 日均，**封装未来流通股本替换**）
- 单调性 t（D1-D10 spread NW t）
- 产出因子用法：d1_best / d1_collapse / d1_d3_flat / d10_best / non_monotone
- **完整性**：市值加权（非等权）+ 单调性 t（非启发式）

### #4 多头端 IC（`long_ic.py`）
- top N 扫描（30/50/100）
- 多头端 IC NW t
- 分类：head_strong / tail_concentrated / weak / long_only_strong
- **完整性**：top N 扫描（非固定 50）+ NW t（非仅 IC 均值）

## 校准（#7/#8/#9）

### #8 FDR（`fdr_correct.py`）
- BH-FDR q=0.10
- 有效 N（特征值校准 `(sum λ)²/sum(λ²)`，跳无 IC 数据因子如 alpha_019）
- **完整性**：N 诚实计数（特征值，非假设独立）

### #9 成本层（`branches/cost_layer/cost_utils.py`）
- 分项：佣金万2.5双边(5bp) + 印花税千0.5[2023.8后,卖出](5bp) + 过户费万0.1双边(0.2bp) = 10.2bp
- 平方根冲击：`impact = c × sqrt(trade/daily)`，c=0.01（经验保守，可校准）
- **完整性**：分项（非 11bp 笼统）+ 连续冲击（非 1%/5% 分层）

## 阶段二（#11）-> 决策门 B

### 预登记（`branches/factor_momentum/登记簿.md`）
- K=12, k∈{1,3,5}, g=month, N=6（TSFM+CSFM×3，实际独立 N 由 TSFM=CSFM 等价时降）
- 跑前登记，防过拟合

### #11 2.2 选股级回测（`phase2_stock.py`）
- TSFM/CSFM × k：放行因子的 Top10 合并去重等权
- 训练 2016-2022 选样本内夏普最高，OOS 2023-2026
- **完整性**：选股级（Top10 合并，非因子级 factor_map ret 均值）

### #11 2.4 block bootstrap（`block_bootstrap.py`）
- k5 月收益 block bootstrap p 值（optimal block, H0: 均值=0）

### #11 2.5 PBO/DSR（`pbo_dsr.py`）
- 完整 CPCV：purge（边界 ±embargo 月去 train/test 泄漏）+ embargo（test 后隔离）+ 多 split(6/8/10)
- DSR Bailey（N=实际独立, T, skew/kurt 精确）
- **完整性**：purge + embargo + 多 split（非固定 6 份无 purge）

### #11 2.6 护栏（`guard_fm1.py`）
- FM-1（因子动量）vs 纯个股动量（252 天涨幅 Top10）相关 ≤0.8

### 决策门 B（毛收益口径，成本未接入时）
- PBO<50% + DSR<0.95 + 护栏通过 + 毛收益正 -> "候选，待成本复核"
- 任一不过 -> 阴性归档

### 阶段二b 成本复核（#9✅后）
- 扣成本重跑 OOS（用 #9 cost_utils）
- 最终判决：扣成本后正 + 跑赢固收+4.5% -> 实盘；否则废弃

## 脚本入口表

| 步 | 脚本 | 产出 |
|---|---|---|
| #7 NW | factor_pers_B.py, factor_persistence.py | t 值（NW 修后） |
| #5 block | diagnose.py block_bootstrap_ci | CI/p（optimal block） |
| #5 诊断 | diagnose.py | 决策门 A |
| #3 Decile | decile.py | 因子用法（市值加权+单调t） |
| #4 多头 IC | long_ic.py | 因子分类（top N+NW t） |
| #8 FDR | fdr_correct.py | fdr_pass（有效 N） |
| #9 成本 | cost_utils.py + eval_lowvol_h20_cost.py | 扣成本收益（分项+平方根） |
| #11 2.2 | phase2_stock.py | 策略净值（选股级） |
| #11 2.4 | block_bootstrap.py | 显著性 p |
| #11 2.5 | pbo_dsr.py | PBO/DSR（完整 CPCV） |
| #11 2.6 | guard_fm1.py | 护栏相关 |

## 判定阈值表

| 阈值 | 值 | 来源 |
|---|---|---|
| MinTRL 有效 block | >10 | 设计 §4 |
| AR(1)>0 占比 | 对标 GK 91% | 设计 §3.2 |
| 转移矩阵 P | CI 下界 > 基准 | 设计 §3.2 |
| IC 强弱 | >0.02 | factor_decay_utils |
| NW max_lag | max(自动, 持有期-1) | #7 |
| FDR q | 0.10 | 设计 §10 |
| PBO | <0.50 | 设计 §4 |
| DSR | <0.95 | 设计 §3.4 |
| 护栏相关 | ≤0.80 | 设计 §3.4 |
| 跑赢固收+ | 4.5% 年化 | §1 |

## 完整性要求（不简化点，新因子走流程时必查）

1. NW t：`max_lag=max(自动,19)`，所有用 NW 的脚本
2. block：Politis-Romano optimal（数据驱动，不固定 6）
3. Decile：市值加权（amount 代理 `get_weights` 封装，未来流通股本替换）+ 单调性 t
4. 多头 IC：top N 扫描（30/50/100）+ NW t
5. FDR：有效 N（特征值校准，非假设独立）
6. 成本：分项（佣金/印花税/过户费）+ 平方根冲击（c 可校准）
7. PBO：完整 CPCV（purge + embargo + 多 split 6/8/10）
8. DSR：Bailey（N 实际独立, skew/kurt 精确）
9. 选股级：Top10 合并去重（非因子级 factor_map ret）

## 当前结论（38 因子库，2026-07-28 全盘重做后）

- **决策门 A**：转移矩阵阳性（χ² p=1.3e-13，CI 下界 > 基准），AR(1) 75.7% 弱 -> 进阶段二
- **决策门 B**：PBO 多 split(6/8/10)=0/0.071/0.020 全通过，DSR 0.094，护栏 0.404 通过，毛收益正 -> 形式候选；但 2.4 不显著(p>0.05) + 选股级训练负(-0.023) -> **归档（候选标记保留）**
- **有效 N=4.2**（因子 zoo 高冗余，38 因子实际 4.2 独立维度）
- **lowvol 存活**：扣成本夏普 2.44 > 1，年化 14.9% > 固收+4.5%（#12 确认）
- **因子动量信号弱**，归档；lowvol 唯一存活策略
- alpha_016：#3 d1_best（D1 组级好）+ #4 top30 IC 负（精排反向）-> 选 D1 组不精排
- alpha_044：#3 d1_collapse（D1 塌陷）+ #4 多头 IC 弱 -> 尾部差，选 D2/D3
