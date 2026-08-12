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
    vis = k in ("daily_pick_eqcomposite_top5", "market_eq", "tsmom_ls_K12", "funnel_top5_eq_ls", "funnel_top5_tsmom_long")
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

<h1>v5 评估报告：候选策略横向对比（13 候选）</h1>
<p class="meta">生成：2026-08-08 · 数据：branches/compare/candidates_returns.json + compare_pool_result.json（8/8 01:05）<br>
方法：compare_pool.py — CPCV(purge+embargo+多split) + MCS(block bootstrap) + DSR(N_eff=1.94)<br>
对象：13 个候选策略（TSMOM 系 / 漏斗系 / phase2 系 / 低波 / daily_pick 生产策略 / 市场等权基准）——同一口径横向比较。</p>

<h2>① 结果：同坐标系对比</h2>
{fig1_html}
{fig4_html}
{table_html}
<p class="meta">口径：周频，2016-W03~2026-W26（526 周）；CPCV 划分 train_end=2022-W52；年化 √52。<br>
图1 灰色曲线默认隐藏，点击图例可切换显示；黑=全市场等权基准，红=daily_pick（被证伪的生产策略），蓝=两匹 MCS 幸存者。</p>

<h2>② 口径（计算假设显式化，13 候选统一）</h2>
<div class="box">
<b>数据源</b>：kline_15m 单一事实源 → 日线；后复权。<br>
<b>候选构成</b>：TSMOM 做多 K1/K4/K12/K24、TSMOM 多空 K12、38因子等权多空、phase2 IC 周频、低波周频、漏斗 Top5 多空/做多/TSMOM做多、daily_pick 等权Top5（生产策略）<br>
<b>因子集</b>：38 因子（data_range=2000-2015 选定，无 look-ahead）<br>
<b>成本</b>：统一口径（含手续费/滑点，compare_pool.py 参数）<br>
<b>基准</b>：全市场等权 market_eq（同周期同口径）<br>
<b>频率</b>：周频再平衡，年化 √52<br>
<b>CPCV 划分</b>：train_end=2022-W52，多 split purge+embargo<br>
<b>注意</b>：夏普统一"日资金曲线"口径聚合为周——避开按笔交易虚高（EP004 提醒的坑）。
</div>

<h2>③ 可信度：多重检验 + 归因</h2>
{fig2_html}
{fig3_html}
{fig5_html}
<div class="box">
<b>候选池有效性</b>：13 候选名义数，N_eff=<b>1.94</b>（相关矩阵特征值）——有效独立信息不到 2 个，候选高度同源（同一批量价因子衍生）→ <b>池内"择优"无统计意义</b>，MCS 只能做"淘汰"级区分。<br>
<b>MCS 置信集</b>（block bootstrap）：幸存者 = <b>tsmom_ls_K12、funnel_top5_eq_ls</b>（并列，无法再区分）——其余候选（含 daily_pick、phase2、低波）被剔除。<br>
<b>PBO</b>（回测过拟合概率）：0.05（低）；<b>排名稳定性</b>（spearman 分段）：seg3_vs_seg4=0.676，近年排名稳定性上升。<br>
<b>alpha/beta 归因</b>（周频 CAPM 式）：多空系（TSMOM/漏斗）beta≈0 真中性且正 alpha（+7.6%/+14.3%）；做多系 beta≈1 满敞口，alpha 微弱正；daily_pick beta 1.02 满敞口且 alpha -4.8%（唯一负 alpha 系）。<br>
<b>walk-forward OOS</b>（8/8）：daily_pick 0.444 稳健跑输 market 0.58（docs §九）。
</div>

<h2>④ 程序性结论</h2>
<div class="box warn">
<b>结论 1：池内无"最优"可挑——候选同源（N_eff=1.94），MCS 只能淘汰，不能择优。</b>幸存两候选（tsmom_ls_K12、funnel_top5_eq_ls）统计上无法再区分；"从池里选一个最好的"是证真，本报告不做。<br>
<b>结论 2：daily_pick 已证伪（"死了"）</b>——SR 0.40 &lt; 市场 0.64、回撤两倍于市场、训练期 0.20 倒挂、DSR 0.891 未过门槛、walk-forward 0.444 确认、alpha -4.8% 选股负贡献。六条证据汇聚，非单一检验（诚实备注：单对 pairwise p=0.087 未达 0.05，证伪靠多方法汇聚）。<br>
<b>结论 3：多空系是本池最强形态</b>——真中性（beta≈0）+ 正 alpha（TSMOM 多空 +7.6%、漏斗多空 +14.3%），是唯一"没被证伪且有正面贡献"的候选方向。<br>
<b>生产层含义</b>：daily_pick 每天推 Top5 属价值性输出，与新定位冲突——应改为输出候选报告（本报告即样板），用不用由老板决定。
</div>

<div class="box ok">
<b>报告责任声明</b>：本报告只输出"真实的证据"，不输出"推荐"。"多空系最强"是程序性排名结论（相对池内），不是推荐实盘做多空。结论是否被采纳、买什么，由阅读者决定。
</div>

</body></html>"""

out = f"{BASE}/reports/compare_pool_report.html"
import os
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("已生成:", out, f"({os.path.getsize(out)//1024} KB)")
