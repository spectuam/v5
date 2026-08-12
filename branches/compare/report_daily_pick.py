# -*- coding: utf-8 -*-
"""v5 首份四件套报告生成器：daily_pick 评估报告（plotly 交互 HTML）

依据/来源：
- 数据: branches/compare/candidates_returns.json (13候选周收益, 2016-W03~2026-W26)
       + compare_pool_result.json (CPCV/MCS/DSR 指标, 8/8 01:05 运行)
- 方法: compare_pool.py (CPCV purge+embargo+多split, MCS block bootstrap, DSR N_eff)
- walk-forward / forward tracker 数字: docs/v5阶段2-3实现与HMM调研-cc.md §九 (8/8, 无独立JSON)
"""
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

BASE = "/home/soso/v5/branches/compare"

# ---------- 加载 ----------
cr = json.load(open(f"{BASE}/candidates_returns.json"))
cp = json.load(open(f"{BASE}/compare_pool_result.json"))
strategies = cp["strategies"]

# ---------- 净值序列 ----------
from datetime import date as dtdate

def to_equity(rows):
    def parse(week_label):
        y, w = int(week_label.split("-W")[0]), int(week_label.split("-W")[1])
        return dtdate.fromisocalendar(y, w, 1)  # ISO 周，周一
    dates = [parse(r[0]) for r in rows]
    rets = pd.Series([r[1] for r in rows], index=dates)
    return (1 + rets).cumprod()

eq = pd.DataFrame({k: to_equity(v) for k, v in cr.items()}).ffill()

NAMES = {
    "daily_pick_eqcomposite_top5": "daily_pick 等权Top5（生产策略）",
    "market_eq": "全市场等权（基准）",
    "tsmom_ls_K12": "TSMOM 多空 K12",
    "tsmom_long_K12": "TSMOM 做多 K12",
    "funnel_top5_eq_ls": "漏斗Top5 多空",
    "funnel_top5_eq_long": "漏斗Top5 做多",
    "funnel_top5_tsmom_long": "漏斗Top5+TSMOM 做多",
    "tsmom_long_K1": "TSMOM 做多 K1",
    "tsmom_long_K4": "TSMOM 做多 K4",
    "tsmom_long_K24": "TSMOM 做多 K24",
    "eq38_ls": "38因子等权 多空",
    "lowvol_weekly": "低波周频",
    "phase2_ic_weekly": "phase2 IC周频",
}

COLORS = {k: "#888" for k in cr}  # 默认灰
COLORS["daily_pick_eqcomposite_top5"] = "#d62728"  # 红 = 被证伪对象
COLORS["market_eq"] = "#000000"  # 黑 = 基准

# ---------- 图1 净值曲线 ----------
fig1 = go.Figure()
for k in cr:
    vis = k in ("daily_pick_eqcomposite_top5", "market_eq", "tsmom_ls_K12", "funnel_top5_eq_ls")
    fig1.add_trace(go.Scatter(
        x=eq.index, y=eq[k], name=NAMES[k], mode="lines",
        line=dict(color=COLORS[k], width=3 if k == "market_eq" else (2.5 if k == "daily_pick_eqcomposite_top5" else 1.2)),
        visible=True if vis else "legendonly",
    ))
fig1.update_layout(title="图1 净值曲线对比（2016-W03 ~ 2026-W26，周频）",
                   xaxis_title="日期", yaxis_title="净值（起点=1）",
                   legend=dict(font=dict(size=10)), height=520,
                   hovermode="x unified")

# ---------- 图2 CPCV OOS 分布（箱线） ----------
fig2 = go.Figure()
for k in strategies:
    dist = strategies[k]["cpcv_oos_dist"]
    fig2.add_trace(go.Box(
        y=dist, name=NAMES.get(k, k), boxpoints="all", pointpos=0,
        marker=dict(color=COLORS.get(k, "#888"), size=3, opacity=0.5),
        line=dict(color=COLORS.get(k, "#888")),
        fillcolor="rgba(0,0,0,0)",
    ))
fig2.add_hline(y=0, line_dash="dash", line_color="#999")
fig2.update_layout(title="图2 可信度：CPCV 样本外夏普分布（50 条 OOS 路径）",
                   xaxis_title="候选策略", yaxis_title="CPCV OOS 夏普",
                   height=500, showlegend=False)

# ---------- 图3 DSR 柱状 ----------
names3 = [NAMES.get(k, k) for k in strategies]
dsr_vals = [strategies[k]["dsr"] for k in strategies]
colors3 = ["#d62728" if k == "daily_pick_eqcomposite_top5" else ("#000000" if k == "market_eq" else "#888") for k in strategies]
fig3 = go.Figure(go.Bar(x=names3, y=dsr_vals, marker_color=colors3))
fig3.add_hline(y=0.95, line_dash="dash", line_color="#d62728")
fig3.add_annotation(x=len(names3) - 0.5, y=0.95, text="DSR 0.95 显著门槛", showarrow=False, font=dict(color="#d62728", size=11))
fig3.update_layout(title="图3 可信度：Deflated Sharpe（按 N_eff=1.94 校正搜索膨胀）",
                   xaxis_title="候选策略", yaxis_title="DSR", height=460,
                   xaxis_tickangle=35)

# ---------- alpha/beta 归因（周频 CAPM 式：ret_s = alpha + beta*ret_m） ----------
def parse_label(w):
    y, wk = int(w.split("-W")[0]), int(w.split("-W")[1])
    return dtdate.fromisocalendar(y, wk, 1)

mkt_ret = pd.DataFrame({k: pd.Series({parse_label(r[0]): r[1] for r in v}).sort_index() for k, v in cr.items()})

ab = {}
for k in cr:
    df = pd.concat([mkt_ret[k], mkt_ret["market_eq"]], axis=1, join="inner").dropna()
    df.columns = ["s", "m"]
    beta = df["s"].cov(df["m"]) / df["m"].var()
    alpha_w = df["s"].mean() - beta * df["m"].mean()
    r2 = (beta * df["m"].std() / df["s"].std()) ** 2
    ab[k] = {"beta": beta, "alpha_ann": alpha_w * 52, "r2": r2}

fig5 = go.Figure()
for k in cr:
    fig5.add_trace(go.Scatter(
        x=[ab[k]["beta"]], y=[ab[k]["alpha_ann"] * 100], mode="markers+text",
        name=NAMES.get(k, k), text=[NAMES.get(k, k).split("（")[0]],
        textposition="top center", textfont=dict(size=10),
        marker=dict(size=12, color=COLORS.get(k, "#888")),
        hovertemplate=f"<b>{NAMES.get(k, k)}</b><br>beta={ab[k]['beta']:.2f}<br>年化alpha={ab[k]['alpha_ann']*100:.1f}%<br>R²={ab[k]['r2']:.2f}<extra></extra>",
    ))
fig5.add_hline(y=0, line_color="#999", line_dash="dash")
fig5.add_vline(x=0, line_color="#999", line_dash="dash")
fig5.update_layout(title="图5 归因：alpha（选股能力）vs beta（市场敞口）四象限",
                   xaxis_title="beta（市场敞口）", yaxis_title="年化 alpha（%）",
                   height=520, showlegend=False,
                   xaxis=dict(range=[-0.3, 1.3]), yaxis=dict(range=[-15, 20]))
fig5.add_annotation(x=1.2, y=18, text="理想区：低敞口+正alpha", showarrow=False, font=dict(color="#2ca02c", size=11))
fig5.add_annotation(x=1.2, y=-13, text="最差区：满敞口+负alpha", showarrow=False, font=dict(color="#d62728", size=11))

# ---------- 图4 SR 三阶段对比 ----------
stages = [("sharpe_train", "训练期(2016-2022)"), ("sharpe_full", "全样本(2016-2026)"), ("sharpe_oos", "样本外(2022+ )")]
fig4 = go.Figure()
for key, label in stages:
    vals = [strategies[k][key] for k in strategies]
    fig4.add_trace(go.Bar(name=label, x=names3, y=vals))
fig4.add_hline(y=0, line_color="#999")
fig4.update_layout(title="图4 结果：三阶段年化夏普（周频口径）", barmode="group",
                   xaxis_tickangle=35, height=460, legend=dict(orientation="h", y=1.12))

# ---------- 汇总表 ----------
rows = []
for k in strategies:
    s = strategies[k]
    rows.append({
        "策略": NAMES.get(k, k),
        "全样本SR": f'{s["sharpe_full"]:.2f}',
        "训练SR": f'{s["sharpe_train"]:.2f}',
        "OOS SR": f'{s["sharpe_oos"]:.2f}',
        "DSR": f'{s["dsr"]:.3f}',
        "Calmar": f'{s["calmar"]:.2f}',
        "最大回撤": f'{s["max_dd"]*100:.1f}%',
        "beta": f'{ab[k]["beta"]:.2f}',
        "年化alpha": f'{ab[k]["alpha_ann"]*100:.1f}%',
        "CPCV中位": f'{s["cpcv_median"]:.2f}',
        "CPCV p10": f'{s["cpcv_p10"]:.2f}',
    })
table_html = pd.DataFrame(rows).to_html(index=False, border=0, classes="tbl")

# ---------- 页面组装 ----------
fig1_html = pio.to_html(fig1, include_plotlyjs=True, full_html=False)
fig2_html = pio.to_html(fig2, include_plotlyjs=False, full_html=False)
fig3_html = pio.to_html(fig3, include_plotlyjs=False, full_html=False)
fig4_html = pio.to_html(fig4, include_plotlyjs=False, full_html=False)
fig5_html = pio.to_html(fig5, include_plotlyjs=False, full_html=False)

CSS = """
body{font-family:'Microsoft YaHei',sans-serif;max-width:1100px;margin:24px auto;padding:0 20px;color:#222}
h1{font-size:24px}h2{font-size:18px;border-left:4px solid #d62728;padding-left:8px;margin-top:36px}
.meta{color:#666;font-size:13px;line-height:1.8}
.tbl{border-collapse:collapse;width:100%;font-size:13px}
.tbl th,.tbl td{border:1px solid #ddd;padding:6px 8px;text-align:right}
.tbl th{background:#f5f5f5}
.box{border:1px solid #ddd;border-radius:6px;padding:12px 16px;background:#fafafa;font-size:14px;line-height:1.8}
.warn{border-left:4px solid #d62728;background:#fdf2f2}
.ok{border-left:4px solid #2ca02c;background:#f2faf2}
"""

html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>v5 评估报告：daily_pick（四件套样板）</title>
<style>{CSS}</style></head><body>

<h1>v5 评估报告：daily_pick 等权Top5（生产策略）</h1>
<p class="meta">生成：2026-08-08 · 数据：branches/compare/candidates_returns.json + compare_pool_result.json（8/8 01:05）<br>
方法：compare_pool.py — CPCV(purge+embargo+多split) + MCS(block bootstrap) + DSR(N_eff=1.94)<br>
这是 v5 按"程序性裁判系统"定位产出的第一份四件套报告：结果 / 口径 / 可信度 / 证伪判定。</p>

<h2>① 结果</h2>
{fig1_html}
{fig4_html}
{table_html}
<p class="meta">口径：周频，2016-W03~2026-W26（526 周）；CPCV 划分 train_end=2022-W52；年化 √52。<br>
图1 灰色曲线默认隐藏，点击图例可切换显示；黑=全市场等权基准，红=daily_pick。</p>

<h2>② 口径（计算假设显式化）</h2>
<div class="box">
<b>daily_pick（生产策略）</b>：38 因子等权复合 → 因子打分排序 → Top5 + 涨停过滤（<i>涨停过滤为生产端规则，回测口径按 compare_pool 统一口径复现</i>）<br>
<b>数据源</b>：kline_15m 单一事实源 → 日线；后复权。<br>
<b>因子集</b>：38 因子，data_range=2000-2015 选定（无 look-ahead，8/8 口径对象化验证）<br>
<b>成本</b>：compare_pool 统一口径（含手续费/滑点假设，详见 compare_pool.py FREQ 与成本参数）<br>
<b>基准</b>：全市场等权（market_eq，同周期同口径）<br>
<b>频率</b>：周频再平衡，年化 √52<br>
<b>注意</b>：夏普统一取"日资金曲线"口径聚合为周——避开按笔交易虚高（EP004 提醒的坑）。
</div>

<h2>③ 可信度</h2>
{fig2_html}
{fig3_html}
{fig5_html}
<div class="box">
<b>walk-forward OOS</b>（8/8，docs §九）：每年 expanding 重选 top-38 → daily_pick 样本外 SR <b>0.444</b> ≈ 静态回测 0.40，同时期 market_eq 0.58 → <b>稳健跑输，非偶然</b>。<br>
<b>forward tracker</b>（8/8 起 10 日实盘跟踪）：daily SR 5.97 vs market SR 9.51（10 日小样本，无统计意义，仅起点）——单日超额均值 +2.3%/周但波动集中。<br>
<b>alpha/beta 归因</b>（周频 CAPM 式回归，ret_s = alpha + beta·ret_m）：daily_pick <b>beta 1.02、年化 alpha -4.8%</b>——满市场敞口且选股负贡献，两头不占（对比：TSMOM 多空 beta -0.01 真中性、alpha +7.6%；漏斗Top5多空 beta -0.04、alpha +14.3%）。
</div>

<h2>④ 证伪判定（程序性结论）</h2>
<div class="box warn">
<b>判定：daily_pick 已证伪（"死了"）。</b><br>
依据（8/8 四重验证汇聚，非单一检验）：<br>
1. 全样本 SR 0.40 &lt; 市场等权 0.64，训练期 SR 0.20 极差（倒挂：OOS 0.72 &gt; 训练 0.20 → 疑似对近年数据过拟合）<br>
2. 最大回撤 -50.5% vs 市场 -33.2%，风险调整全面垫底（Calmar 0.27 池内最低）<br>
3. CPCV 中位 0.40 &lt; 市场 0.64，且 p10=0.15（最差路径接近 0）<br>
4. DSR 0.891 未过 0.95 门槛<br>
5. walk-forward 确认 0.444 稳健跑输<br>
6. alpha/beta 归因：beta 1.02（满敞口）+ 年化 alpha -4.8%（选股负贡献）——跑输 = 选股能力为负 + 无任何防御，非运气<br>
<b>诚实备注</b>：单对 MCS 检验（market_eq vs daily_pick）pairwise p=0.087 未达 0.05——单检验不显著，证伪成立靠多方法汇聚 + 生产口径长期跟踪，不靠任何单一检验。<br>
<b>生产层含义</b>：daily_pick 每天推 Top5 属价值性输出，与新定位冲突——应改为输出候选报告（本报告即样板），用不用由老板决定。
</div>

<div class="box ok">
<b>报告责任声明</b>：本报告只输出"真实的证据"，不输出"推荐"。结论是否被采纳、买什么，由阅读者决定。
</div>

</body></html>"""

out = f"{BASE}/reports/daily_pick_report.html"
import os
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("已生成:", out, f"({os.path.getsize(out)//1024} KB)")
