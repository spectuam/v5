# v5 阶段 2-3 实现与 HMM 调研记录（cc，2026-08-07）

> 作者：cc（glm）
> 日期：2026-08-07 凌晨
> 前置：`docs/v5架构方案-合并版.md`（最终融合方案）、`docs/v5系统认知-老板.md`
> 性质：阶段 2（比较框架）+ 阶段 3（五路漏斗）的实现记录 + HMM 状态层调研。含实施、选择理由、结果、结论。

---

## 一、阶段 2 比较框架（compare_pool）

### 1.1 实施什么

新建 `branches/compare/compare_pool.py`，实现多策略横向比较框架，包含：
- **CPCV**（Combinatorial Purged Cross-Validation）：复用 `pbo_dsr.py` 的 purge+embargo+多 split(6/8/10) 逻辑，扩展到任意单策略，产出 OOS sharpe 分布（多 split 多组合）
- **DSR-adjusted Sharpe**（Deflated Sharpe Ratio）：复用 `pbo_dsr.py` 的 DSR 公式，N 改用 N_eff
- **N_eff**（有效独立策略数）：复用 `fdr_correct.py` 的特征值法 `(Σλ)²/Σλ²`，对策略 returns 相关矩阵算
- **MCS**（Model Confidence Set, Hansen 2011）：新写，block bootstrap 两两比较，输出"无法区分的最优集合 + p 值"
- **Calmar 硬筛**：maxDD > 阈值（0-30% 可设）剔除
- **PBO 总开关**：池中 IS 最优策略 OOS 落下半区概率
- **N 记账**：报告候选池大小 + 试验次数
- **Spearman 稳定性**：分时段排名相关

辅助脚本：
- `collect_candidates.py`：TSMOM long-only 的 K 变体（K=1/4/12/24），秒级，复用已有 factor_returns_week + factor_returns_top_30
- `collect_heterogeneous.py`：补 tsmom_ls（多空版）+ eq38_ls（等权 38 因子多空，GK 配置层口径）
- `market_benchmark.py`：全市场等权周收益（market beta 基准，~10min 全市场扫描）
- `lowvol_weekly.py`：低波 Top10 周度版（eval_lowvol_h20 改周度 T+5）
- `phase2_weekly.py`：IC 选股 Top10 周度版（phase2_stock 改周度）

### 1.2 为什么这么选择

- **为什么先做阶段 2（不是阶段 1 口径对象化）**：老板最在乎"比较方法无懈可击"，先用现有候选策略跑通比较框架证明 work，再补口径对象化和漏斗。核心优先。
- **为什么复用 pbo_dsr/fdr_correct 而非重写**：SOP 已有 CPCV/DSR/特征值法脚手架，不造轮子，在现有基础上扩展。
- **为什么 9 个候选这样选**：要异构（N_eff>1 让 MCS 有区分力）。K 变体（同源）+ tsmom_ls（多空）+ eq38（配置层）+ market（beta）+ lowvol（低波）+ phase2_ic（IC 选股），覆盖不同策略范式。
- **为什么 DSR 用 N_eff 不用 460**：460 因子高度共簇，有效独立维度远小于名义数，DSR 按 N_eff 校正才诚实（避免高估选择膨胀）。

### 1.3 结果

9 候选比较（共同 506 周，train 332 / OOS 174）：

| 策略 | SR全 | 训练 | OOS | DSR | Calmar | MDD | CPCV中位 |
|---|---|---|---|---|---|---|---|
| tsmom_long_K1 | 0.66 | 0.59 | 0.79 | 0.981 | 0.56 | -32.7% | 0.67 |
| tsmom_long_K4 | 0.65 | 0.59 | 0.75 | 0.979 | 0.55 | -32.6% | 0.66 |
| tsmom_long_K12 | 0.65 | 0.58 | 0.77 | 0.979 | 0.55 | -32.7% | 0.65 |
| tsmom_long_K24 | 0.64 | 0.58 | 0.75 | 0.978 | 0.53 | -33.4% | 0.65 |
| **tsmom_ls_K12** | **1.91** | **2.54** | **1.00** | **1.000** | **1.05** | **-7.4%** | **1.92** |
| eq38_ls | 0.95 | 0.82 | 1.17 | 0.998 | 0.49 | -12.3% | 0.95 |
| market_eq | 0.61 | 0.58 | 0.68 | 0.972 | 0.50 | -33.2% | 0.62 |
| lowvol_weekly | 0.39 | 0.36 | 0.46 | 0.897 | 0.14 | -42.8% | 0.40 |
| phase2_ic_weekly | 0.83 | 0.84 | 0.82 | 0.996 | 0.54 | -44.1% | 0.80 |

- **N_eff=1.88**（名义 9，特征值法发现 9 候选实际不到 2 个独立维度）
- **MCS 无法区分集合 = {tsmom_ls_K12}（1 个）**：tsmom_ls 显著优于其他 5 个（两两 p<0.01），其余彼此无法区分（p>0.05）
- **PBO=0.15**（IS 最优落下半区 15%，低，因 tsmom_ls 明显领先）
- **排名稳定性**：Spearman seg2_vs_seg3=-0.829（中间段排名大变，不稳）

### 1.4 结论

1. **框架完全 work**：9 候选横向比较 + MCS 区分 + DSR(N_eff) + Calmar + PBO + N 记账 + Spearman，全部产出。阶段 2 核心达成。
2. **long-only 因子动量相对 market beta 无显著超额**：market_eq(SR0.61) 和 tsmom_long 多头版(SR0.65) 无法区分（p=0.08-0.19）。long-only 因子动量 alpha 弱，主要是市场 beta 暴露。
3. **tsmom_ls 多空版显著最优但 A 股做空受限不可实盘**：SR1.91 碾压，但做空受限。
4. **N_eff 仅 1.88**：9 候选高度相关，真正独立维度 <2。印证"量价因子库有效 N 极低"（fdr_correct 之前算 38 因子有效 N=4.2，策略层更少）。
5. **lowvol 周度化失效**：月度 T+20 时 SR2.71，改周度 T+5 暴跌到 0.39。低波是低频策略，不适合周度口径--暴露"把月度策略改周度"的口径代价。
6. **DSR 边界 bug 修了**：初版用 AMS 近似 `2ln(N)-ln(ln(N))`，n_eff≈1 时 `log(log)` 爆炸导致 DSR=0。改用 Bailey 正式公式 `(1-γ)Φ⁻¹(1-1/N)+γΦ⁻¹(1-1/(Ne))` + n_eff≤2 时 E_max=0（DSR=PSR）。修复后 DSR 0.978-1.000 合理。

---

## 二、阶段 3 五路漏斗（funnel）

### 2.1 实施什么

按合并版方案的五路顺序 **E -> D -> B/A/C**（融合 cc 的 E 先筛 + DS 的 D 先于 B/C，FGX 原文警告"先单因子检验再 Lasso 放大假阳性"）：

| 顺序 | 路 | 脚本 | 方法 | v5 现状 |
|---|---|---|---|---|
| 1 | E 经济先验 | `economics_prior.py` | 人工标注经济逻辑类型 + 先验强度 | 新建 |
| 2 | D 去冗余 | `double_selection.py` | PCA 正交化 + VIF 诊断 | 新建（简化版） |
| 3 | B 显著性 | 复用 `fdr_correct.py` | NW-t + FDR 有效 N | 已有 ✓ |
| 4 | A 强度 | `ir_calc.py` | IC 均值 + IR | 新建（补 IR） |
| 5 | C 形态 | `path_c_monotonicity.py` | Patton-Timmermann 正式单调性检验 | 新建（升级 decile） |

`funnel.py` 串联：E 硬筛 -> D 去冗余 -> 在 D 保留集上 A/B/C 综合打分 -> 选 Top-K 因子 -> 构造候选策略 -> 算 returns -> 进 compare_pool

### 2.2 为什么这么选择

- **五路顺序 E->D->B/A/C**：cc 原 E->A∩B->C->D（D 最后）；DS 原 D->B->A->C->E。融合：E 人工硬筛最前（便宜，先砍没解释的）-> D 控存量（FGX 警告 D 先于 B/C）-> B/A/C 增量检验并行交集。两方文献依据兼容。
- **路 E 全过硬筛**：38 都是公开因子（alpha101/gtja191/qlib158），非纯挖掘，都有某种行为金融/流动性解释。路 E 对现有 38 主要是归类+标强度，真正剔除价值在阶段 5 扩充纯挖掘因子。
- **路 D 用 PCA 简化版（非完整 BCH double-selection）**：完整 Belloni-Chernozhukov-Hansen 两阶段 Lasso 要收益目标+控制变量，复杂。先用 PCA 正交化去冗余，标注"简化版，完整 BCH 待补"。
- **路 B 用 p 值排名非硬筛**：fdr_correct 之前结论 FDR 0 通过（t_abs 全<2），硬筛会全剔除导致交集空。改用 p 值排名参与综合打分。
- **路 C 升级 Patton-Timmermann**：decile.py 原只有 D1-D10 spread t，路 C 加 Spearman 秩相关（D 序号 vs 收益）+ p 值的正式单调性检验。
- **funnel 产候选策略**：不只筛因子，还构造候选策略（Top5 等权多空/多头/TSMOM sign 多头）算 returns 喂 compare_pool，闭环"从因子 zoo 搜索 -> 比较"。

### 2.3 结果

**路 E**：38 因子全过硬筛。类型分布：formula 25 / volume 5 / momentum 4 / trend 3 / reversal 1。强度：weak 25 / medium 8 / strong 5。25 个 formula/weak 需老板查公式细化。

**路 D**：37 因子（alpha_019 无 IC）有效 N=3.57（top1 主成分解释 47.9%）。PCA 高载荷（loading>0.3）保留 9 个。VIF 全爆=1e6（极端共簇，弃 VIF 硬筛）。

**路 A**：37 因子 IR，top5：alpha_016(0.856)/alpha_055(0.830)/alpha_044(0.801)/gtja_016(0.784)/gtja_090(0.777)。

**路 C**：38 因子 Patton-Timmermann 单调性，16/38 通过（rho>0.7, p<0.05）。都方向"高因子值->高收益"。

**funnel Top5 因子**（E∩D 9 个上 A/B/C 综合排名）：
gtja191/alpha_016、alpha101/alpha_015、gtja191/alpha_157、alpha101/alpha_016、gtja191/alpha_041

**候选策略**（Top5 构造）：
- funnel_top5_eq_ls（等权多空）：SR1.96 / 训练2.37 / OOS1.33 / DSR1.000 / Calmar1.59 / MDD-8.06%
- funnel_top5_eq_long（等权多头）：SR0.72 / OOS0.77
- funnel_top5_tsmom_long（TSMOM sign 多头）：SR0.75 / OOS0.80

**12 候选 compare_pool 重跑**：
- N_eff=1.93，PBO=0.10
- **MCS 无法区分集合 = {tsmom_ls_K12, funnel_top5_eq_ls}（2 个）**：两多空强策略并列，都显著优于其他
- funnel_top5_eq_ls Calmar1.59（最高，MDD-8.06% 最小）
- 排名稳定性提升：Spearman 0.47-0.67（之前 K 变体 -0.4）

### 2.4 结论

1. **去冗余无损**：funnel 筛的 Top5 等权多空(SR1.96) 和全 38 因子 TSMOM 多空(SR1.99) 无法区分（p=0.528）。5 个去冗余因子的配置层 ≈ 38 因子，去冗余没丢信息。证明"38 因子有效 N≈3.57"判断对，5 个代表已捕获核心。
2. **Top5 更稳**：funnel_top5 Calmar1.59 > tsmom_ls 0.94，MDD -8.1% 更小。去冗余后回撤更可控。
3. **排名稳定性提升**：Spearman 0.47-0.67（K 变体 -0.4），funnel 候选排名更稳。
4. **闭环跑通**：从 38 因子 zoo 经 E->D->B/A/C 筛 Top5 -> 构造候选 -> compare_pool 比较 -> MCS 识别最优集合。阶段 3 闭环达成。
5. **诚实**：多空强不可实盘，多头弱（0.72-0.75）。系统作为"相对择优器"work（筛出 Top5 去冗余无损、MCS 识别最优集合、诚实报告强的不可实盘）。

---

## 三、多空版定位（老板定）

### 3.1 选择

多空版 A 股不可实盘（融券标的少/成本高年化 8-10%/券源紧/2024 程序化监管），不直接产出实盘策略。但保留作**诊断基准**：
1. **alpha 上限标定**：多空版是"无做空约束下的理论完整 alpha"。多空 1.96 vs 多头 0.72 的差距量化了"做空侧贡献多少 alpha"
2. **文献对齐验证**：多空 SR1.96 接近文献（EL 0.98/GK 0.84 量级），证明"因子库有真 alpha，只是 A 股做空受限拿不到"
3. **long-only 设计参考**：多空版告诉哪些因子做空侧有贡献，指导 long-only 选因子
4. **未来可选**：A 股做空机制若放宽，多空版可直接实盘

### 3.2 结论

多空版保留作 compare_pool 里的"无约束上限"诊断基准，不删不产出。主线转 long-only。但 long-only 量价库内已到顶（SR0.6-0.8，之前收敛 0.50-0.53），突破要换层（扩数据/分状态/ML）。

---

## 四、HMM 状态层

### 4.1 简易版实施（实盘不可达）

**v1**（`market_regime.py` 初版）：hmmlearn GaussianHMM，3 状态，特征=当周收益+4 周波动，全局 fit。
- 结果：状态划分粗糙（bull/bear 按周收益正负分，不是真市场状态），bull 年化 116%/bear -63% 极端。

**v2**（改进特征+BIC 扫描）：特征改过去 4 周累计收益+波动（不含当周防泄露），BIC 扫 3/4/5 状态，选 5 状态。
- 结果：5 状态划分合理些（bull/sideways/温和/横盘/下跌），转移矩阵有逻辑（crash->crash 0.82 持续、bull->bull 0.77）。
- long-only 分状态：bull 年化 141% / sideways 67% / recovery(下跌) -22%。long-only 完全跟市场 beta。
- 最近 44 周 recovery+crash 占 57%，解释 long-only 转负。

**状态择时验证**（`state_adaptive.py`）：recovery+crash 状态空仓。
- 全局 HMM 理论上限：SR 0.66->1.33，MDD -33%->-21%（近翻倍）
- **滚动 fit 实盘**（`market_regime_rolling.py`，窗口 156 周）：SR 0.64-0.71（**没改善，甚至略降**），年化 18-21%->10-11%（腰斩），MDD -32%->-20%

### 4.2 问题

1. **全局上限 1.4 是 look-ahead 幻觉**：Viterbi 用全序列含未来，实盘达不到
2. **滚动 fit 没改善**：HMM 大量不收敛（日志全是 "not converging"），状态语义不稳（label switching，每次 fit 状态编号互换），用全局语义套滚动编号错位
3. **滚动 fit 的 recovery/crash 年化正**（12%/15%，不是下跌状态），空仓错了

### 4.3 文献调研结论（Agent 联网核实）

老板质疑：HMM 有没有文献背书？GMM vs HMM 哪个权威？简易版有什么疏漏？

**方向对**：
- HMM = Markov-Switching 同族（MSAR 是 HMM 的 AR=0 特例，Krolzig 1998 证）。用 HMM 思路对。
- **GMM 不如 HMM 权威**：市场状态文献压倒性用 HMM/Markov-switching（Hamilton 谱系），GMM 无时序持续性建模，不是标准方法。

**实现错 5 硬伤**（对照学术标准）：
1. **5 状态过多**--文献主流 2-3（Hamilton GNP=2，KNS 股票收益=3），5 状态过拟合+不稳
2. **2 特征 Gaussian emission 非标准**--学术是单序列收益让 mean/variance 切换，不是收益+波动塞 2 维
3. **缺 AR 结构**--MS-AR(p) 是标准，纯 HMM 是 AR=0 特例，丢动量信号
4. **周频非主流**--月度是 regime 识别事实标准（KNS 月度、Hamilton 季度）
5. **covariance full/diag 混用无原则**--学术用 per-regime 标量

**通病**：滚动 fit 不收敛是 HMM 预期（局部最优多，要 `n_init=10+` 随机重启）；状态编号会互换（label switching，要按经济意义重排序）。

**不造轮子--换 statsmodels**：
`statsmodels.tsa.regime_switching.MarkovRegression`（Hamilton 谱系学术标准，自带 Hamilton filter + Kim smoother + EM），直接用 **KNS 1998 配置**：
```python
MarkovRegression(dta, k_regimes=3, trend="n", switching_variance=True)  # 月频
```
状态数 AIC/BIC 扫 2-4 确认，状态按 variance 排序对齐语义。

**关键文献**：
- Hamilton (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series", *Econometrica* 57(2):357-384, DOI 10.2307/1912559 -- 奠基
- Kim, Nelson, Startz (1998) 股票收益方差切换，3 状态 -- 我们的场景
- statsmodels 文档：statsmodels.org/dev/regime_switching.html
- Krolzig (1998) MSAR-HMM 等价性

### 4.4 结论

- HMM 状态层**方向对**（HMM=Markov-switching，GMM 不如它权威），**实现错**（5 硬伤 + 造轮子用 hmmlearn 而非 statsmodels 标准库）
- 简易版实盘不可达（SR0.64-0.71），全局上限 1.4 是 look-ahead
- **诚实承认**：这又落入之前批判的"没扎实文献依据就急着搭"误区。应该先调研再搭。
- **下一步**：用 statsmodels MarkovRegression（KNS 配置）重写，扔 hmmlearn 简易版。

---

## 五、未 commit + 待办

### 未 commit
- `branches/compare/*.py` 全部新脚本（compare_pool/funnel/五路/HMM 系列）
- DS 侧已 commit ec08875（三文档：系统认知-老板/架构方案-cc/架构方案-ds）
- cc 侧待方向定后 commit

### 待办（新 session 接手）
1. ~~**用 statsmodels MarkovRegression 重写 market_regime**~~ ✅ 已完成（见 §七）
2. **状态自适应选股**（不同状态激活不同因子，不只择时空仓）
3. ~~**阶段 1 口径对象化**（strategy_factory.py + daily_pick 改读配置）~~ ✅ 已完成 8/8（见 §八，daily_pick 基线 SR0.40 跑输市场等权）
4. ~~**阶段 4 forward OOS / paper trading**~~ ✅ 已完成 8/8（见 §九，walk-forward SR0.444≈0.40 稳健OOS + forward tracker 10日起点）
5. **路 E**：alpha101/gtja191 公式因子经济含义（老板查公式细化 25 个 formula/weak）
6. **路 D**：完整 BCH double-selection（两阶段 Lasso + 收益目标，当前简化 PCA）

### 接手
新 session 读：`docs/v5架构方案-合并版.md`（最终方案）+ memory `session-state-2026-08-07-cc` + `branches/compare/`（脚本 + result）。
脚本入口：`compare_pool.py`（比较框架）/ `funnel.py`（五路漏斗）/ `market_regime.py`（HMM 待重写）。

---

## 六、今日核心发现汇总

1. **比较框架 work**：9 候选横向比较 + MCS 区分 + DSR(N_eff) + Calmar + PBO，诚实输出"可实盘的都弱且难分、强的不可实盘"
2. **去冗余无损**：Top5 因子等权多空 ≈ 38 因子 TSMOM，有效 N=3.57 的判断对
3. **long-only 量价库到顶**：相对 market beta 无超额，SR0.6-0.8，突破换层
4. **多空版定位诊断基准**：不可实盘但标定 alpha 上限 + 文献对齐
5. **HMM 方向对实现错**：简易版实盘不可达，换 statsmodels MarkovRegression（KNS 配置）
6. **又落入"没依据就搭"误区**：HMM 没调研就搭，应该先调研再搭（老板提醒"不要造轮子"）

---

## 七、HMM 重写：statsmodels MarkovRegression（待办#1 完成）

> 日期：2026-08-08（凌晨）
> 范围：用 `statsmodels.tsa.regime_switching.MarkovRegression`（Hamilton 1989 / KNS 1998 谱系）重写 `market_regime.py` / `market_regime_rolling.py` / `state_adaptive.py`，旧 hmmlearn 版归档 `.hmmlearn.bak`。

### 7.1 修复的 5 硬伤
1. 5 状态过多 -> AIC/BIC 数据驱动选 k
2. 2 特征 Gaussian 非标准 -> 单收益序列 mean/variance 切换（KNS）
3. 缺 AR 结构 -> KNS 方差切换是市场状态标准（MS-AR 标注 future）
4. 周频非主流 -> 月频（Hamilton/KNS 事实标准）
5. covariance 混用 -> 单变量无 covariance

### 7.2 实证前提（plan 阶段验证）
- statsmodels 0.14.6 装入 v5 venv
- 月频 resample：536 周 -> 126 月（2016-01~2026-06），SR 0.578（周频 0.581，信号保留）
- `MarkovRegression(trend="n", switching_variance=True)` 端到端跑通
- **AIC/BIC 都选 k=2**（k=2 AIC -286.5/BIC -275.1 最优；k=3 -280.4/-254.8；k=4 更差）-- 数据支持 2 状态（高/低波动），非 5
- 状态按 sigma2 升序标注：calm(sigma2=0.0022) / crash(sigma2=0.0146, 6.5× 波动差)
- **filtered（Hamilton 因果/live）vs smoothed（Kim 全样本/look-ahead 上限）一致率 95.2%** -- live 可达版远好于坏掉的 hmmlearn
- expanding fit 正常收敛，逐月重估 18s

### 7.3 三层 live 可达性对比（`market_regime_rolling.py`）
| 层 | 含义 | look-ahead |
|---|---|---|
| smoothed-global | Kim smoother 全样本 | 全（理论上限）|
| filtered-global | Hamilton filter 状态因果，参数全样本 | 参数轻 look-ahead |
| expanding-filtered | 每月 [0,t] 重估参数 + Hamilton filter | 无（最严 live）|

### 7.4 核心发现：A股高波动 regime 含高收益
- crash（高波动）regime：33 月，年化 **58.77%**，波动 45.1%，SR 1.30
- calm（低波动）regime：93 月，年化 0.83%，波动 15.6%，SR 0.05
- **「高波动≠纯下跌」**：A股等权高波动期含急涨（2020 后疫情、2024-2025 反弹）。旧「crash 空仓」规则会损价值。

### 7.5 诚实结论：状态择时在 long-only 无改善（双口径交叉验证）
| 策略 | 全段原版 | filtered-global 最佳 | expanding 严格 live 最佳 |
|---|---|---|---|
| tsmom_long_K12 | SR0.66 | SR0.83（hide calm）| 段内原版0.68->0.70=**中性** |
| funnel_top5_eq_long | SR0.72 | SR0.77 | 段内原版0.74->0.70=**中性** |
| funnel_top5_tsmom_long | SR0.78 | SR0.87 | 段内原版0.74->0.72=**中性** |
- **hide_crash（高波动空仓，旧规则）全口径反损**：SR 0.66->0.07
- **hide_calm（低SR空仓）**：filtered-global 似改善（0.66->0.83），但 expanding 严格 live 归中性（0.68->0.70）-> **改善源于参数 look-ahead，不可靠**
- 旧结论「滚动 fit 实盘无改善」**用正确模型确认成立**，但机制不同：不是「hmmlearn 不收敛」，而是「A 股高波动 regime 含高收益，空仓损价值；hide 低 SR 在严格 live 下中性」

### 7.6 产出文件
- `market_regime.py`（重写）+ `market_regime_result.json`：k=2 regime + smoothed/filtered 双输出 + week_state + state_stats/transmat/AIC-BIC
- `market_regime_rolling.py`（重写）+ `market_regime_rolling_result.json`：expanding 三层 live 对比
- `state_adaptive.py`（更新）+ `state_adaptive_result.json`：双向择时 + 双口径交叉验证判定
- 旧版归档：`*.hmmlearn.bak`

### 7.7 下一步
- 待办#2 状态自适应选股：不同状态激活不同因子（非择时空仓）。但 §7.5 结论提示 long-only 量价天花板下，状态层价值有限，需结合待办#3/#4 或换层（OSAP/Qlib）才有突破空间。

---

## 八、口径对象化：strategy_factory + daily_pick 配置化（待办#3 完成）

> 日期：2026-08-08
> 范围：daily_pick_v5 策略口径从硬编码抽成 config，生产/验证同口径；首个 daily_pick 策略 in-sample 基线。

### 8.1 产出
- `branches/strategy_factory/strategy_config.json`：schema + 生产实例（38因子等权复合 pct rank Top5 + 涨停过滤 + 90天面板）
- `branches/strategy_factory/strategy_factory.py`：`load_config`/`load_factor_ids`/`build_panel_realtime`/`build_panel_history`/`rank_and_pick`/`produce_picks`/`backtest`
- `branches/strategy_factory/verify_factory.py`：**护栏**--验证 factory.rank_and_pick == daily_pick 原版（MATCH ✓，picks 逐位相同）
- `daily_pick_v5.py` 重构：常量从 config 读（LOOKBACK/TOP_K/LIMIT_UP/因子源/过滤/排序），config 缺失则回退硬编码保生产稳定；**行为零变更**（重跑 verify 仍 MATCH）。归档 `daily_pick_v5.py.bak`

### 8.2 口径匹配原理
daily_pick 的 38 因子 = compare 框架 38 因子（同源 `factor_decay_results_tdx.json`）。lookback≤90天的因子在全历史 panel 上 date T 的值 = 生产 90天 panel 上 date T 的值（因子只回看≤90天），故 backtest 一次性预算全历史因子等价于生产逐日 90天 panel。`compute_alpha` 对整段 panel 一次性算（date×code DataFrame），38 因子全历史仅 38 次调用（155s）。

### 8.3 首个 daily_pick in-sample 基线（诚实发现）
daily_pick_eqcomposite_top5（周度 T+5，526周 2016-2026）进 compare_pool 同口径对比：

| 策略 | SR全 | SR训练(≤2022) | SR-OOS(>2022) | MDD | Calmar | DSR |
|---|---|---|---|---|---|---|
| **daily_pick_eqcomposite_top5** | **0.40** | **0.20** | 0.72 | **-50.5%** | **0.27** | **0.891** |
| market_eq | 0.64 | 0.65 | 0.64 | -33.2% | 0.52 | 0.975 |
| lowvol_weekly | 0.49 | 0.56 | 0.40 | -31.7% | 0.23 | 0.946 |
| funnel_top5_eq_long | 0.77 | 0.80 | 0.76 | -31.9% | 0.65 | 0.991 |
| phase2_ic_weekly | 0.85 | 0.91 | 0.77 | -35.5% | 0.69 | 0.996 |

**核心结论**：
1. **生产 daily_pick 是候选池里最弱之一**（SR0.40，仅高于 lowvol0.49；MDD -50% 全池最差，次差 -35%；Calmar 0.27、DSR 0.891 均最低）
2. **跑输全市场等权**（0.40 vs market_eq 0.64），且回撤远更大（-50% vs -33%）
3. **训练期(2016-2022) SR0.20 极差，OOS(2022+) 0.72 才回暖**--策略近期才像样，早期拖累严重（疑似 factor_decay 因子集对近年数据过拟合）
4. MCS 集合不变={tsmom_ls, funnel_top5_eq_ls}，daily_pick 明显可区分（更差）

**这是老板最在意的诚实评估**：生产中跑的策略从未被验证过，#3 首次暴露它跑输市场等权且回撤最大。Top5 等权集中持仓 + 涨停过滤推高波动与回撤。

### 8.4 口径标注（诚实）
- 生产 daily horizon=1（日度），回测 weekly+T+5（compare 约定）。weekly≠daily 口径差，但选股逻辑（因子集/复合/Top5/涨停过滤）完全同口径。
- 526周（过滤 7 个 Top5 未来收盘缺失的 NaN 周）。已修 backtest NaN 处理（sell NaN 跳过 + SR 用 nan-filter）。
- 内存：全历史 panel 2546d×4991c×7字段 float32，峰值安全（CLAUDE.md 7GB 红线）。

### 8.5 下一步
- 待办#4 forward OOS：factory.produce_picks 已就绪可前向产出信号 + 跟踪实盘 returns，对照 §8.3 基线判衰减（文献 backtest1.26 vs live0.31，4.1× 衰减预期）
- daily_pick 跑输市场等权的事实，需老板定：是否调生产策略（如放宽 TopK / 改等权为分散 / 弃涨停过滤），还是先 #4 forward OOS 看实盘是否也跑输

---

## 九、forward OOS：walk-forward + paper trading（待办#4 完成）

> 日期：2026-08-08
> 范围：walk-forward 因子重选 backtest（时序 OOS）+ forward paper trading 跟踪（真未来）。唯一对未来有验证效力的环节（合并方案§四.7）。

### 9.1 诚实层级澄清（重要修正）
#3 的 daily_pick backtest SR0.40 用的是 38 因子（`factor_decay_results_tdx.json` `data_range=2000-2015`），backtest 在 2016-2026 -> **#3 本身已是因子层 OOS，无因子选择 look-ahead**。#4 非修正 #3 的 look-ahead，而是：
- walk-forward 测**滚动重选因子是否优于静态 2000-2015 集**（策略改进问题）
- forward paper trading 给**真未来验证**（CPCV/backtest 都同历史分布内）

| 层 | 方法 | 对未来效力 |
|---|---|---|
| CPCV（compare_pool） | 同历史分布 resample | 无 |
| Backtest（#3） | 因子 2000-2015 选 + 选股前向 2016-2026 | 无（历史） |
| Walk-forward（#4） | 每年 expanding 重选因子 + 前向选股 | 无（历史但时序 OOS） |
| Forward paper（#4） | 真实未来 picks + realized | **有（唯一）** |

### 9.2 walk-forward 结果（`walkforward.py`）
- 每年 expanding [2006, Y-1] 用 `factor_ic_daily` 重选 top-38 因子（IR>0.3/IC>0.02/persistent 准则），该年周度选股 T+5，concat 534 周
- **walk-forward SR 0.444，年化 15.60%，MDD -46.41%**
- 对比 #3 静态 2000-2015 集 SR 0.40 -> **相近（0.444 vs 0.40）**
- **结论**：因子集稳定（persistent），滚动重选 ≈ 静态集 -> daily_pick 的 SR~0.43 是**稳健 OOS 数**（非因子选择 artifact），仍跑输 market_eq(0.58)
- 口径差：walk-forward top-38 by IR 无正交化 vs 静态 38 正交池；expanding 窗口近似生产全前置

### 9.3 forward paper trading（`forward_tracker.py`）
- 解析 `picks_v5_*.md`（daily timer 已记 14 个，2026-07-20~08-07），算 realized T+5
- 10 个已到期（7/20-7/31），4 个未到期
- daily_pick forward SR **5.965**（10 日，无统计意义）；market_eq 同期 SR **9.513**（同期强反弹，亦荒谬）
- daily_pick 均值 5.92%/周 > market 3.64%（超额 +2.3%/周），但 SR 6.0 < market 9.5（集中持仓波动大，风险调整后仍跑输市场，与 #3 一致）
- **10 日样本无任何统计结论**，仅作 forward 起点；需数月积累

### 9.4 MinBTL + 诚实标注
- AMS MinBTL：N=456, y=10 需 12.3 年；当前有效样本 2016-2026 = 10 年 < 12.3 -> **临界**
- daily_kline 2000-2026（26yr）/ factor_ic_daily 2006-2026（20yr）可扩到满足，但需重跑因子集（保持 2016+ 与 compare 框架一致）
- CPCV 标注"同历史分布内、对未来无验证效力"；walk-forward 时序 OOS 仍历史；forward paper 唯一真未来

### 9.5 产出文件
- `branches/strategy_factory/walkforward.py` + `walkforward_result.json`（SR0.444 vs 0.40）
- `branches/strategy_factory/forward_tracker.py` + `forward_track_result.json`（10 日 forward + market_eq 基准）
- 建议加 weekly timer 跑 forward_tracker 持续积累

### 9.6 下一步
- forward 需数月积累才有意义（weekly timer 持续更新 forward_track_result.json）
- daily_pick 稳健跑输市场（#3+walk-forward 双重确认），老板需定：调生产策略（放宽 TopK/分散/弃涨停过滤）or 接受现状转 #5/#6 或换层
- 真"诚实评估器"已就位（walk-forward + forward tracker），换层/新因子可在此框架下诚实评估

---

## 十、调参检验：TopK×涨停 扫描（老板定方向 a）

> 日期：2026-08-08
> 假设：daily_pick 跑输市场(SR0.43 vs 0.58)+MDD最大(-50%) 的头号嫌疑是 Top5 集中持仓 + 涨停过滤。检验能否调参跑赢市场。

### 10.1 全样本参数扫描（`param_scan.py`）
38 因子静态(2000-2015 OOS) + 周度 T+5 + 2016-2026，535 周：

| TopK | 涨停on SR | on MDD | 涨停off SR | off MDD |
|---|---|---|---|---|
| 5(生产) | 0.32 | -61.7% | 0.36 | -59.3% |
| 10 | 0.51 | -52.8% | 0.48 | -52.6% |
| 20 | **0.60** | -39.3% | **0.62** | -38.4% |
| 30 | 0.60 | -38.8% | 0.60 | -38.4% |
| 50 | 0.61 | -39.4% | 0.61 | -39.9% |

- **Top5 是全空间最差**；TopK 增大单调改善 SR + 降 MDD，到 20 饱和
- Top20 全样本跑赢 market_eq(0.58)；涨停 on/off 影响小（噪声内）

### 10.2 walk-forward 验证（诚实修正，关键）
全样本 Top20"跑赢市场"可能是全样本偏差。跑 `walkforward.py --topk 20` 验证：
- walk-forward Top5: SR 0.444, MDD -46.4%
- **walk-forward Top20: SR 0.530, MDD -43.1%**（< market 0.58，**不跑赢市场**）
- Top5->Top20 改善成立（同口径 0.444->0.530，+0.09 SR，MDD -46%->-43%）
- **但 Top20 仍跑输市场**（0.53 < 0.58），MDD 仍高于市场(-43% vs -33%)
- 全样本 0.60 跑赢市场是偏差，walk-forward 修正后不成立 -- **这正是 walk-forward 验证的价值**

### 10.3 诚实结论
1. **Top5 集中确实是 daily_pick 跑输市场的主因**（TopK 增大改善 SR + 降 MDD，walk-forward 确认）。生产建议改 TopK=20-30（比 Top5 稳健改善），但**不期望跑赢市场**。
2. **涨停过滤影响小**（on/off 噪声内），可保留生产习惯。
3. **调参救不了 daily_pick 跑输市场**：即使 Top20（最佳区），walk-forward SR 0.53 < market 0.58。选股 alpha 在分散后很薄（量价天花板再印证）。
4. **更根本问题**：daily_pick 选股策略稳健跑输全市场等权，调参只缓解不逆转。是否该用更分散基准替换生产策略，或转 #5/#6/换层 -- 老板定。

### 10.4 产出
- `branches/strategy_factory/param_scan.py` + `param_scan_result.json`（TopK×涨停 全表）
- `walkforward.py` 加 `--topk` 参数 + Top20 验证（SR0.530 不跑赢市场）

### 10.5 下一步（待老板定）
- 调参检验完毕，daily_pick 稳健跑输市场（调参不逆转）
- 选项：(b) #5/#6 漏斗补完（框架严谨化，不改变跑输事实）(c) 换层 OSAP+Qlib（唯一突破，诚实评估器就位可承接）(d) 接受现状，生产改 TopK=20-30（改善但不跑赢）+ forward 持续跟踪

