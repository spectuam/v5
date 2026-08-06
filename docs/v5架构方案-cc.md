# v5 架构调研与实施计划（cc 方案）

> 日期：2026-08-06
> 来源：4 批联网核实调研 + v5 现状核对
> 性质：cc 对老板思路的独立调研核实、批判、与可落地方案。**不与 DS 交叉，保证 DS 独立调研。**
> 配套：`docs/v5系统认知-老板.md`（共享输入）
> 老板定位：v5 = 相对择优器（垃圾里挑最有价值/亏最少就成功），和绝对可用解耦。

---

## 一、调研说明

4 批调研（联网核实，部分 DOI 已验证）：
1. 因子筛选多方法交集（12 方法，推荐 5 圈）
2. 因子 zoo 扩充与生成器陷阱（Hou/McLean-Pontiff/DeMiguel/AlphaForge）
3. 策略比较方法论（MCS/StepM/SPA/WRC/PBO/DSR 原文核实）
4. 数据挖掘过拟合 + 量价 alpha 天花板（AMS 公式/MinBTL/衰减实证）

**环境限制**：WebSearch 全程屏蔽；WebFetch 对 academic.oup.com / arxiv / GitHub / NBER 可用，SSRN/ScienceDirect 403。关键数字已硬核实，少数精确阈值标注"待核实"。

## 二、总判断

老板的**"相对择优器"定位被文献支持**（Romano-Wolf 借 Timmermann 原话："simple forecasting schemes, such as equal-weighting various strategies, are hard to beat"；"可能都是垃圾只挑相对最好的"是合理预期）。

但 3 个具体设想要改：
- ① **准确序数排名 -> MCS 无法区分集合**
- ② **复利目标 -> DSR-adjusted Sharpe 排序 + Calmar 硬筛**
- ③ **裸搜 460 -> 5 圈交集漏斗约束**

## 三、能打败老板思路的（8 条，带 DOI）

1. **PBO 数学必然**（Bailey et al. 2014, Notices AMS, DOI 10.1090/noti1105）：N=460, y=10 纯噪声最优 IS 年化 Sharpe≈1.1、OOS=0；MinBTL 需 12.3 年，数据仅 10 年；N/T=3.83（N/T=1 时 IS-OOS 已零相关 p=0.75）。**过拟合被数学保证**。
2. **复利目标更糟**：path-dependent 锁定一条幸运路径，方差 > Sharpe。老板选的标尺让过拟合更重。
3. **量价 alpha 天花板实证**：McLean-Pontiff (JF, 10.1111/jofi.12365) 发表后衰减 58%；Hou-Xue-Zhang (RFS, 10.1093/rfs/hhy131) 65-82% 复现失败；Gu-Kelly-Xiu ML 残值只在 momentum/liquidity/vol 族；GS 理论推论公开数据 alpha 最薄。
4. **"准确序数排名"是错目标**：MCS/StepM/SPA/WRC 全输出"无法区分集合"不排名（arch 实现层确认 "no ranking capabilities"）；Romano-Wolf "选唯一最优 bad idea，等权 hard to beat，trim 不用 pick"；PBO 原文"选最优过程 detrimental 比随机选还差"。
5. **纯挖掘死、有先验活**：AlphaForge (arxiv 2406.18394) GP 在 CSI500 OOS IC 仅 0.37%，纯挖掘天花板 2-4%，成熟因子 5-10%。
6. **MVO 不如等权**：DeMiguel 2009 RFS，1/N 击败 MVO+14 扩展，25 资产需 3000 月(250 年)才 beat 1/N。
7. **危机相关性飙升**：Longin-Solnik 2001 JF，bear 市相关性飙升，分散化危机期不成立。
8. **实证退化**：backtest Sharpe 1.26 vs live 0.31（4.1×）；316 因子多重检验后仅 5-8 个显著。

**诚实修正**：PBO 论文是 2016 JCF（非 2017 JPM）；Chordia 那篇是 JAE（非 JFE）；"N/T>0.1 时 PBO 趋近 1"精确阈值待核实（方向确定：N/T 越大 PBO 越高，N/T≥1 时 IS-OOS 零相关）。

## 四、老板需要的正路（9 条）

1. 目标改 **MCS 无法区分集合 + p 值**（arch 有参考实现），不序数排名。
2. 选策略改**集合内等权 / trim + ensemble**，不排名选 Top-K（Timmermann：等权 hard to beat，trim 不用 pick）。
3. **5 圈交集漏斗**约束搜索空间：E 经济先验硬筛 -> A(IC+IR) ∩ B(NW-t+FDR) ∩ C(decile单调+多空t) ∩ D(Lasso+正交) -> 打分 Top-K 进比较。
4. **DSR-adjusted Sharpe/Sortino 排序轴 + Calmar 硬筛**（剔除回撤超限），复利只做参考展示。
5. 多重检验：**Harvey t≥3 + BH-FDR + DSR 逐策略 + PBO 总开关**（N/T=3.83 必诚实报）。
6. CPCV 产出 **OOS 分布**（多 split 6/8/10），比分布相对位置不比单点；**N_eff 用 PCA 估**（460 可能只有几十独立，DSR 用 N_eff 不用 460）。
7. **forward OOS / paper trading** 是唯一真验证；CPCV 明确标注"同历史分布内、对未来无验证效力"。
8. 扩展谨慎：OSAP 复现 + post-pub OOS + long-only dilution 建模；因子生成器用 Qlib+AlphaGen 当假设生成器（人脑先验过滤，AlphaForge Table 1 做 sanity check：CSI300 OOS IC<1% 即过拟合）；组合用等权/Ledoit-Wolf 收缩不用 MVO。
9. 能活因子有经济解释（动量/价值/规模/盈利/低 beta/质量）--和 v5 复现 TSMOM、放弃 IC 选股偏离文献口径的方向**一致，不是巧合**。

## 五、v5 现状对照

| 环节 | v5 现状 | 缺口 |
|---|---|---|
| CPCV/PBO/DSR | SOP 有脚手架（pbo_dsr.py） | 没横向多策略、没报 N_eff |
| FDR/NW | 有（fdr_correct.py, factor_pers_B） | 未组织进漏斗 |
| decile/long_ic | 有（decile.py, long_ic.py） | 未组织进漏斗 |
| IC 排序 | 有 | 缺 IR |
| Lasso/正交 | 无 | 圆 D 全缺 |
| 经济先验标注 | 无 | 圆 E 全缺 |
| 多策略横向比较 | 无（phase2 只选 best） | 比较引擎全缺 |
| MCS | 无 | 全缺 |
| 同口径对齐 | 散（口径脱节） | 清单未定 |
| forward OOS | 无 | 全缺 |
| daily_pick | 等权投票 Top5 原版 | 待升级 |

**结论**：不是从零，是在现有 SOP 脚手架上补"横向比较 + MCS + 5 圈漏斗组织 + 同口径 + forward OOS + daily_pick 升级"。

## 六、可落地计划（阶段 0-5）

### 阶段 0｜认知对齐（不写代码）
接受 3 项"要改"：序数排名->MCS 集合、复利->Sharpe+Calmar 硬筛、裸搜->5 圈漏斗。+ 接受量价天花板（相对择优器定位）。

### 阶段 1｜比较框架重建（最优先 = "比较方法无懈可击"的落地）
- 1.1 同口径对齐清单：survivorship-free 股票池/同时间窗/同成本模型/Sharpe 风险调整/杠杆波动归一/同 OOS 路径/look-ahead 守卫
- 1.2 多策略横向比较引擎：所有候选同口径同跑，产出每策略 train/valid/test/CPCV-OOS 分布（不是 IC 选一个验证）
- 1.3 CPCV 产出 OOS 分布（多 split 6/8/10），比分布不比单点
- 1.4 实现 MCS：输出"无法区分集合 + p 值"，替代序数排名
- 1.5 多重检验：t≥3 + BH-FDR + DSR 逐策略 + PBO 总开关（N/T=3.83 诚实报）
- 1.6 目标函数：DSR-Sharpe/Sortino 排序轴 + Calmar 硬筛 + 复利参考
- 1.7 N_eff 估算：PCA 降维看 460 实际独立维度，DSR 用 N_eff

### 阶段 2｜5 圈交集漏斗（搜索空间约束 = "多方法圈定比较范围"的落地）
- 圆 E 经济先验标注（人工，第一层硬筛）
- 圆 A 补 IR（v5 有 IC 缺 IR）
- 圆 B 已有 NW+FDR ✓
- 圆 C 已有 decile+long_ic ✓
- 圆 D 补 Lasso+正交化
- 组织漏斗：E -> A∩B -> ∩C -> ∩D -> 打分 Top-K 进阶段 1 比较

### 阶段 3｜真验证
forward OOS/paper trading；CPCV 标注"同历史分布内、对未来无验证效力"；MinBTL 检查（10 年<12.3 年安全线，诚实标注）。

### 阶段 4｜daily_pick 升级
等权投票 Top5 -> MCS 集合内等权/trim+ensemble；生产/验证同口径。

### 阶段 5｜扩展（谨慎）
数据层 OSAP+Qlib Alpha158；因子接入 OSAP 复现+post-pub OOS+long-only dilution；因子生成器 Qlib+AlphaGen 当假设生成器；组合用等权/Ledoit-Wolf 不用 MVO。

## 七、最优先与下一步

**阶段 1（比较框架）+ 阶段 2（5 圈漏斗）最优先**--这俩是老板"搜索比较"的核心，也是 v5 现状缺口最大处。阶段 0 认知对齐是前提。

等老板认方向（或与 DS 方案对照后定），进 plan mode 细化阶段 1+2 具体实现（哪些脚本改、新增什么、怎么接现有 CPCV/PBO/DSR/FDR）。

## 附：关键文献 DOI 清单（可核实）

| 文献 | DOI/URL |
|---|---|
| MCS (Hansen/Lunde/Nason 2011 Econometrica) | 10.3982/ECTA5771 |
| Romano-Wolf StepM (2005 Econometrica) | 10.1111/j.1468-0262.2005.00615.x |
| Hansen SPA (2005) | 10.1016/j.jeconom.2005.04.004 |
| White Reality Check (2000) | 10.1111/1468-0262.00132 |
| PBO (Bailey et al. 2016 JCF) | 10.21314/jcf.2016.322 |
| AMS Pseudo-math (Bailey et al. 2014) | 10.1090/noti1105 |
| DSR (Bailey & López de Prado 2014 JPM) | 10.3905/jpm.2014.40.5.094 |
| Harvey/Liu/Zhu (2016 RFS) | 10.1093/rfs/hhv059 (NBER w20592) |
| AFML (López de Prado 2018) | Wiley ISBN 978-1119482086 |
| McLean & Pontiff (2016 JF) | 10.1111/jofi.12365 |
| Hou/Xue/Zhang Replicating Anomalies (2020 RFS) | 10.1093/rfs/hhy131 (NBER w23394) |
| Gu/Kelly/Xiu (2020 RFS) | 10.1093/rfs/hhaa009 |
| DeMiguel/Garlappi/Uppal (2009 RFS) | RFS 22(7):2407 |
| Longin-Solnik (2001 JF) | 10.1111/0022-1082.00449 |
| AlphaForge (2024) | arxiv 2406.18394 |
| AlphaGen (KDD'23) | arxiv 2306.12964 |
| Chen-Zimmermann OSAP | openassetpricing.com |
| 微软 Qlib | github.com/microsoft/qlib |
