# v5 架构方案（DS 独立版 v2）

> 日期：2026-08-07（v1 之后完成 4 批联网调研，全部核实后更新）
> 依据：`docs/_archive/04_重新整理/v5系统认知-老板.md`（只读此文档，未看 cc 方案，保持双盲）
> 调研：4 个后台 Agent 联网核实（URL + 逐字引用 + 核实日期，证据见 §7 附录）
> 变更：v1 的三点批判经调研后 2 强支持 + 1 支持（含 2 处表述修正），五路交集顺序按文献调整

---

## 0. 一句话判断

老板的"中间路"是对的——约束搜索 + 复利目标 + 相对择优，是标准量化的收敛形态，且与文献强吻合（等权 Top-N 被学术支持为小资金最优默认）。三点批判经 4 批联网调研：**全部成立**，其中两处表述按原文修正。

---

## 1. 三点批判（调研核实版）

### 批判 1：追求"排准确名次"是错目标——正确输出是"无法区分的最优集合"

**证据等级：强支持（顶刊原文逐字）。**

- **MCS（Hansen, Lunde & Nason 2011, Econometrica 79(2)）** 原文："Many applications will not yield a single model that significantly dominates all competitors because the data is not sufficiently informative to give an unequivocal answer"；"MCS 承认数据的局限性——信息含量低的数据给出含许多模型的 MCS"。
- **Romano & Wolf (2005, Econometrica 73(4))** 原文（引 Timmermann 2006）："(i) 选择唯一的、历史记录最好的策略常常是坏主意；(ii) 简单的预测方案，例如对各策略等权加权，很难被击败；(iii) 常常需要把最差的策略修剪掉"。
- **White (2000) RC / Hansen (2005) SPA**：输出都是"是否存在优于基准者"的检验（p 值/拒绝），不做排名。
- **PBO（Bailey et al., JCF 20(4):39-69, 2017-04；2016-09 线上首发）**：把"IS 最优策略的 OOS 相对排名"本身当被检验对象；实证（随机游走、N=8,800 组合）：优化选择程序的 OOS 分布**既不一阶也不二阶随机占优随机选择**（PBO=55%）。
- **DSR（Bailey & López de Prado, JPM 40(5):94-107, 2014）**：以"赢家诅咒"为题眼，E[max SR] 公式（N 次独立试验的期望最大夏普）随 N 增长——选最优会选中膨胀的夏普。

**→ 修正 v1**：原稿"PBO 随 N 趋近 1"的表述**在所有可获取原文中无出处**（正式定义是条件概率；无补偿效应时 PBO 趋近 0.5）。正确表述："试验数 N 越大，假阳性概率越高；实证（N=8800）下选择程序不优于随机选择（PBO=55%）"。

### 批判 2："过拟合先放一下"只能放一半——比较框架必须内置轻防过拟合

**证据等级：支持（定量公式 + 实证数字）。**

- **AMS 2014（Bailey, Borwein, LdP, Zhu, Notices AMS 61(5)）**：只试 N=10 个配置就期望找到 IS 夏普 1.57（真值 0）；**5 年数据最多试 45 个独立配置**，2 年数据只能试 7 个；MinBTL < 2·lnN / E[max]²（年）——**样本长度和试验次数是同一枚硬币的两面**。
- 含义：搜索规模与可信任的样本互为函数。"相对"的价值建立在比较可信上——排名若被选择偏差污染，"相对"就是假的。

**→ 落地**：比较框架内置三件套（不额外加负担）：DSR-adjusted Sharpe 作排序轴、试验次数 N 诚实记账（AMS 精神："不报告 N 的回测无法评估代表性"）、集合输出而非单点。

### 批判 3：复利最大化不能直接当搜索轴——回撤硬筛 + 校正后夏普作精排

**证据等级：支持（链条证据，各环均有文献）。**

- **回撤是"极值的极值"**（Magdon-Ismail, NYU）：MDD 不可年化、不同时长 track record 不可比；**回撤分布对样本长度/频率/序列相关极度敏感**（Goldberg & Mahmoud 2017：序列相关与 CED 相关 0.75，vs 波动率 0.47）。
- **Calmar 作排序轴被直接批评**：不可年化、随样本对数增长、无单调性（收益更高者 Calmar 可能更差）、"统计显著性低于其他指标"（Investopedia/quant.SE 存档）。
- **学术主流 = 回撤作约束**：Chekhlov-Uryasev-Zabarankin (2005)："组合优化 = 在回撤约束（M(x) ≤ v₁ 等）下最大化期望累计收益"。
- **复利目标 = Kelly/对数效用**：对参数估计误差病态敏感（Wikipedia Kelly："仅在概率完全已知时才严格成立，投资中几乎从不"；标准处方：**分数 Kelly**，0.5×Kelly 保留 75% 增长率、方差减半）；且其选择膨胀**无解析校正工具**（夏普的膨胀有 DSR/PSR 解析式）。
- **夏普的估计误差有完整理论**（Lo 2002, FAJ）：T=60、真值 SR=1.5 时标准误已 0.188；SE/SR ≈ 1/√(2T)。

**→ 落地**：回撤约束（0-30% 可设）作**硬筛**（超限直接淘汰，不进排名）；精排轴 = DSR-adjusted Sharpe；复利最大化作最终选择前的**二次检查**，并报告"试了多少次"。

---

## 1.5 对老板思路的核实（调研新增）

| 老板认知 | 调研结论 | 证据 |
|----------|---------|------|
| 中间路（约束搜索+目标+择优） | **标准量化范式，方向正确** | 与工业界 7 步流水线吻合（Qlib/聚宽/华泰金工均有公开实现） |
| 持仓习惯≈等权 Top-N | **文献支持为最优默认** | DeMiguel et al. 2009 (RFS)：1/N 等权打败 14 个优化模型；25 资产需 3000 个月样本才可能反超 |
| 相对择优（垃圾里挑最优） | **正确方向；输出形态修正为集合** | MCS/Romano-Wolf/PBO/DSR（见批判 1） |
| 复利最大化+回撤可设 | **回撤作硬筛正确；复利作精排轴需校正** | CDaR 约束优化主流；Calmar 批评；Kelly 敏感性（批判 3） |
| 460 因子库 | **预期真实有效比例很低，筛选门槛要比美股更高** | HXZ 2020：452 异象 65% 无法复现、多重检验下 82% 失败；Green-Hand-Zhang：94 特征仅 12 个独立有效、2003 后崩塌 |
| 量价数据（公开数据天花板） | **A 股量价因子有真实信号但已衰减** | 东吴金工：换手率因子 IC -0.072/IR -2.09；华泰金工：2019 以来量价因子整体不佳；McLean-Pontiff：发表后收益低 58% |
| 化学反应（因子非线性交互） | **非线性交互是 ML 文献确认的真信号所在，但幅度极小** | GKX 2020：树/NN 收益来自线性抓不到的非线性交互，月度 R² 仅 0.33-0.40%；EL 2022：因子动量=所有因子自相关的聚合 |

---

## 2. 方向（三层内化，v2 微调）

```
层 1：口径对象化 —— 策略 = 可配置对象（系统重构）
层 2：集合级相对择优 —— 比较框架（DSR-adjusted + 集合输出 + N 记账）
层 3：多路交集漏斗 —— 筛选路径（顺序按文献修正）
```

### 层 1：口径对象化（不变）

策略 = 可配置对象（factor_set / combination / selection / rebalance / cost / target），生产（daily_pick）与验证共用同一配置。碎片实验全部归位成配置实例。

### 层 2：集合级相对择优（按调研增强）

`compare_pool.py` 输出：
- 每策略：**DSR-adjusted Sharpe**（校正试验次数）、PBO、回撤、OOS 分时段
- **集合输出**：两两 block bootstrap 比较 → "无法区分的最优集合"
- **N 记账**：报告每次搜索试了多少配置（AMS 精神）
- 排名稳定性：分时段 Spearman

### 层 3：多路交集漏斗（顺序按文献修正）

**关键修正（Feng-Giglio-Xiu 2020 原文警告）**："先单因子检验（B/C）再 Lasso（D）会放大假阳性"——推荐顺序：**先用稀疏方法控制存量因子，再对增量做多重检验校正**。

| 顺序 | 路 | 方法 | 证据等级 | 调整 |
|------|----|------|---------|------|
| 1 | D 独立性 | **double-selection Lasso**（Belloni-Chernozhukov-Hansen 2014）+ 正交化（Barra VIF 诊断，不过度正交化） | 半标准，有明确原文警告 | v1 的"Lasso 非零"升级为 double-selection；顺序提前 |
| 2 | B 显著性 | NW-t + FDR 有效 N | **学术前沿标准** | 不变 |
| 3 | A 强度 | IC 均值 + IR | 行业惯例（阈值无权威出处） | 阈值按 Grinold 定律（IR≈IC·√BR）自行校准，标注惯例来源 |
| 4 | C 形态 | decile 单调（**升级为 Patton-Timmermann 2010 正式单调性检验**）+ 多空收益 t | 标准但需升级 | 补正式检验 |
| 5 | E 先验 | 经济逻辑人工标注 | **学术前沿标准**（Harvey 2017："门槛取决于经济合理性"；Arnott-Harvey-Markowitz 回测协议第一条=事前经济假设） | 不变 |

注意两个坑（文献直接警示）：
1. 交集漏斗无文献 canon 化——最接近的学术对应是 Harvey-Liu 框架（多重检验+经济先验+增量贡献）
2. A/C 惯例阈值与 B 的严格门槛（t>3.0）有口径冲突——统一用校准后的阈值

---

## 3. 可落地规划（4 步，按顺序）

### 第一步：口径对象化（半天-1 天）
- 策略配置 schema（JSON）+ `strategy_factory.py`（配置 → 回测/生产可执行）
- daily_pick_v5 改为读配置（等权投票 Top5 是配置的一个实例）
- **产出**：生产/验证共用口径；碎片实验归位

### 第二步：比较框架重建（1-2 天）
- `compare_pool.py`：DSR-adjusted Sharpe + PBO + 集合输出 + N 记账 + Spearman 稳定性
- 用已有策略形态（TSMOM long-only、lowvol、因子动量、组合叠加）跑通
- **产出**：v5 第一次真正的横向 OOS 比较 + 诚实"无法区分集合"

### 第三步：多路交集 + week 全链路（2-3 天）
- 路 D 的 double-selection Lasso、路 A 的 IR 校准、路 C 的 Patton-Timmermann 检验、路 E 标注表
- factor_map 补 week 切片（诊断层已证 week P_TT 0.518 > month 0.402）
- 顺序执行：D → B → A → C → E 交集收敛 → 候选池 → 层 2 比较
- **产出**：候选策略集合 + 诚实报告（含"无法区分集合"边界）

### 第四步：生产接轨（候选集合确定后）
- 集合内配置（等权/trim）→ 扣成本 OOS 复核 → 口径对象更新 daily_pick
- 决策门 B 升级为集合级

---

## 4. 与老板认知的对照（v2）

| 老板要求 | 落点 | 调研状态 |
|----------|------|---------|
| 相对择优器 | 层 2 集合级比较（修正为集合而非单点） | MCS/RW 逐字支持 |
| 回撤可设 0-30% | 硬筛（学术主流，CDaR 式） | 支持 |
| 复利最大化、节点可设 | 精排轴 DSR-adjusted；复利作二次检查 | 支持（Kelly 敏感性） |
| 不只 IC 一条路 | 层 3 五路交集（顺序修正） | FGX 原文支持修正 |
| 方法内化进架构 | 层 1 口径对象化 | 与工业界流水线一致 |
| 过拟合先放一下 | 只放重验证；框架内置轻防过拟合 | AMS 定量支持 |
| 一步步往前走，错了重来 | 四步每步独立产出 | - |

## 5. 诚实限定（v2 按调研收紧）

- 460 因子预期真实有效比例很低（HXZ：65-82% 失败；GHZ：94 个仅 12 个独立）——候选集合为空是**大概率事件**，系统价值在于诚实排出"谁能亏最少"
- A 股量价因子已衰减（华泰：2019 以来不佳）——即使集合非空，盈利预期也要压低
- 等权 Top-N 是我们天然的最优默认（DeMiguel）——无需为"不够优化"焦虑
- 本方案不承诺赚钱；承诺：候选集合是统计上无法被击败的最优集合，同口径可复现，N 记账透明

## 6. 关键分歧点（供对照 cc 方案时看）

1. **排名 vs 集合**：cc 方案若排 Top-K 名次，此处是最大分歧（MCS 原文不支持单点排名）
2. **轻验证内置于搜索**：是否接受 DSR/PBO/N 记账作为搜索的一部分
3. **week 优先铺开**：是否同意 week 全链路优先
4. **五路顺序**：D（稀疏控制存量）在 B/C 之前（FGX 原文）

## 7. 调研证据附录（全部 2026-08-07 联网核实）

### 策略比较方法论
- Hansen, Lunde & Nason (2011) MCS, Econometrica 79(2):453-497 — 摘要 https://jstor.econometricsociety.org/publications/econometrica/2011/03/01/model-confidence-set ；全文 WP https://repec.econ.au.dk/repec/creates/rp/10/rp10_76.pdf
- Romano & Wolf (2005) StepM, Econometrica 73(4):1237-1282 — https://www.stat.wharton.upenn.edu/~steele/Courses/956/Resource/MultipleComparision/RomanoWolf05.pdf
- Bailey, Borwein, LdP, Zhu (2017) PBO, JCF 20(4):39-69（2016-09 线上首发）— http://www.risk.net/journal-of-computational-finance/technical-paper/2471206/the-probability-of-backtest-overfitting ；修订稿 https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- Bailey & LdP (2014) DSR, JPM 40(5):94-107 — http://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- White (2000) Reality Check, Econometrica 68(5) — https://www.ssc.wisc.edu/~bhansen/718/White2000.pdf
- Hansen (2005) SPA, JBES 23(4):365-380 — SIEPR WP https://web.archive.org/web/2id_/https://www-siepr.stanford.edu/workp/swp05003.pdf

### 目标函数
- Bailey et al. (2014) Pseudo-Mathematics, Notices AMS 61(5):458-471 — https://www.ams.org/notices/201405/rnoti-p458.pdf （N=10→SR1.57；5yr→45 trials；MinBTL<2lnN/E[max]²）
- Lo (2002) Statistics of Sharpe Ratios, FAJ 58(4) — http://edge-fund.com/Lo02.pdf
- Magdon-Ismail, MDD 演讲 — http://www.cs.rpi.edu/~magdon/talks/mdd_NYU04.pdf
- Goldberg & Mahmoud (2017) Drawdown, Math. Fin. Econ — https://ar5iv.labs.arxiv.org/html/1404.7493
- Chekhlov, Uryasev, Zabarankin (2005) CDaR, IJTAF 8(1) — https://ideas.repec.org/a/wsi/ijtafx/v08y2005i01ns0219024905002767.html
- Kelly criterion — https://en.wikipedia.org/wiki/Kelly_criterion

### 因子筛选
- Harvey, Liu & Zhu (2016) HLZ, RFS 29(1):5-68 — 摘要 http://causalclaims.trfetzer.com/paper/w20592.html
- Harvey (2017) Presidential Address, JF 72(4):1399-1440 — https://people.duke.edu/~charvey/Research/Published_Papers/P131_The_scientific_outlook.pdf （"t>3 也不够，取决于经济合理性"）
- Harvey & Liu (2021) Lucky Factors, JFE 141(2):413-435 — https://people.duke.edu/~charvey/Research/Published_Papers/P146_Lucky_factors.pdf
- Feng, Giglio & Xiu (2020) Taming the Factor Zoo, JF 75(3):1327-1370 — https://www.nber.org/system/files/working_papers/w25481/w25481.pdf （"简单 Lasso 选入≠真因子"；先稀疏后检验）
- Gu, Kelly & Xiu (2020) GKX, RFS 33(5):2223-2273 — https://dachxiu.chicagobooth.edu/download/ML.pdf （ENet 0.11% vs NN 0.40% R²；"Lasso 选子集劣于简单平均"）
- Patton & Timmermann (2010) Monotonicity, JFE 98(3):605-625 — https://scholars.duke.edu/publication/792435
- Arnott, Harvey & Markowitz (2019) Backtesting Protocol, JFDS — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3275654
- Barra/Menchero 因子正交化 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1601414

### 主流方向与 A 股
- Cochrane (2011) factor zoo, JF 66(4) — DOI 10.1111/j.1540-6261.2011.01671.x
- McLean & Pontiff (2016), JF 71(4):1625-1666（样本外 -26%、发表后 -58%）
- Hou, Xue & Zhang (2020) Replicating Anomalies, RFS 33(5):2019-2133（452 异象 65% 失败、多重检验 82% 失败）— NBER w23394
- Green, Hand & Zhang (2017), RFS 30(12):4389-4436（94 特征仅 12 独立）
- Ehsani & Linnainmaa (2022) Factor Momentum, JF 77(3)（动量=自相关聚合）— NBER w25551
- Moskowitz, Ooi & Pedersen (2012) TSMOM, JFE 104(2):228-250
- DeMiguel, Garlappi & Uppal (2009) 1/N, RFS 22(5):1915-1953（3000 个月才可能反超）
- Liu, Stambaugh & Yuan (2019) Size and Value in China, JFE 134(1)（最小 30% 壳价值）
- WorldQuant 101 Alphas — arXiv:1601.00991
- 工业界：microsoft/qlib（GitHub）、聚宽文档（joinquant.com）、华泰金工/东吴金工研报（慧博转载）、CSRC 程序化交易管理规定（2024-10-08 实施）、财政部税务总局印花税公告 2023 年第 39 号

### 未能核实（如实标注）
- PBO 的 JCF 发表版全文（付费）——基于作者主页修订稿
- MCS 的 Econometrica 发表版正文——基于 CREATES WP（摘要逐字一致）
- MinTRL 公式原文（Bailey & LdP 2012，SSRN 付费墙）
- CFA 教材 IC 阈值、HLZ 原文 BHY 程序表数字、部分券商研报原 PDF
- "PBO 随 N 趋近 1"——所有抓取原文中均不存在（已从方案中删除）
