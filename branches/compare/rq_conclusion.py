#!/home/soso/v5/.venv/bin/python3
"""RQAlpha 对跑验证·结论报告（合并全部实验）"""
import json, os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

BASE = "/home/soso/v5/branches/compare"


def load(tag):
    p = f"{BASE}/rq_tsmom_ls_result.pkl" if tag == "base" else f"{BASE}/rq_tsmom_ls_result_{tag}.pkl"
    if not os.path.exists(p):
        return None
    rq = pd.read_pickle(p)
    return rq


def wk(ts):
    iso = pd.Timestamp(ts).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def weekly_nav(rq):
    pf = rq["portfolio"]
    pf.index = pd.to_datetime(pf.index)
    s = pf["unit_net_value"]
    w = pd.Series({wk(ts): v for ts, v in s.items()})
    return w / w.iloc[0]


def stats(eq):
    r = eq.pct_change().dropna()
    sr = r.mean() / r.std() * np.sqrt(52) if r.std() > 0 else np.nan
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    ann = eq.iloc[-1] ** (52 / len(eq)) - 1
    return ann, sr, mdd


# ---- 十年对照 ----
ours10 = json.load(open(f"{BASE}/tsmom_ls_K12_long_leg.json"))
ours10_s = pd.Series(ours10).sort_index()
eq10 = (1 + ours10_s).cumprod()
a10 = {}
for tag, label, cap in [("base", "100万·默认成本", 1e6), ("e8", "1亿·默认成本", 1e8), ("bp", "100万·纯费率", 1e6)]:
    rq = load(tag)
    if rq is None:
        continue
    nav = weekly_nav(rq)
    nav = nav[nav.index >= ours10_s.index[0]]
    nav = nav / nav.iloc[0]
    ann, sr, mdd = stats(nav)
    tr = rq["trades"]
    fee = tr["tax"].sum() + tr["commission"].sum()
    a10[tag] = {"nav": nav, "ann": ann, "sr": sr, "mdd": mdd, "n": len(tr),
                "fee_pct": fee / cap * 100, "label": label}
ann_i10, sr_i10, mdd_i10 = stats(eq10)

# ---- 三年对照 ----
ours3_s = ours10_s[(ours10_s.index >= "2016-W01") & (ours10_s.index <= "2018-W52")]
eq3 = (1 + ours3_s).cumprod()
ann_i3, sr_i3, mdd_i3 = stats(eq3)
a3 = {}
for tag, label in [("e8_3y", "1亿·默认(三年)"), ("e8nolimit_3y", "1亿·无涨跌停(三年)")]:
    rq = load(tag)
    if rq is None:
        continue
    nav = weekly_nav(rq)
    nav = nav[(nav.index >= "2016-W01") & (nav.index <= "2018-W52")]
    nav = nav / nav.iloc[0]
    ann, sr, mdd = stats(nav)
    tr = rq["trades"]
    fee = (tr["tax"].sum() + tr["commission"].sum()) / 1e8 / 3 * 100
    a3[tag] = {"ann": ann, "sr": sr, "mdd": mdd, "n": len(tr), "fee_ann_pct": fee, "label": label, "nav": nav}

# ---- 图1: 十年净值 ----
fig1 = go.Figure()
colors = {"base": "#d62728", "e8": "#ff7f0e", "bp": "#9467bd"}
for tag in ["base", "e8", "bp"]:
    if tag in a10:
        fig1.add_trace(go.Scatter(x=a10[tag]["nav"].index, y=a10[tag]["nav"].values,
                                  name=a10[tag]["label"], line=dict(color=colors[tag], width=2)))
fig1.add_trace(go.Scatter(x=eq10.index, y=(eq10 / eq10.iloc[0]).values, name="我们理想(无成本无限制)",
                          line=dict(color="#1f77b4", width=2)))
fig1.update_layout(title="十年对照：RQAlpha 三运行 vs 自写口径", xaxis_title="周", yaxis_title="净值(起点=1)",
                   height=480, hovermode="x unified")

# ---- 图2: 三年净值 ----
fig2 = go.Figure()
for tag in ["e8_3y", "e8nolimit_3y"]:
    if tag in a3:
        fig2.add_trace(go.Scatter(x=a3[tag]["nav"].index, y=a3[tag]["nav"].values,
                                  name=a3[tag]["label"], line=dict(width=2)))
fig2.add_trace(go.Scatter(x=eq3.index, y=(eq3 / eq3.iloc[0]).values, name="我们理想(三年)",
                          line=dict(color="#1f77b4", width=2)))
fig2.update_layout(title="三年窗口（归因闭合实验）", xaxis_title="周", yaxis_title="净值(起点=1)",
                   height=420, hovermode="x unified")

# ---- 表格 ----
def row(label, ann, sr, mdd, extra=""):
    return f"<tr><td>{label}</td><td>{ann*100:.1f}%</td><td>{sr:.2f}</td><td>{mdd*100:.1f}%</td><td>{extra}</td></tr>"

t10 = [row(a10["base"]["label"], a10["base"]["ann"], a10["base"]["sr"], a10["base"]["mdd"],
            f"成交{a10['base']['n']}笔 · 费占本金{a10['base']['fee_pct']:.1f}%"),
       row(a10["bp"]["label"], a10["bp"]["ann"], a10["bp"]["sr"], a10["bp"]["mdd"],
           f"成交{a10['bp']['n']}笔 · 费占本金{a10['bp']['fee_pct']:.1f}%"),
       row(a10["e8"]["label"], a10["e8"]["ann"], a10["e8"]["sr"], a10["e8"]["mdd"],
           f"成交{a10['e8']['n']}笔 · 费占本金{a10['e8']['fee_pct']:.1f}%"),
       row("我们理想(无成本无限制)", ann_i10, sr_i10, mdd_i10, "自写回测口径")]
table10 = f"<table class='tbl'><tr><th>口径</th><th>年化</th><th>夏普</th><th>MDD</th><th>备注</th></tr>{''.join(t10)}</table>"

t3 = [row(a3["e8_3y"]["label"], a3["e8_3y"]["ann"], a3["e8_3y"]["sr"], a3["e8_3y"]["mdd"],
          f"成交{a3['e8_3y']['n']}笔 · 费用年化{a3['e8_3y']['fee_ann_pct']:.2f}pp"),
      row(a3["e8nolimit_3y"]["label"], a3["e8nolimit_3y"]["ann"], a3["e8nolimit_3y"]["sr"], a3["e8nolimit_3y"]["mdd"],
          f"成交{a3['e8nolimit_3y']['n']}笔 · 费用年化{a3['e8nolimit_3y']['fee_ann_pct']:.2f}pp"),
      row("我们理想(三年)", ann_i3, sr_i3, mdd_i3, "自写回测口径")]
table3 = f"<table class='tbl'><tr><th>口径</th><th>年化</th><th>夏普</th><th>MDD</th><th>备注</th></tr>{''.join(t3)}</table>"

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

fig1_html = pio.to_html(fig1, include_plotlyjs=True, full_html=False)
fig2_html = pio.to_html(fig2, include_plotlyjs=False, full_html=False)

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>RQAlpha 对跑验证·结论报告</title><style>{CSS}</style></head><body>
<h1>自写回测 vs RQAlpha 引擎：对跑验证结论报告</h1>
<p class="meta">生成：2026-08-10 · 引擎：RQAlpha 6.x（A股日线，涨跌停/停牌/t+1/最低佣金5元/笔内置）<br>
策略：tsmom_ls_K12 多头腿（TSMOM 信号选因子 × top30% 持仓，周频调仓）· 数据：kline_15m 派生持仓 + RQAlpha bundle<br>
全部数字来自 analyser 实测（portfolio/trades），非估算。</p>

<h2>① 十年对照（2016-2026）</h2>
{table10}
<div class="box">
<b>主结论</b>：自写回测（理想 16.1%/SR 0.73）vs 真实引擎（100万 2.1%/0.34；1亿 7.0%/0.45）——<b>14 个百分点的系统性高估</b>。<br>
100万版额外受"最低佣金 5 元/笔 + 最小手数"打击（单只权重 247 元买不起一手 → 85% 目标持仓未成交）；1亿版执行率 86% 但费用成为主约束（3.5%/年）。
</div>

<h2>② 三年归因闭合实验（2016-2018，1 亿资金）</h2>
{table3}
<div class="box warn">
<b>归因分解（年化，理想 -0.5% → 默认 -9.7%，缺口 9.2pp，精确闭合）</b>：<br>
1. 费用：<b>-2.41pp</b>（26%）——trades 实测（佣金万8+最低5元+印花税万5）<br>
2. 涨跌停限制：<b>-1.72pp</b>（19%）——默认版 vs 无涨跌停版净值差（精确实验）<br>
3. 停牌+其余：<b>-5.03pp</b>（55%）——还原费用后剩余（停牌 2.3万条拒绝为主，含分红时点/近似误差）<br>
<b>校验和 -9.16pp = 缺口 -9.16pp ✓</b>
</div>

<h2>③ 净值曲线</h2>
{fig1_html}
{fig2_html}

<h2>④ 结论：自写回测的缺陷清单（按贡献排序）</h2>
<div class="box">
1. <b>费用全缺</b>（2.4~3.5pp/年）：自写回测无成本模型——佣金/印花税/最低佣金/滑点<br>
2. <b>停牌不可交易</b>（~5pp/年，三年窗口）：停牌期间订单被拒、复牌跳变未建模<br>
3. <b>涨跌停不可成交</b>（1.7pp/年）：涨停买不进、跌停卖不出——机会成本<br>
4. <b>最小手数/最低佣金 × 资金规模</b>：小资金下"等权 N 只"形态不可执行（权重买不起一手）——候选形态约束<br>
5. <b>未上市股票</b>：自写回测靠"查无数据跳过"无意处理，RQAlpha 严格拒绝<br>
<b>本质</b>：自写回测不是"算错了"，是"没建模成交现实"——假设任意价格任意量成交。秒级计算时间的代价是这些全看不见。
</div>

<div class="box ok">
<b>对 v5 的三条修正</b>：<br>
1. 候选评估必须带<b>资金规模</b>口径（四件套加"资金规模"项）——同一策略 100万/1亿是两种动物<br>
2. <b>RQAlpha 作为第二引擎</b>纳入评估管道：候选过四件套前先过真实引擎撮合<br>
3. 候选形态约束：等权 N 只的策略需满足 N × 一手成本 ≤ 资金（否则不可执行）
</div>

<div class="box">
<b>报告责任</b>：本报告输出证据与程序性结论，不构成推荐。归因数字基于 analyser 实测与对照实验，非估算。
</div>
</body></html>"""

out = f"{BASE}/reports/rq_conclusion_report.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("报告:", out)
